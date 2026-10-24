"""Storage contract tests use real SQLite files and no Qt or external services."""

import asyncio
import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from curio.memory_contract import (
    ApprovalStatus,
    MemoryFilter,
    MemoryRecord,
    MemorySettings,
    MemorySource,
    MemoryType,
    StorageMode,
)
from curio.memory_store import SQLiteMemoryStore


def record(**changes):
    return replace(
        MemoryRecord(
            type=MemoryType.FACT,
            content="My project is Curio",
            source=MemorySource.USER,
        ),
        **changes,
    )


def store_at(path, **settings):
    return SQLiteMemoryStore(MemorySettings(enabled=True, storage_path=path, **settings))


def test_crud_persistence_and_deletion(tmp_path):
    async def scenario():
        path = tmp_path / "nested" / "memory.sqlite3"
        item = record(approval_status=ApprovalStatus.APPROVED)
        async with store_at(path) as store:
            assert await store.create(item) == item
            assert await store.retrieve(item.id) == item
            edited = await store.update(replace(item, content="My project is Curio"))
            assert edited.approval_status == ApprovalStatus.PENDING
            assert edited.updated_at > item.updated_at
            assert edited.created_at == item.created_at
        async with store_at(path) as reopened:
            assert await reopened.retrieve(item.id) == edited
            assert await reopened.delete(item.id)
            assert not await reopened.delete(item.id)
            assert await reopened.retrieve(item.id) is None
            assert await reopened.search("Curio") == ()
            assert await reopened.list() == ()
        async with store_at(path) as reopened:
            assert await reopened.retrieve(item.id) is None

    asyncio.run(scenario())


def test_expiration_filters_search_pagination_and_clear(tmp_path):
    async def scenario():
        now = datetime.now(UTC)
        expired = record(
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(days=2),
            expires_at=now - timedelta(days=1),
        )
        approved = record(
            content="Prefer concise answers",
            type=MemoryType.PREFERENCE,
            preference_key="response.verbosity",
            approval_status=ApprovalStatus.APPROVED,
        )
        async with store_at(tmp_path / "m.db") as store:
            await store.create(expired)
            await store.create(approved)
            assert await store.list() == (approved,)
            assert len(await store.list(filters=MemoryFilter(include_expired=True))) == 2
            assert await store.retrieve(expired.id) == expired
            assert await store.search(
                "concise", filters=MemoryFilter(approval_status=ApprovalStatus.APPROVED)
            ) == (approved,)
            assert await store.search("Curio") == ()
            assert await store.search("   ") == ()
            assert await store.list(limit=0) == ()
            assert await store.list(offset=1) == ()
            assert await store.clear() == 2
            assert await store.clear() == 0

    asyncio.run(scenario())


def test_duplicate_ids_and_content_are_atomic_across_instances(tmp_path):
    async def scenario():
        path = tmp_path / "m.db"
        async with store_at(path) as first, store_at(path) as second:
            item = record()
            outcomes = await asyncio.gather(
                first.create(item), second.create(item), return_exceptions=True
            )
            assert sum(isinstance(result, ValueError) for result in outcomes) == 1
            with pytest.raises(ValueError):
                await second.create(record(content="  MY project is CURIO  "))
            other = await second.create(record(content="Another fact"))
            with pytest.raises(ValueError):
                await first.update(replace(other, content=item.content))
            assert (await second.retrieve(other.id)).content == "Another fact"
            assert len(await first.list()) == 2

    asyncio.run(scenario())


def test_disabled_blocks_writes_but_allows_management(tmp_path):
    async def scenario():
        path = tmp_path / "m.db"
        item = record()
        async with SQLiteMemoryStore(MemorySettings(storage_path=path)) as store:
            with pytest.raises(PermissionError):
                await store.create(item)
            assert not path.exists()
        async with store_at(path) as store:
            await store.create(item)
        async with SQLiteMemoryStore(MemorySettings(storage_path=path)) as store:
            assert await store.retrieve(item.id) == item
            # Explicit management remains available while new learning is blocked.
            assert (await store.update(item)).id == item.id
            with pytest.raises(PermissionError):
                await store.create(record(content="New learning remains blocked"))
            assert await store.delete(item.id)

    asyncio.run(scenario())


def test_session_storage_and_default_expiration(tmp_path):
    async def scenario():
        path = tmp_path / "never-created.db"
        async with store_at(
            path, storage_mode=StorageMode.SESSION, default_expiration_days=7
        ) as store:
            saved = await store.create(record())
            assert saved.expires_at == saved.created_at + timedelta(days=7)
            assert await store.retrieve(saved.id) == saved
        assert not path.exists()
        async with store_at(path, storage_mode=StorageMode.SESSION) as store:
            assert await store.list() == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "changes",
    [
        {"content": " "},
        {"id": ""},
        {"confidence": float("nan")},
        {"confidence": 2},
        {"created_at": datetime(2026, 1, 1)},
        {"type": "unknown"},
        {"type": MemoryType.PREFERENCE},
        {"source_id": "api_key=secret"},
        {"content": "password: hunter2"},
        {"content": "api_key = abc123"},
        {"content": "data:image/png;base64,abc"},
        {"content": "data:audio/wav;base64,abc"},
    ],
)
def test_invalid_or_sensitive_records_never_persist(tmp_path, changes):
    async def scenario():
        async with store_at(tmp_path / "m.db") as store:
            with pytest.raises(ValueError):
                await store.create(record(**changes))
            assert await store.list() == ()

    asyncio.run(scenario())


