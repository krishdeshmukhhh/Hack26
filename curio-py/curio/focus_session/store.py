"""Local SQLite ``SessionStore`` for focus-session summaries (section F, Privacy).

Summaries stay on the device. All SQLite work runs on one dedicated worker
thread, never on the Qt event loop; await ``close()`` at shutdown. Saving a
summary with an existing ``plan_id`` replaces it, so the summary can be saved
when the session ends and again once the learner adds a reflection.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_path

from curio.focus_contract import SessionSummary

_SCHEMA_VERSION = 1
_COLUMNS = (
    "plan_id, goal, started_at, ended_at, on_goal_seconds, off_goal_seconds, "
    "break_seconds, drift_count, interventions, false_alarms, concepts, reflection, "
    "distractions"
)


def default_path() -> Path:
    return user_data_path("Curio") / "focus_sessions.sqlite3"


def _values(s: SessionSummary) -> tuple:
    return (
        s.plan_id,
        s.goal,
        # UTC text sorts chronologically.
        s.started_at.astimezone(UTC).isoformat(timespec="microseconds"),
        s.ended_at.astimezone(UTC).isoformat(timespec="microseconds"),
        float(s.on_goal_seconds),
        float(s.off_goal_seconds),
        float(s.break_seconds),
        int(s.drift_count),
        int(s.interventions),
        int(s.false_alarms),
        json.dumps(list(s.concepts_practised)),
        s.reflection,
        json.dumps(list(s.distractions)),
    )


def _summary(row: sqlite3.Row) -> SessionSummary:
    return SessionSummary(
        plan_id=row["plan_id"],
        goal=row["goal"],
        started_at=datetime.fromisoformat(row["started_at"]),
        ended_at=datetime.fromisoformat(row["ended_at"]),
        on_goal_seconds=row["on_goal_seconds"],
        off_goal_seconds=row["off_goal_seconds"],
        break_seconds=row["break_seconds"],
        drift_count=row["drift_count"],
        interventions=row["interventions"],
        false_alarms=row["false_alarms"],
        concepts_practised=tuple(json.loads(row["concepts"])),
        reflection=row["reflection"],
        distractions=tuple(json.loads(row["distractions"])),
    )


class SqliteSessionStore:
    """Implements ``focus_contract.SessionStore``. ``path=":memory:"`` for tests."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = str(path) if path is not None else str(default_path())
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="curio-focus")
        self._conn: sqlite3.Connection | None = None
        self._closed = False

    async def __aenter__(self) -> SqliteSessionStore:
        return self

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

    def _connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA secure_delete = ON")
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > _SCHEMA_VERSION or version < 0:
                raise OSError("Unsupported focus session database schema version")
            if version == 0:
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone():
                    raise OSError("Unrecognized unversioned focus database; migration refused")
                conn.execute("""CREATE TABLE summaries (
                    plan_id TEXT PRIMARY KEY NOT NULL CHECK(length(trim(plan_id)) > 0),
                    goal TEXT NOT NULL,
                    started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
                    on_goal_seconds REAL NOT NULL CHECK(on_goal_seconds >= 0),
                    off_goal_seconds REAL NOT NULL CHECK(off_goal_seconds >= 0),
                    break_seconds REAL NOT NULL CHECK(break_seconds >= 0),
                    drift_count INTEGER NOT NULL CHECK(drift_count >= 0),
                    interventions INTEGER NOT NULL CHECK(interventions >= 0),
                    false_alarms INTEGER NOT NULL CHECK(false_alarms >= 0),
                    concepts TEXT NOT NULL, reflection TEXT NOT NULL,
                    distractions TEXT NOT NULL
                )""")
                conn.execute("CREATE INDEX summaries_started ON summaries(started_at)")
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            conn.execute(f"SELECT {_COLUMNS} FROM summaries LIMIT 0")
            conn.commit()
        except BaseException:
            conn.rollback()
            conn.close()
            raise
        self._conn = conn
        return conn

    async def _run(self, fn, *args):
        if self._closed:
            raise RuntimeError("Focus session store is closed")
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, lambda: fn(self._connection(), *args)
        )

    async def save_summary(self, summary: SessionSummary) -> None:
        if not summary.plan_id.strip():
            raise ValueError("Summary needs a plan id")
        if summary.ended_at < summary.started_at:
            raise ValueError("Summary ends before it starts")
        await self._run(_save, _values(summary))

    async def summaries(self, limit: int = 50) -> tuple[SessionSummary, ...]:
        return await self._run(_list, max(0, int(limit)))

    async def clear(self) -> None:
        await self._run(_clear)


def _save(conn: sqlite3.Connection, values: tuple) -> None:
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO summaries ({_COLUMNS}) VALUES "
            f"({', '.join('?' * len(values))})",
            values,
        )


def _list(conn: sqlite3.Connection, limit: int) -> tuple[SessionSummary, ...]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM summaries ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return tuple(_summary(row) for row in rows)


def _clear(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("DELETE FROM summaries")
    conn.execute("VACUUM")
