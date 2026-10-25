"""Local, append-only SQLite log of walkthrough step events."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from platformdirs import user_data_path

from curio.learning_contract import AssistanceLevel, ElementRef, StepEvent, StepOutcome

_SCHEMA_VERSION = 1
_COLUMNS = (
    "id, walkthrough_id, app, task, step_index, instruction, assistance, outcome, "
    "element_label, element_x, element_y, element_window, concepts, app_version, occurred_at"
)


def default_event_log_path() -> Path:
    return user_data_path("Curio") / "learning_events.sqlite3"


def _row(event: StepEvent) -> tuple:
    element = event.element
    return (
        event.id,
        event.walkthrough_id,
        event.app,
        event.task,
        event.step_index,
        event.instruction,
        event.assistance.value,
        event.outcome.value,
        element.label if element is not None else None,
        element.x if element is not None else None,
        element.y if element is not None else None,
        element.window_title if element is not None else None,
        json.dumps(list(event.concepts)),
        event.app_version,
        event.occurred_at.isoformat(),
    )


def _event(row: sqlite3.Row) -> StepEvent:
    element = None
    if row["element_label"] is not None:
        element = ElementRef(
            label=row["element_label"],
            x=row["element_x"],
            y=row["element_y"],
            window_title=row["element_window"] or "",
        )
    return StepEvent(
        id=row["id"],
        walkthrough_id=row["walkthrough_id"],
        app=row["app"],
        task=row["task"],
        step_index=row["step_index"],
        instruction=row["instruction"],
        assistance=AssistanceLevel(row["assistance"]),
        outcome=StepOutcome(row["outcome"]),
        element=element,
        concepts=tuple(json.loads(row["concepts"])),
        app_version=row["app_version"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
    )


class SqliteEventLog:
    """``EventLog`` backed by one SQLite file. Created lazily on first use."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else default_event_log_path()
        # Calls run on worker threads; one lock keeps them serialized.
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > _SCHEMA_VERSION:
                raise OSError("Unsupported learning event database schema version")
            if version == 0:
                conn.execute("""CREATE TABLE IF NOT EXISTS step_events (
                    id TEXT PRIMARY KEY NOT NULL,
                    walkthrough_id TEXT NOT NULL,
                    app TEXT NOT NULL,
                    task TEXT NOT NULL,
                    step_index INTEGER NOT NULL CHECK(step_index >= 1),
                    instruction TEXT NOT NULL,
                    assistance TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    element_label TEXT, element_x REAL, element_y REAL, element_window TEXT,
                    concepts TEXT NOT NULL,
                    app_version TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                )""")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS step_events_walkthrough "
                    "ON step_events(walkthrough_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS step_events_recent "
                    "ON step_events(occurred_at)"
                )
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                conn.commit()
        except BaseException:
            conn.close()
            raise
        return conn

    def _run(self, fn, *args):
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    return fn(conn, *args)
            finally:
                conn.close()

    async def append(self, event: StepEvent) -> None:
        await asyncio.to_thread(self._run, self._append, event)

    @staticmethod
    def _append(conn: sqlite3.Connection, event: StepEvent) -> None:
        conn.execute(
            f"INSERT INTO step_events ({_COLUMNS}) VALUES ({', '.join('?' * 15)})",
            _row(event),
        )

    async def walkthrough(self, walkthrough_id: str) -> tuple[StepEvent, ...]:
        return await asyncio.to_thread(self._run, self._walkthrough, walkthrough_id)

    @staticmethod
    def _walkthrough(conn: sqlite3.Connection, walkthrough_id: str) -> tuple[StepEvent, ...]:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM step_events WHERE walkthrough_id = ? "
            "ORDER BY occurred_at, rowid",
            (walkthrough_id,),
        )
        return tuple(_event(row) for row in rows)

    async def recent(self, limit: int = 200, app: str | None = None) -> tuple[StepEvent, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        return await asyncio.to_thread(self._run, self._recent, limit, app)

    @staticmethod
    def _recent(
        conn: sqlite3.Connection, limit: int, app: str | None
    ) -> tuple[StepEvent, ...]:
        where, args = ("WHERE app = ? ", (app,)) if app is not None else ("", ())
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM step_events {where}"
            "ORDER BY occurred_at DESC, rowid DESC LIMIT ?",
            (*args, limit),
        )
        return tuple(_event(row) for row in rows)

    async def clear(self) -> None:
        await asyncio.to_thread(self._run, self._clear)

    @staticmethod
    def _clear(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM step_events")