def test_missing_update_identity_and_invalid_queries(tmp_path):
    async def scenario():
        async with store_at(tmp_path / "m.db") as store:
            item = record()
            with pytest.raises(KeyError):
                await store.update(item)
            await store.create(item)
            with pytest.raises(ValueError):
                await store.update(replace(item, created_at=item.created_at - timedelta(days=1)))
            with pytest.raises(ValueError):
                await store.list(limit=-1)
            with pytest.raises(ValueError):
                await store.search("hello", limit=-1)

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["corrupt", "future", "unversioned", "directory"])
def test_database_failures_are_safe(tmp_path, kind):
    path = tmp_path / "m.db"
    if kind == "corrupt":
        path.write_bytes(b"not a database")
    elif kind == "directory":
        path.mkdir()
    else:
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE precious (value TEXT)")
            conn.execute(f"PRAGMA user_version = {99 if kind == 'future' else 0}")

    async def scenario():
        async with store_at(path) as store:
            with pytest.raises(OSError):
                await store.create(record())

    asyncio.run(scenario())
    if kind in {"future", "unversioned"}:
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT * FROM precious").fetchall() == []


def test_schema_version_and_worker_thread(tmp_path, monkeypatch):
    original = sqlite3.connect
    owner = threading.get_ident()
    threads = []

    def connect(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)

    async def scenario():
        async with store_at(tmp_path / "m.db") as store:
            await asyncio.gather(*(store.create(record(content=f"Fact {i}")) for i in range(12)))
            assert len(await store.list()) == 12
        with pytest.raises(RuntimeError):
            await store.list()

    asyncio.run(scenario())
    assert threads and all(thread != owner for thread in threads)
    with original(tmp_path / "m.db") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_ordering_preserves_microseconds_and_search_ties(tmp_path):
    async def scenario():
        now = datetime.now(UTC)
        older = record(id="a", content="Curio older", created_at=now, updated_at=now)
        newer = record(
            id="z",
            content="Curio newer",
            created_at=now,
            updated_at=now + timedelta(microseconds=1),
        )
        async with store_at(tmp_path / "m.db") as store:
            await store.create(older)
            await store.create(newer)
            assert await store.list() == (newer, older)
            assert await store.search("Curio") == (newer, older)
            assert await store.search("newer Curio") == (newer, older)
            assert await store.search("%' OR 1=1 --") == ()

    asyncio.run(scenario())


def test_sqlite_constraint_and_lock_failure(tmp_path):
    async def scenario():
        path = tmp_path / "m.db"
        async with store_at(path) as store:
            item = await store.create(record())
            with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO memories SELECT 'other', type, content, source, "
                    "confidence, created_at, updated_at, expires_at, approval_status, "
                    "source_id, preference_key, normalized_content FROM memories"
                )
            with sqlite3.connect(path) as locker:
                locker.execute("BEGIN EXCLUSIVE")
                with pytest.raises(OSError, match="database operation failed"):
                    await store.create(record(content="Locked write"))
                locker.rollback()
            assert await store.list() == (item,)
            assert await store.create(record(content="Recovered write"))

    asyncio.run(scenario())


def test_initialization_failure_rolls_back_schema(tmp_path, monkeypatch):
    path = tmp_path / "m.db"

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith("CREATE UNIQUE INDEX"):
                raise sqlite3.OperationalError("injected migration failure")
            return super().execute(sql, *args)

    original = sqlite3.connect

    def connect(*args, **kwargs):
        return original(*args, **kwargs, factory=FailingConnection)

    monkeypatch.setattr(sqlite3, "connect", connect)

    async def scenario():
        async with store_at(path) as store:
            with pytest.raises(OSError):
                await store.create(record())

    asyncio.run(scenario())
    with original(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []


def test_blocked_worker_does_not_block_event_loop(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = SQLiteMemoryStore._create

    def slow_create(self, conn, item):
        entered.set()
        assert release.wait(timeout=5)
        return original(self, conn, item)

    monkeypatch.setattr(SQLiteMemoryStore, "_create", slow_create)

    async def scenario():
        async with store_at(tmp_path / "m.db") as store:
            pending = asyncio.create_task(store.create(record()))
            try:
                async with asyncio.timeout(2):
                    while not entered.is_set():
                        await asyncio.sleep(0.001)
                assert not pending.done()
                # This coroutine is still running while SQLite's worker is blocked.
                await asyncio.sleep(0)
            finally:
                release.set()
            await pending

    asyncio.run(scenario())


def test_approval_updates_and_corrupt_rows(tmp_path):
    async def scenario():
        path = tmp_path / "m.db"
        async with store_at(path) as store:
            item = await store.create(record())
            approved = await store.update(replace(item, approval_status=ApprovalStatus.APPROVED))
            assert approved.approval_status == ApprovalStatus.APPROVED
            assert (
                await store.list(filters=MemoryFilter(approval_status=ApprovalStatus.PENDING)) == ()
            )
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE memories SET created_at = 'bad timestamp'")
            with pytest.raises(OSError, match="invalid record"):
                await store.retrieve(item.id)

    asyncio.run(scenario())
