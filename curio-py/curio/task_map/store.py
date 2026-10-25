"""SQLite task map: verified paths from finished walkthroughs on this machine.

All SQLite work runs on one dedicated worker thread, never on the Qt event loop.
Use ``async with SqliteTaskMap(path)`` or await ``close()`` at shutdown.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

from curio.learning_contract import (
    ElementRef,
    PathSource,
    PathStep,
    StepEvent,
    StepOutcome,
    TaskPath,
    WalkthroughSummary,
    task_key,
)
from curio.task_map.difficulty import LocalDifficulty
from curio.task_map.matching import MATCH_THRESHOLD, task_similarity

_SCHEMA_VERSION = 1
RECENT_WINDOW = timedelta(days=30)
RECENT_WEIGHT = 2  # a verification inside RECENT_WINDOW counts this many times
# A local path wins unless a shared one is more than this many times stronger.
LOCAL_PREFERENCE = 1.5
# Candidates whose task matches within this margin of the best match compete on strength.
_MATCH_MARGIN = 0.15
_STUCK = (StepOutcome.RETRIED, StepOutcome.TIMED_OUT)


def default_path() -> Path:
    return user_data_path("Curio") / "task_map.sqlite3"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ts(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def clean_steps(events: Sequence[StepEvent]) -> tuple[PathStep, ...]:
    """Last SUCCEEDED attempt per step index, in index order, renumbered from 1."""
    kept: dict[int, StepEvent] = {}
    for event in events:
        if event.outcome == StepOutcome.SUCCEEDED:
            kept[event.step_index] = event
    return tuple(
        PathStep(
            index=n,
            instruction=event.instruction,
            element=event.element,
            concepts=event.concepts,
        )
        for n, (_, event) in enumerate(sorted(kept.items()), start=1)
    )


def signature(steps: Sequence[PathStep]) -> str:
    """The sequence of element labels that identifies a path."""
    return "\x1f".join(
        " ".join(s.element.label.lower().split()) if s.element is not None else ""
        for s in steps
    )


def _steps_to_json(steps: Sequence[PathStep]) -> str:
    return json.dumps(
        [
            {
                "index": s.index,
                "instruction": s.instruction,
                "element": None
                if s.element is None
                else {
                    "label": s.element.label,
                    "x": s.element.x,
                    "y": s.element.y,
                    "window_title": s.element.window_title,
                },
                "concepts": list(s.concepts),
                "difficulty": s.difficulty,
            }
            for s in steps
        ],
        sort_keys=True,
    )


def _steps_from_json(raw: str) -> tuple[PathStep, ...]:
    def element(e: dict[str, Any] | None) -> ElementRef | None:
        if e is None:
            return None
        return ElementRef(
            label=e["label"], x=e["x"], y=e["y"], window_title=e.get("window_title", "")
        )

    return tuple(
        PathStep(
            index=s["index"],
            instruction=s["instruction"],
            element=element(s["element"]),
            concepts=tuple(s["concepts"]),
            difficulty=s["difficulty"],
        )
        for s in json.loads(raw)
    )


@dataclass(frozen=True)
class _Row:
    path: TaskPath
    signature: str
    strength: float  # recency-weighted verifications (local) or verified_count (shared)


class SqliteTaskMap:
    """``TaskMap`` over one SQLite file; ``local_difficulty`` is its ``DifficultyProvider``.

    Paths for the same app and a matching task are alternatives keyed by their
    element-label sequence. ``find`` prefers the alternative with the most recent
    verifications, so a path fixed after an app update overtakes the stale one.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._path = Path(path) if path is not None else default_path()
        self._clock = clock
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="curio-task-map")
        self._conn: sqlite3.Connection | None = None
        self._closed = False
        self.local_difficulty = LocalDifficulty()

    async def __aenter__(self) -> SqliteTaskMap:
        if self._closed:
            raise RuntimeError("Task map is closed")
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

    async def _run(self, fn: Callable[..., Any], *args: Any) -> Any:
        if self._closed:
            raise RuntimeError("Task map is closed")
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, lambda: fn(self._connection(), *args)
        )

    def _connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > _SCHEMA_VERSION or version < 0:
                raise OSError("Unsupported task map schema version")
            if version == 0:
                conn.execute("""CREATE TABLE paths (
                    id TEXT PRIMARY KEY NOT NULL,
                    app TEXT NOT NULL, task TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('local','shared')),
                    signature TEXT NOT NULL, steps TEXT NOT NULL,
                    verified_count INTEGER NOT NULL CHECK(verified_count >= 0),
                    app_version TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(source, app, task, signature)
                )""")
                conn.execute("CREATE INDEX paths_app ON paths(app)")
                conn.execute("""CREATE TABLE verifications (
                    path_id TEXT NOT NULL REFERENCES paths(id) ON DELETE CASCADE,
                    verified_at TEXT NOT NULL
                )""")
                conn.execute("CREATE INDEX verifications_path ON verifications(path_id)")
                conn.execute("""CREATE TABLE step_stats (
                    app TEXT NOT NULL, task TEXT NOT NULL, step_index INTEGER NOT NULL,
                    attempts INTEGER NOT NULL, stuck INTEGER NOT NULL,
                    PRIMARY KEY(app, task, step_index)
                )""")
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            conn.commit()
        except BaseException:
            conn.rollback()
            conn.close()
            raise
        self._conn = conn
        self._refresh_difficulty(conn)
        return conn

    # --- TaskMap -------------------------------------------------------------

    async def record(self, summary: WalkthroughSummary) -> TaskPath | None:
        return await self._run(self._record, summary)

    async def find(self, app: str, task: str) -> TaskPath | None:
        return await self._run(self._find, app, task)

    async def paths(self, app: str | None = None) -> tuple[TaskPath, ...]:
        rows = await self._run(self._rows, app)
        return tuple(
            r.path for r in sorted(rows, key=lambda r: (r.path.app, r.path.task, -r.strength))
        )

    async def merge(self, shared: Sequence[TaskPath]) -> int:
        return await self._run(self._merge, tuple(shared))

    async def refresh_difficulty(self) -> None:
        """Load this machine's step history into ``local_difficulty`` (call at startup)."""
        await self._run(lambda conn: None)

    # --- worker-thread implementations ---------------------------------------

    def _rows(self, conn: sqlite3.Connection, app: str | None) -> list[_Row]:
        recent_since = _ts(self._clock() - RECENT_WINDOW)
        query = (
            "SELECT p.*, coalesce(sum(CASE WHEN v.verified_at >= ? THEN ? ELSE 1 END), 0) "
            "AS recency FROM paths p LEFT JOIN verifications v ON v.path_id = p.id"
        )
        params: list[Any] = [recent_since, RECENT_WEIGHT]
        if app is not None:
            query += " WHERE p.app = ?"
            params.append(app)
        query += " GROUP BY p.id"
        rows = []
        for row in conn.execute(query, params):
            source = PathSource(row["source"])
            path = TaskPath(
                id=row["id"],
                app=row["app"],
                task=row["task"],
                steps=_steps_from_json(row["steps"]),
                verified_count=row["verified_count"],
                source=source,
                app_version=row["app_version"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            strength = row["recency"] if source == PathSource.LOCAL else row["verified_count"]
            rows.append(_Row(path=path, signature=row["signature"], strength=float(strength)))
        return rows

    def _record(self, conn: sqlite3.Connection, summary: WalkthroughSummary) -> TaskPath | None:
        app, task = summary.app, task_key(summary.task)
        now = _ts(self._clock())
        try:
            for event in summary.steps:
                conn.execute(
                    "INSERT INTO step_stats VALUES (?, ?, ?, 1, ?) "
                    "ON CONFLICT(app, task, step_index) DO UPDATE SET "
                    "attempts = attempts + 1, stuck = stuck + excluded.stuck",
                    (app, task, event.step_index, int(event.outcome in _STUCK)),
                )
            result = self._reinforce(conn, summary, app, task, now) if summary.completed else None
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        self._refresh_difficulty(conn)
        return result

    def _reinforce(
        self, conn: sqlite3.Connection, summary: WalkthroughSummary, app: str, task: str, now: str
    ) -> TaskPath | None:
        steps = clean_steps(summary.steps)
        if not steps:
            return None
        sig = signature(steps)
        same = [
            (task_similarity(r.path.task, task, app), r)
            for r in self._rows(conn, app)
            if r.path.source == PathSource.LOCAL and r.signature == sig
        ]
        same = [(score, r) for score, r in same if score >= MATCH_THRESHOLD]
        if same:
            _, row = max(same, key=lambda pair: (pair[0], pair[1].strength))
            path = replace(
                row.path,
                steps=steps,
                verified_count=row.path.verified_count + 1,
                app_version=summary.app_version or row.path.app_version,
                updated_at=datetime.fromisoformat(now),
            )
            conn.execute(
                "UPDATE paths SET steps = ?, verified_count = ?, app_version = ?, updated_at = ? "
                "WHERE id = ?",
                (_steps_to_json(steps), path.verified_count, path.app_version, now, path.id),
            )
        else:
            path = TaskPath(
                app=app,
                task=task,
                steps=steps,
                app_version=summary.app_version,
                updated_at=datetime.fromisoformat(now),
            )
            conn.execute(
                "INSERT INTO paths VALUES (?, ?, ?, 'local', ?, ?, 1, ?, ?)",
                (path.id, app, task, sig, _steps_to_json(steps), path.app_version, now),
            )
        conn.execute("INSERT INTO verifications VALUES (?, ?)", (path.id, now))
        return path

    def _find(self, conn: sqlite3.Connection, app: str, task: str) -> TaskPath | None:
        rows = self._rows(conn, app)
        scored = [(task_similarity(r.path.task, task, app), r) for r in rows]
        scored = [(score, r) for score, r in scored if score >= MATCH_THRESHOLD]
        if not scored:
            return None
        best_match = max(score for score, _ in scored)
        pool = [r for score, r in scored if score >= best_match - _MATCH_MARGIN]

        def effective(r: _Row) -> tuple[float, bool, datetime]:
            local = r.path.source == PathSource.LOCAL
            return (r.strength * (LOCAL_PREFERENCE if local else 1.0), local, r.path.updated_at)

        winner = max(pool, key=effective)
        if winner.path.source == PathSource.LOCAL:
            twin = next(
                (
                    r
                    for r in pool
                    if r.path.source == PathSource.SHARED and r.signature == winner.signature
                ),
                None,
            )
            if twin is not None:
                return _with_difficulty(winner.path, twin.path)
        return winner.path

    def _merge(self, conn: sqlite3.Connection, shared: tuple[TaskPath, ...]) -> int:
        changed = 0
        now = _ts(self._clock())
        try:
            for incoming in shared:
                app, task = incoming.app.strip(), task_key(incoming.task)
                if not app or not task or not incoming.steps:
                    continue
                steps = tuple(
                    replace(
                        s,
                        index=n,
                        element=None if s.element is None else replace(s.element, window_title=""),
                    )
                    for n, s in enumerate(incoming.steps, start=1)
                )
                sig, steps_json = signature(steps), _steps_to_json(steps)
                existing = conn.execute(
                    "SELECT id, steps, verified_count, app_version FROM paths "
                    "WHERE source = 'shared' AND app = ? AND task = ? AND signature = ?",
                    (app, task, sig),
                ).fetchone()
                values = (steps_json, incoming.verified_count, incoming.app_version)
                if existing is None:
                    conn.execute(
                        "INSERT INTO paths VALUES (?, ?, ?, 'shared', ?, ?, ?, ?, ?)",
                        (incoming.id, app, task, sig, *values, now),
                    )
                elif tuple(existing)[1:] != values:
                    conn.execute(
                        "UPDATE paths SET steps = ?, verified_count = ?, app_version = ?, "
                        "updated_at = ? WHERE id = ?",
                        (*values, now, existing["id"]),
                    )
                else:
                    continue
                changed += 1
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return changed

    def _refresh_difficulty(self, conn: sqlite3.Connection) -> None:
        stats: dict[tuple[str, str], dict[int, tuple[int, int]]] = {}
        for row in conn.execute("SELECT app, task, step_index, attempts, stuck FROM step_stats"):
            stats.setdefault((row["app"], row["task"]), {})[row["step_index"]] = (
                row["attempts"],
                row["stuck"],
            )
        self.local_difficulty.update(stats)


def _with_difficulty(local: TaskPath, shared: TaskPath) -> TaskPath:
    """Copy crowd difficulty onto a local path whose element sequence is identical."""
    return replace(
        local,
        steps=tuple(
            s if s.difficulty is not None else replace(s, difficulty=t.difficulty)
            for s, t in zip(local.steps, shared.steps, strict=True)
        ),
    )
