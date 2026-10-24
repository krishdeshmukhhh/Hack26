"""Local SQLite implementation of the shared memory storage contract.

Use ``async with SQLiteMemoryStore(settings)`` or await ``close()`` at shutdown.
Settings are fixed for the lifetime of an instance; close and reopen to change
them. All SQLite work runs on one dedicated worker, never on the Qt event loop.
Only caller-redacted text belongs here: this is not a secret classification API.
Obvious credential assignments and image/audio data URLs are rejected as defense
in depth; callers must exclude all screenshots, audio and confidential content.
Cancellation propagates to the awaiter, but a write already running in SQLite
may still commit. Close drains queued work before releasing the connection.
"""

from __future__ import annotations

import asyncio
import math
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from platformdirs import user_data_path

from curio.memory_contract import (
    ApprovalStatus,
    MemoryFilter,
    MemoryRecord,
    MemorySettings,
    MemorySource,
    MemoryType,
    StorageMode,
)

_SCHEMA_VERSION = 1
_SENSITIVE = re.compile(
    r"(?:password|passwd|api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*\S+"
    r"|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{16,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|data:(?:image|audio)/",
    re.IGNORECASE,
)
_COLUMNS = (
    "id, type, content, source, confidence, created_at, updated_at, expires_at, "
    "approval_status, source_id, preference_key"
)


def _validate(record: MemoryRecord) -> MemoryRecord:
    """Validate transport containers before touching SQLite; never echo content."""
    try:
        item = replace(
            record,
            type=MemoryType(record.type),
            source=MemorySource(record.source),
            approval_status=ApprovalStatus(record.approval_status),
        )
    except (ValueError, TypeError):
        raise ValueError("Invalid memory enum value") from None
    for value in (item.id, item.content):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Memory ID and content must be nonempty text")
    for value in (item.source_id, item.preference_key):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Optional memory metadata must be nonempty text")
    if item.type == MemoryType.PREFERENCE and not item.preference_key:
        raise ValueError("Preference memories require a preference key")
    if item.type != MemoryType.PREFERENCE and item.preference_key is not None:
        raise ValueError("Only preference memories may have a preference key")
    if (
        isinstance(item.confidence, bool)
        or not isinstance(item.confidence, (float, int))
        or not math.isfinite(item.confidence)
        or not 0 <= item.confidence <= 1
    ):
        raise ValueError("Confidence must be finite and between zero and one")
    if item.created_at is None or item.updated_at is None:
        raise ValueError("Creation and update timestamps are required")
    for timestamp in (item.created_at, item.updated_at, item.expires_at):
        if timestamp is not None and (
            not isinstance(timestamp, datetime) or timestamp.utcoffset() != timedelta(0)
        ):
            raise ValueError("Memory timestamps must be timezone-aware UTC")
    if item.updated_at < item.created_at:
        raise ValueError("Update timestamp precedes creation")
    if item.expires_at is not None and item.expires_at <= item.created_at:
        raise ValueError("Expiration must follow creation")
    if any(
        _SENSITIVE.search(value)
        for value in (
            item.id,
            item.content,
            item.source_id or "",
            item.preference_key or "",
        )
    ):
        raise ValueError("Sensitive payloads are not accepted in memory storage")
    return item


def _values(item: MemoryRecord) -> tuple:
    return (
        item.id,
        item.type.value,
        item.content,
        item.source.value,
        item.confidence,
        item.created_at.isoformat(timespec="microseconds"),
        item.updated_at.isoformat(timespec="microseconds"),
        item.expires_at.isoformat(timespec="microseconds") if item.expires_at else None,
        item.approval_status.value,
        item.source_id,
        item.preference_key,
        " ".join(item.content.split()).casefold(),
    )


def _record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        type=MemoryType(row["type"]),
        content=row["content"],
        source=MemorySource(row["source"]),
        confidence=row["confidence"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
        approval_status=ApprovalStatus(row["approval_status"]),
        source_id=row["source_id"],
        preference_key=row["preference_key"],
    )


