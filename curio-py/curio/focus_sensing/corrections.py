"""Local SQLite store for the learner's "that wasn't a distraction" corrections.

Keyed by app plus a normalised title pattern, so "Inbox (3) - Gmail" and
"Inbox (4) - Gmail" share one correction. Titles stay on the device. All
SQLite work runs on one dedicated worker thread, never on the Qt event loop;
the store is opened lazily on first use.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_path

from curio.focus_contract import TrackJudgment

_SCHEMA_VERSION = 1
_COUNTER_RE = re.compile(r"[\(\[]\d+[\)\]]")  # unread counters: "(3)", "[12]"
_DIGITS_RE = re.compile(r"\d+")
_NON_WORD_RE = re.compile(r"[^a-z0-9#]+")
MEMORY = ":memory:"


def title_pattern(window_title: str) -> str:
    """Normalise a title for matching: lowercase, counters dropped, digit runs as ``#``."""
    text = _COUNTER_RE.sub(" ", window_title.lower())
    text = _DIGITS_RE.sub("#", text)
    return _NON_WORD_RE.sub(" ", text).strip()


class SQLiteCorrectionStore:
    """Async (app, title pattern) -> TrackJudgment map with a write-through cache.

    ``path`` is required so tests never touch the user's data directory by
    accident; pass ``SQLiteCorrectionStore.default_path()`` in the app, or
    ``":memory:"`` for a session-only store.
    """

    def __init__(self, path: Path | str, *, clock: Callable[[], datetime] | None = None) -> None:
        self._path = str(path)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="curio-focus")
        self._conn: sqlite3.Connection | None = None
        self._cache: dict[tuple[str, str], TrackJudgment] | None = None
        self._closed = False

    @staticmethod
    def default_path() -> Path:
        return user_data_path("Curio") / "focus_corrections.sqlite3"

    async def __aenter__(self) -> SQLiteCorrectionStore:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def get(self, app: str, pattern: str) -> TrackJudgment | None:
        cache = await self._loaded()
        return cache.get((app, pattern))

    async def put(self, app: str, pattern: str, judgment: TrackJudgment) -> None:
        cache = await self._loaded()
        judgment = TrackJudgment(judgment)
        stamp = self._clock().isoformat()
        await self._run(self._put, app, pattern, judgment.value, stamp)
        cache[(app, pattern)] = judgment

    async def remove(self, app: str, pattern: str) -> None:
        cache = await self._loaded()
        await self._run(self._remove, app, pattern)
        cache.pop((app, pattern), None)

    async def all(self) -> dict[tuple[str, str], TrackJudgment]:
        return dict(await self._loaded())

    async def clear(self) -> None:
        cache = await self._loaded()
        await self._run(self._clear)
        cache.clear()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        future = asyncio.get_running_loop().run_in_executor(self._executor, self._close)
        self._executor.shutdown(wait=False)
        await asyncio.shield(future)

    # --- worker thread ---------------------------------------------------------

    async def _loaded(self) -> dict[tuple[str, str], TrackJudgment]:
        if self._cache is None:
            rows = await self._run(self._load)
            self._cache = {(app, pattern): TrackJudgment(value) for app, pattern, value in rows}
        return self._cache

    async def _run(self, fn, *args):
        if self._closed:
            raise RuntimeError("Correction store is closed")
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)

    def _connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self._path != MEMORY:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=2.0)
        conn.execute("PRAGMA secure_delete = ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > _SCHEMA_VERSION:
            conn.close()
            raise OSError("Unsupported focus corrections schema version")
        if version == 0:
            with conn:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS corrections (
                        app TEXT NOT NULL,
                        pattern TEXT NOT NULL,
                        judgment TEXT NOT NULL
                            CHECK(judgment IN ('on_goal','off_goal','unsure','on_break')),
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (app, pattern)
                    )"""
                )
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        self._conn = conn
        return conn

    def _load(self) -> list[tuple[str, str, str]]:
        return (
            self._connection().execute("SELECT app, pattern, judgment FROM corrections").fetchall()
        )

    def _put(self, app: str, pattern: str, judgment: str, stamp: str) -> None:
        conn = self._connection()
        with conn:
            conn.execute(
                "INSERT INTO corrections (app, pattern, judgment, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(app, pattern) DO UPDATE SET "
                "judgment = excluded.judgment, updated_at = excluded.updated_at",
                (app, pattern, judgment, stamp),
            )

    def _remove(self, app: str, pattern: str) -> None:
        conn = self._connection()
        with conn:
            conn.execute("DELETE FROM corrections WHERE app = ? AND pattern = ?", (app, pattern))

    def _clear(self) -> None:
        conn = self._connection()
        with conn:
            conn.execute("DELETE FROM corrections")

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
