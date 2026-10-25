"""Spaced review: an SM-2-style schedule stored locally in SQLite, with
interleaving of easily confused concepts (research doc, section G).

All SQLite work runs on one dedicated worker thread, never on the Qt event
loop. Review items never leave the device.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from platformdirs import user_data_path

from curio.focus_contract import ReviewItem
from curio.learning_contract import concept_key

_SCHEMA_VERSION = 1
_COLUMNS = "id, concept, question, answer, due_at, interval_days, repetitions, lapses, ease"

DEFAULT_EASE = 2.5
MIN_EASE = 1.3
MAX_EASE = 3.0
FIRST_INTERVAL_DAYS = 1.0
SECOND_INTERVAL_DAYS = 3.0
LAPSE_INTERVAL_DAYS = 1.0  # a wrong answer comes back at the next day's session
MAX_INTERVAL_DAYS = 365.0

# Easily confused concept pairs (concept_key form). Interleaving helps most
# when the mixed categories are similar (Brunmair & Richter 2019).
CONFUSABLE_PAIRS: frozenset[frozenset[str]] = frozenset(
    frozenset(pair)
    for pair in (
        ("vlookup", "index match"),
        ("vlookup", "xlookup"),
        ("xlookup", "index match"),
        ("vlookup", "hlookup"),
        ("absolute reference", "relative reference"),
        ("absolute reference", "mixed reference"),
        ("sumif", "countif"),
        ("sumif", "sumifs"),
        ("pivot table", "pivot chart"),
        ("filter", "sort"),
        ("layer", "mask"),
        ("layer mask", "clipping mask"),
        ("frame", "group"),
        ("component", "instance"),
        ("margin", "padding"),
    )
)
_STOP_WORDS = frozenset({"a", "an", "and", "the", "of", "to", "in", "on", "for", "with", "how"})


class ReviewScheduler(Protocol):
    async def due_reviews(self, now: datetime, limit: int = 3) -> tuple[ReviewItem, ...]: ...

    async def record_review(self, item: ReviewItem, correct: bool) -> ReviewItem: ...

    async def add_review_items(self, items: Sequence[ReviewItem]) -> None: ...


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _normalise(concept: str) -> str:
    return " ".join(_singular(w) for w in concept_key(concept).split())


def similar(a: str, b: str) -> bool:
    """True for a bundled confusable pair or concepts that share a content word."""
    a, b = _normalise(a), _normalise(b)
    if not a or not b or a == b:
        return False
    if frozenset((a, b)) in CONFUSABLE_PAIRS:
        return True
    return bool((set(a.split()) & set(b.split())) - _STOP_WORDS)


def interleave(items: Sequence[ReviewItem]) -> list[ReviewItem]:
    """Reorder so consecutive items differ in concept, preferring a confusable neighbour.

    Input order is the priority order (most overdue first) and breaks ties.
    """
    remaining = list(items)
    ordered: list[ReviewItem] = []
    while remaining:
        if not ordered:
            ordered.append(remaining.pop(0))
            continue
        previous = _normalise(ordered[-1].concept)
        different = [i for i, item in enumerate(remaining) if _normalise(item.concept) != previous]
        if not different:
            ordered.append(remaining.pop(0))
            continue
        close = [i for i in different if similar(previous, remaining[i].concept)]
        ordered.append(remaining.pop(close[0] if close else different[0]))
    return ordered


def next_schedule(
    item: ReviewItem, correct: bool, ease: float, now: datetime
) -> tuple[ReviewItem, float]:
    """SM-2-style update: correct grows the interval by ease, wrong resets it."""
    if correct:
        repetitions = item.repetitions + 1
        if repetitions == 1:
            interval = FIRST_INTERVAL_DAYS
        elif repetitions == 2:
            interval = SECOND_INTERVAL_DAYS
        else:
            interval = item.interval_days * ease
        ease = min(MAX_EASE, ease + 0.1)
        lapses = item.lapses
    else:
        repetitions = 0
        interval = LAPSE_INTERVAL_DAYS
        ease = max(MIN_EASE, ease - 0.2)
        lapses = item.lapses + 1
    interval = min(MAX_INTERVAL_DAYS, interval)
    updated = replace(
        item,
        repetitions=repetitions,
        interval_days=interval,
        lapses=lapses,
        due_at=now + timedelta(days=interval),
    )
    return updated, ease


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Review timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _item(row: sqlite3.Row) -> ReviewItem:
    return ReviewItem(
        id=row["id"],
        concept=row["concept"],
        question=row["question"],
        answer=row["answer"],
        due_at=datetime.fromisoformat(row["due_at"]),
        interval_days=row["interval_days"],
        repetitions=row["repetitions"],
        lapses=row["lapses"],
    )


class SqliteReviewScheduler:
    """Local review store. ``path=":memory:"`` keeps items for this process only.

    Duplicate questions on the same concept (case and spacing ignored) are
    skipped, so repeated sessions don't pile up copies.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._memory = path == ":memory:"
        self._path = (
            Path(path)
            if path is not None and not self._memory
            else user_data_path("Curio") / "study_reviews.sqlite3"
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="curio-reviews")
        self._conn: sqlite3.Connection | None = None
        self._closed = False

    async def __aenter__(self) -> SqliteReviewScheduler:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            future = asyncio.get_running_loop().run_in_executor(self._executor, self._close)
            self._executor.shutdown(wait=False)
            await asyncio.shield(future)

    # --- StudyCoach review methods -----------------------------------------------

    async def due_reviews(self, now: datetime, limit: int = 3) -> tuple[ReviewItem, ...]:
        if limit <= 0:
            return ()
        pool = await self._run(self._due, _iso(now), limit * 4)
        return tuple(interleave(pool)[:limit])

    async def record_review(self, item: ReviewItem, correct: bool) -> ReviewItem:
        return await self._run(self._record, item, bool(correct), self._clock())

    async def add_review_items(self, items: Sequence[ReviewItem]) -> None:
        clean = [i for i in items if i.question.strip() and i.answer.strip() and i.concept.strip()]
        if clean:
            await self._run(self._add, clean)

    # --- Management (visible and deletable, per the privacy section) -------------

    async def items(self) -> tuple[ReviewItem, ...]:
        return await self._run(self._all)

    async def delete(self, item_id: str) -> None:
        await self._run(self._delete, item_id)

    async def clear(self) -> None:
        await self._run(self._clear)

    # --- Worker-thread SQLite --------------------------------------------------------

    async def _run(self, operation, *args):
        if self._closed:
            raise RuntimeError("Review scheduler is closed")
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, lambda: operation(self._connection(), *args)
        )

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if not self._memory:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(":memory:" if self._memory else str(self._path), timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA secure_delete = ON")
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > _SCHEMA_VERSION:
                raise OSError("Unsupported review database schema version")
            if version == 0:
                conn.execute("""CREATE TABLE reviews (
                    id TEXT PRIMARY KEY NOT NULL,
                    concept TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    interval_days REAL NOT NULL,
                    repetitions INTEGER NOT NULL,
                    lapses INTEGER NOT NULL,
                    ease REAL NOT NULL,
                    normalized_question TEXT NOT NULL
                )""")
                conn.execute(
                    "CREATE UNIQUE INDEX review_dedup ON reviews (concept, normalized_question)"
                )
                conn.execute("CREATE INDEX review_due ON reviews (due_at)")
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            conn.commit()
        except BaseException:
            conn.rollback()
            conn.close()
            raise
        self._conn = conn
        return conn

    @staticmethod
    def _due(conn: sqlite3.Connection, now: str, pool: int) -> list[ReviewItem]:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM reviews WHERE due_at <= ? ORDER BY due_at, id LIMIT ?",
            (now, pool),
        ).fetchall()
        return [_item(row) for row in rows]

    @staticmethod
    def _record(
        conn: sqlite3.Connection, item: ReviewItem, correct: bool, now: datetime
    ) -> ReviewItem:
        row = conn.execute(f"SELECT {_COLUMNS} FROM reviews WHERE id = ?", (item.id,)).fetchone()
        ease = row["ease"] if row is not None else DEFAULT_EASE
        current = _item(row) if row is not None else item
        updated, ease = next_schedule(current, correct, ease, now)
        with conn:
            conn.execute(
                "INSERT INTO reviews (id, concept, question, answer, due_at, interval_days, "
                "repetitions, lapses, ease, normalized_question) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET due_at = excluded.due_at, "
                "interval_days = excluded.interval_days, repetitions = excluded.repetitions, "
                "lapses = excluded.lapses, ease = excluded.ease",
                (*_values(updated), ease, _normalised_question(updated.question)),
            )
        return updated

    @staticmethod
    def _add(conn: sqlite3.Connection, items: list[ReviewItem]) -> None:
        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO reviews (id, concept, question, answer, due_at, "
                "interval_days, repetitions, lapses, ease, normalized_question) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(*_values(i), DEFAULT_EASE, _normalised_question(i.question)) for i in items],
            )

    @staticmethod
    def _all(conn: sqlite3.Connection) -> tuple[ReviewItem, ...]:
        rows = conn.execute(f"SELECT {_COLUMNS} FROM reviews ORDER BY due_at, id").fetchall()
        return tuple(_item(row) for row in rows)

    @staticmethod
    def _delete(conn: sqlite3.Connection, item_id: str) -> None:
        with conn:
            conn.execute("DELETE FROM reviews WHERE id = ?", (item_id,))

    @staticmethod
    def _clear(conn: sqlite3.Connection) -> None:
        with conn:
            conn.execute("DELETE FROM reviews")


def _values(item: ReviewItem) -> tuple:
    return (
        item.id,
        concept_key(item.concept),
        item.question.strip(),
        item.answer.strip(),
        _iso(item.due_at),
        float(item.interval_days),
        int(item.repetitions),
        int(item.lapses),
    )


def _normalised_question(question: str) -> str:
    return " ".join(question.split()).casefold()