class SQLiteMemoryStore:
    """Async MemoryStore with atomic writes and lazy, versioned initialization.

    Duplicate means the same ID, or identical type, preference key and content
    after Unicode case folding and whitespace normalization, in any approval or
    expiration state. Delete an old duplicate before recreating it.
    """

    def __init__(self, settings: MemorySettings | None = None) -> None:
        settings = settings if settings is not None else MemorySettings()
        if type(settings.enabled) is not bool:
            raise ValueError("Memory enabled state must be a boolean")
        StorageMode(settings.storage_mode)
        days = settings.default_expiration_days
        if days is not None and (type(days) is not int or days <= 0):
            raise ValueError("Default expiration days must be a positive integer")
        self._settings = settings
        self._path = (
            Path(settings.storage_path)
            if settings.storage_path is not None
            else (user_data_path("Curio") / "memory.sqlite3")
        )
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="curio-memory")
        self._conn: sqlite3.Connection | None = None
        self._closed = False

    async def __aenter__(self) -> SQLiteMemoryStore:
        if self._closed:
            raise RuntimeError("Memory store is closed")
        return self

    def reconfigure(self, settings: MemorySettings) -> None:
        """Update policy on the owning loop between serialized calls; retain session data."""
        if (settings.storage_mode, settings.storage_path) != (
            self._settings.storage_mode, self._settings.storage_path
        ):
            raise ValueError("Reopen storage when changing storage mode or path")
        self._settings = settings

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            future = asyncio.get_running_loop().run_in_executor(self._executor, self._close)
            self._executor.shutdown(wait=False)
            await asyncio.shield(future)

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _connection(self) -> sqlite3.Connection | None:
        if self._conn is not None:
            return self._conn
        session = self._settings.storage_mode == StorageMode.SESSION
        if not self._settings.enabled and (session or not self._path.exists()):
            return None
        if not session:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(":memory:" if session else str(self._path), timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            # No WAL sidecar retaining deleted content; overwrite deleted cells.
            conn.execute("PRAGMA secure_delete = ON")
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > _SCHEMA_VERSION or version < 0:
                raise OSError("Unsupported memory database schema version")
            if version == 0:
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone():
                    raise OSError("Unrecognized unversioned memory database; migration refused")
                # Version zero is an empty database. Future migrations belong here,
                # inside this same transaction; never reset or drop unknown schemas.
                conn.execute("""CREATE TABLE memories (
                    id TEXT PRIMARY KEY NOT NULL CHECK(length(trim(id)) > 0),
                    type TEXT NOT NULL CHECK(type IN ('fact','preference','project')),
                    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
                    source TEXT NOT NULL CHECK(source IN
                        ('user','explicit_feedback','automatic','import')),
                    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT,
                    approval_status TEXT NOT NULL CHECK(approval_status IN
                        ('pending','approved','rejected')),
                    source_id TEXT, preference_key TEXT, normalized_content TEXT NOT NULL,
                    CHECK((type = 'preference' AND preference_key IS NOT NULL
                           AND length(trim(preference_key)) > 0)
                          OR (type != 'preference' AND preference_key IS NULL))
                )""")
                conn.execute(
                    "CREATE UNIQUE INDEX memory_dedup ON memories "
                    "(type, coalesce(preference_key, ''), normalized_content)"
                )
                conn.execute("CREATE INDEX memory_expiration ON memories(expires_at)")
                conn.execute("PRAGMA user_version = 1")
            # Fail safely on a falsely versioned or incomplete schema.
            conn.execute(f"SELECT {_COLUMNS}, normalized_content FROM memories LIMIT 0")
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(memories)")}
            if "memory_dedup" not in indexes:
                raise OSError("Memory database is missing its duplicate constraint")
            conn.commit()
        except BaseException:
            conn.rollback()
            conn.close()
            raise
        self._conn = conn
        return conn

    async def _run(self, operation: str, *args):
        if self._closed:
            raise RuntimeError("Memory store is closed")
        return await asyncio.get_running_loop().run_in_executor(
            self._executor,
            self._execute,
            operation,
            args,
        )

    def _execute(self, operation: str, args: tuple):
        try:
            return getattr(self, f"_{operation}")(self._connection(), *args)
        except sqlite3.IntegrityError:
            raise ValueError("Duplicate memory or invalid storage constraint") from None
        except (sqlite3.Error, OverflowError):
            raise OSError("Memory database operation failed") from None

    def _require_enabled(self) -> None:
        if not self._settings.enabled:
            raise PermissionError("Memory is disabled; writes are not permitted")

    async def create(self, record: MemoryRecord) -> MemoryRecord:
        self._require_enabled()
        item = _validate(record)
        if item.expires_at is None and self._settings.default_expiration_days is not None:
            try:
                item = replace(
                    item,
                    expires_at=item.created_at
                    + timedelta(days=self._settings.default_expiration_days),
                )
            except OverflowError:
                raise ValueError("Default expiration exceeds timestamp range") from None
        return await self._run("create", item)

    def _create(self, conn, item):
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"INSERT INTO memories ({_COLUMNS}, normalized_content) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _values(item),
            )
        return item

    async def retrieve(self, memory_id: str) -> MemoryRecord | None:
        return await self._run("retrieve", memory_id)

    def _retrieve(self, conn, memory_id):
        if conn is None:
            return None
        row = conn.execute(f"SELECT {_COLUMNS} FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._decode(row) if row is not None else None

    @staticmethod
    def _decode(row):
        try:
            return _validate(_record(row))
        except (ValueError, TypeError):
            raise OSError("Memory database contains an invalid record") from None

    async def update(self, record: MemoryRecord) -> MemoryRecord:
        # Explicit management edits/approval remain available while learning is disabled.
        return await self._run("update", _validate(record))

    def _update(self, conn, item):
        if conn is None:
            raise KeyError(item.id)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = self._retrieve(conn, item.id)
            if previous is None:
                raise KeyError(item.id)
            if item.created_at != previous.created_at:
                raise ValueError("Creation timestamp cannot change")
            status = item.approval_status
            if any(
                getattr(previous, key) != getattr(item, key)
                for key in (
                    "content",
                    "source",
                    "source_id",
                    "preference_key",
                    "type",
                )
            ):
                status = ApprovalStatus.PENDING
            item = replace(
                item,
                approval_status=status,
                updated_at=max(
                    datetime.now(UTC),
                    previous.updated_at + timedelta(microseconds=1),
                ),
            )
            columns = _COLUMNS.split(", ")[1:] + ["normalized_content"]
            conn.execute(
                "UPDATE memories SET "
                + ", ".join(f"{key} = ?" for key in columns)
                + " WHERE id = ?",
                (*_values(item)[1:], item.id),
            )
        return item

    async def delete(self, memory_id: str) -> bool:
        return await self._run("delete", memory_id)

    def _delete(self, conn, memory_id):
        if conn is None:
            return False
        with conn:
            return conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount > 0

    async def clear(self) -> int:
        return await self._run("clear")

    def _clear(self, conn):
        if conn is None:
            return 0
        with conn:
            return conn.execute("DELETE FROM memories").rowcount

    async def list(
        self,
        *,
        filters: MemoryFilter | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[MemoryRecord, ...]:
        self._validate_page(limit, offset)
        return await self._run("list", filters or MemoryFilter(), limit, offset)

    @staticmethod
    def _validate_page(limit, offset=0):
        if type(limit) is not int or type(offset) is not int or limit < 0 or offset < 0:
            raise ValueError("Limits and offsets must be nonnegative integers")

    @staticmethod
    def _where(filters):
        clauses, values = [], []
        if not filters.include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            values.append(datetime.now(UTC).isoformat(timespec="microseconds"))
        for key, enum in (("type", MemoryType), ("approval_status", ApprovalStatus)):
            value = getattr(filters, key)
            if value is not None:
                clauses.append(f"{key} = ?")
                values.append(enum(value).value)
        if filters.preference_key is not None:
            clauses.append("preference_key = ?")
            values.append(filters.preference_key)
        return " AND ".join(clauses) or "1", values

    def _list(self, conn, filters, limit, offset):
        if conn is None:
            return ()
        where, values = self._where(filters)
        return tuple(
            self._decode(row)
            for row in conn.execute(
                f"SELECT {_COLUMNS} FROM memories WHERE {where} "
                "ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            )
        )

    async def search(
        self,
        query: str,
        *,
        filters: MemoryFilter | None = None,
        limit: int = 20,
    ) -> tuple[MemoryRecord, ...]:
        self._validate_page(limit)
        if not isinstance(query, str):
            raise ValueError("Search query must be text")
        if not query.strip() or limit == 0:
            return ()
        return await self._run("search", query, filters or MemoryFilter(), limit)

    def _search(self, conn, query, filters, limit):
        if conn is None:
            return ()
        # Literal keyword matching: SQL metacharacters never become query syntax.
        # Ranking is local and deliberately independent of embeddings/providers.
        terms = set(query.casefold().split())
        where, values = self._where(filters)
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM memories WHERE {where} ORDER BY updated_at DESC, id ASC",
            values,
        )
        scored = [(sum(term in row["content"].casefold() for term in terms), row) for row in rows]
        scored.sort(key=lambda entry: -entry[0])
        return tuple(self._decode(row) for score, row in scored if score > 0)[:limit]
