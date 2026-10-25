"""Per-user concept mastery with Bayesian knowledge tracing. Never leaves the device.

Updates after every walkthrough with no per-record approval; instead every skill
and the evidence behind it is stored, visible in the skills window, and
resettable. All SQLite work runs in ``asyncio.to_thread`` with a short-lived
connection per call, so the Qt event loop never blocks on disk.

Mastery is a probability the user knows a concept. Each step's outcome is
evidence, weighted by how much help the step got (watching isn't doing) and,
when the crowd knows it, how hard the step is. Mastery decays toward the prior
with a half-life when read, and an unseen concept borrows from related known
ones through the ``ConceptGraph``.
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from platformdirs import user_data_path

from curio.learning_contract import (
    AssistanceLevel,
    DifficultyProvider,
    SkillState,
    StepOutcome,
    WalkthroughSummary,
)
from curio.skills.concepts import ConceptGraph

Clock = Callable[[], datetime]
Listener = Callable[[], None]

_SCHEMA_VERSION = 1
_SECONDS_PER_DAY = 86_400.0


def default_path() -> Path:
    return user_data_path("Curio") / "skills.sqlite3"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class BktParams:
    """Every tunable number in one place."""

    p_init: float = 0.2
    p_learn: float = 0.15
    # Learning after a failed step. Lower than p_learn, or mastery could never
    # fall below p_learn and the DID_IT band would be unreachable.
    p_learn_after_failure: float = 0.05
    p_slip: float = 0.1
    p_guess: float = 0.2
    half_life_days: float = 14.0
    assistance_weights: Mapping[AssistanceLevel, float] = field(
        default_factory=lambda: MappingProxyType(
            {
                AssistanceLevel.NONE: 1.0,
                AssistanceLevel.HINTED: 0.7,
                AssistanceLevel.POINTED: 0.35,
                AssistanceLevel.DID_IT: 0.0,
            }
        )
    )
    # 0 ignores crowd difficulty; 0.5 makes a success on the hardest step count
    # 1.5x and on the easiest 0.5x (and the reverse for failures).
    difficulty_strength: float = 0.5
    # Mastery carried into an app where the concept hasn't been practiced yet.
    cross_app_transfer: float = 0.75
    # Advice bands: below each threshold, give that much help.
    did_it_below: float = 0.15
    pointed_below: float = 0.45
    hinted_below: float = 0.8
    # prompt_context calls a concept "known well" from this mastery up.
    known_well: float = 0.6


DEFAULT_PARAMS = BktParams()


def assistance_for(mastery: float, params: BktParams = DEFAULT_PARAMS) -> AssistanceLevel:
    if mastery < params.did_it_below:
        return AssistanceLevel.DID_IT
    if mastery < params.pointed_below:
        return AssistanceLevel.POINTED
    if mastery < params.hinted_below:
        return AssistanceLevel.HINTED
    return AssistanceLevel.NONE


def bkt_update(
    mastery: float, correct: bool, weight: float, params: BktParams = DEFAULT_PARAMS
) -> float:
    """One weighted BKT step.

    The observation's likelihoods are tempered by ``weight`` (a power
    posterior): weight 0 is no evidence, 1 is a normal observation and above 1
    counts extra. The learning transition scales with ``min(weight, 1)``.
    """
    if weight <= 0:
        return mastery
    p = min(max(mastery, 1e-6), 1 - 1e-6)
    if correct:
        known, unknown = 1 - params.p_slip, params.p_guess
    else:
        known, unknown = params.p_slip, 1 - params.p_guess
    known, unknown = known**weight, unknown**weight
    posterior = p * known / (p * known + (1 - p) * unknown)
    p_learn = params.p_learn if correct else params.p_learn_after_failure
    learned = posterior + (1 - posterior) * p_learn * min(weight, 1.0)
    return min(max(learned, 0.0), 1.0)


def decayed(
    mastery: float,
    last_practiced: datetime | None,
    now: datetime,
    params: BktParams = DEFAULT_PARAMS,
) -> float:
    """Mastery pulled back toward the prior by time since last practice."""
    if last_practiced is None or params.half_life_days <= 0:
        return mastery
    days = max(0.0, (now - last_practiced).total_seconds() / _SECONDS_PER_DAY)
    keep = math.pow(0.5, days / params.half_life_days)
    return params.p_init + (mastery - params.p_init) * keep


def difficulty_factor(
    difficulty: float | None, correct: bool, params: BktParams = DEFAULT_PARAMS
) -> float:
    if difficulty is None or not math.isfinite(difficulty):
        return 1.0
    d = min(max(difficulty, 0.0), 1.0)
    tilt = 2 * params.difficulty_strength * (d - 0.5)
    return max(0.0, 1 + tilt if correct else 1 - tilt)


@dataclass(frozen=True, kw_only=True)
class SkillEvidence:
    """One step's effect on one concept: the "why?" behind a mastery number."""

    event_id: str
    concept: str
    app: str
    task: str
    walkthrough_id: str
    step_index: int
    instruction: str
    outcome: StepOutcome
    assistance: AssistanceLevel
    difficulty: float | None
    weight: float
    mastery_before: float
    mastery_after: float
    recorded_at: datetime


@dataclass(frozen=True, kw_only=True)
class _Row:
    concept: str
    mastery: float
    attempts: int
    last_practiced: datetime | None
    apps: tuple[str, ...]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS skills (
    concept TEXT PRIMARY KEY,
    mastery REAL NOT NULL,
    attempts INTEGER NOT NULL,
    last_practiced TEXT,
    apps TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    event_id TEXT NOT NULL,
    concept TEXT NOT NULL,
    app TEXT NOT NULL,
    task TEXT NOT NULL,
    walkthrough_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    instruction TEXT NOT NULL,
    outcome TEXT NOT NULL,
    assistance TEXT NOT NULL,
    difficulty REAL,
    weight REAL NOT NULL,
    mastery_before REAL NOT NULL,
    mastery_after REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    seq INTEGER NOT NULL,
    PRIMARY KEY (event_id, concept)
);
CREATE INDEX IF NOT EXISTS evidence_concept ON evidence (concept, seq);
"""


def _ts(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="microseconds") if value else None


def _parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row(raw: sqlite3.Row) -> _Row:
    return _Row(
        concept=raw["concept"],
        mastery=raw["mastery"],
        attempts=raw["attempts"],
        last_practiced=_parse_ts(raw["last_practiced"]),
        apps=tuple(json.loads(raw["apps"])),
    )


def _evidence(raw: sqlite3.Row) -> SkillEvidence:
    return SkillEvidence(
        event_id=raw["event_id"],
        concept=raw["concept"],
        app=raw["app"],
        task=raw["task"],
        walkthrough_id=raw["walkthrough_id"],
        step_index=raw["step_index"],
        instruction=raw["instruction"],
        outcome=StepOutcome(raw["outcome"]),
        assistance=AssistanceLevel(raw["assistance"]),
        difficulty=raw["difficulty"],
        weight=raw["weight"],
        mastery_before=raw["mastery_before"],
        mastery_after=raw["mastery_after"],
        recorded_at=datetime.fromisoformat(raw["recorded_at"]),
    )


@dataclass(frozen=True, kw_only=True)
class _Observation:
    event_id: str
    app: str
    task: str
    walkthrough_id: str
    step_index: int
    instruction: str
    outcome: StepOutcome
    assistance: AssistanceLevel
    difficulty: float | None
    concepts: tuple[str, ...]


class SqliteSkillModel:
    """``SkillModel`` backed by one local SQLite file.

    Observing the same step twice is a no-op (evidence is keyed by step event
    id and concept). Listeners registered with ``subscribe`` are called on the
    caller's thread after each change, so the skills window can refresh.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        graph: ConceptGraph,
        difficulty: DifficultyProvider | None = None,
        clock: Clock = _utc_now,
        params: BktParams = DEFAULT_PARAMS,
    ) -> None:
        self._path = path if path is not None else default_path()
        self._graph = graph
        self._difficulty = difficulty
        self._clock = clock
        self._params = params
        self._write_lock = asyncio.Lock()
        self._ready = False
        self._listeners: list[Listener] = []

    @property
    def graph(self) -> ConceptGraph:
        return self._graph

    @property
    def params(self) -> BktParams:
        return self._params

    @property
    def path(self) -> Path:
        return self._path

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    # --- SQLite (worker thread only) -----------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        if not self._ready:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            conn.commit()
            self._ready = True
        return conn

    def _load_rows(self, conn: sqlite3.Connection) -> dict[str, _Row]:
        return {r.concept: r for r in map(_row, conn.execute("SELECT * FROM skills"))}

    def _read_rows(self) -> dict[str, _Row]:
        with closing(self._connect()) as conn:
            return self._load_rows(conn)

    def _apply(self, observations: Sequence[_Observation], now: datetime) -> int:
        p = self._params
        changed = 0
        with closing(self._connect()) as conn, conn:
            rows = self._load_rows(conn)
            seq = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM evidence").fetchone()[0]
            for obs in observations:
                correct = obs.outcome == StepOutcome.SUCCEEDED
                weight = p.assistance_weights.get(obs.assistance, 0.0) * difficulty_factor(
                    obs.difficulty, correct, p
                )
                if weight <= 0:
                    continue
                for concept in obs.concepts:
                    exists = conn.execute(
                        "SELECT 1 FROM evidence WHERE event_id = ? AND concept = ?",
                        (obs.event_id, concept),
                    ).fetchone()
                    if exists:
                        continue
                    row = rows.get(concept)
                    if row is None:
                        before = self._transfer_prior(concept, rows, now)
                        row = _Row(
                            concept=concept, mastery=before, attempts=0,
                            last_practiced=None, apps=(),
                        )
                    else:
                        before = decayed(row.mastery, row.last_practiced, now, p)
                    after = bkt_update(before, correct, weight, p)
                    apps = row.apps if obs.app in row.apps else (*row.apps, obs.app)
                    row = replace(
                        row, mastery=after, attempts=row.attempts + 1,
                        last_practiced=now, apps=apps,
                    )
                    rows[concept] = row
                    seq += 1
                    conn.execute(
                        "INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            obs.event_id, concept, obs.app, obs.task, obs.walkthrough_id,
                            obs.step_index, obs.instruction, obs.outcome.value,
                            obs.assistance.value, obs.difficulty, weight, before, after,
                            _ts(now), seq,
                        ),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO skills VALUES (?,?,?,?,?)",
                        (concept, row.mastery, row.attempts, _ts(now), json.dumps(row.apps)),
                    )
                    changed += 1
        return changed

    # --- mastery maths (pure) ------------------------------------------------

    def _transfer_prior(self, concept: str, rows: Mapping[str, _Row], now: datetime) -> float:
        """Starting mastery for an unseen concept, borrowed from related known ones."""
        p = self._params
        borrowed = 0.0
        for neighbour, weight in self._graph.related(concept).items():
            row = rows.get(neighbour)
            if row is None:
                continue
            m = decayed(row.mastery, row.last_practiced, now, p)
            borrowed = max(borrowed, weight * (m - p.p_init))
        return p.p_init + borrowed

    def _effective(
        self, concept: str, app: str, rows: Mapping[str, _Row], now: datetime
    ) -> float:
        p = self._params
        row = rows.get(concept)
        if row is None:
            return self._transfer_prior(concept, rows, now)
        m = decayed(row.mastery, row.last_practiced, now, p)
        if row.apps and app not in row.apps:
            m = p.p_init + p.cross_app_transfer * (m - p.p_init)
        return m

    # --- SkillModel ------------------------------------------------------------

    async def observe(self, summary: WalkthroughSummary) -> None:
        app = self._graph.app(summary.app)
        observations: list[_Observation] = []
        for step in summary.steps:
            if step.outcome == StepOutcome.ABANDONED:
                continue
            concepts = self._graph.canonical_all(app, step.concepts)
            if not concepts:
                continue
            observations.append(
                _Observation(
                    event_id=step.id, app=app, task=summary.task,
                    walkthrough_id=summary.walkthrough_id, step_index=step.step_index,
                    instruction=step.instruction, outcome=StepOutcome(step.outcome),
                    assistance=AssistanceLevel(step.assistance),
                    difficulty=self._step_difficulty(summary.app, summary.task, step.step_index),
                    concepts=concepts,
                )
            )
        if not observations:
            return
        async with self._write_lock:
            changed = await asyncio.to_thread(self._apply, observations, self._clock())
        if changed:
            self._notify()

    def _step_difficulty(self, app: str, task: str, step_index: int) -> float | None:
        if self._difficulty is None:
            return None
        try:
            value = self._difficulty.step_difficulty(app, task, step_index)
        except Exception:
            return None  # crowd data is optional; never fail an observation over it
        return None if value is None else float(value)

    async def snapshot(self) -> tuple[SkillState, ...]:
        rows = await asyncio.to_thread(self._read_rows)
        now = self._clock()
        states = (
            SkillState(
                concept=r.concept,
                mastery=decayed(r.mastery, r.last_practiced, now, self._params),
                attempts=r.attempts,
                last_practiced=r.last_practiced,
                apps=r.apps,
            )
            for r in rows.values()
        )
        return tuple(sorted(states, key=lambda s: (-s.mastery, s.concept)))

    async def mastery(self, app: str, concepts: Sequence[str]) -> dict[str, float]:
        """Effective mastery per canonical concept for use in ``app``."""
        app = self._graph.app(app)
        keys = self._graph.canonical_all(app, concepts)
        rows = await asyncio.to_thread(self._read_rows)
        now = self._clock()
        return {k: self._effective(k, app, rows, now) for k in keys}

    async def recommend_assistance(self, app: str, concepts: Sequence[str]) -> AssistanceLevel:
        values = await self.mastery(app, concepts)
        weakest = min(values.values(), default=self._params.p_init)
        return assistance_for(weakest, self._params)

    async def prompt_context(self, app: str, concepts: Sequence[str]) -> str | None:
        app = self._graph.app(app)
        keys = self._graph.canonical_all(app, concepts)
        if not keys:
            return None
        rows = await asyncio.to_thread(self._read_rows)
        now = self._clock()
        p = self._params
        g = self._graph
        sentences: list[str] = []
        comfortable: list[str] = []
        learning: list[str] = []
        for key in keys:
            row = rows.get(key)
            here = g.name_in(key, app)
            if row is not None and row.apps and app not in row.apps:
                m = decayed(row.mastery, row.last_practiced, now, p)
                if m >= p.known_well:
                    source = row.apps[-1]
                    there = g.name_in(key, source)
                    if there != here:
                        sentences.append(
                            f"The user knows {there} well from {source}; "
                            f"in {app} the same idea is {here}."
                        )
                    else:
                        sentences.append(
                            f"The user knows {there} well from {source}, "
                            f"and it works much the same in {app}."
                        )
                continue
            if row is None:
                best = self._best_neighbour(key, rows, now)
                if best is not None:
                    neighbour = rows[best]
                    sentences.append(
                        f"The user knows {g.name_in(best, neighbour.apps[-1])} well, "
                        f"which is closely related to {here}."
                    )
                continue
            m = self._effective(key, app, rows, now)
            if m >= p.hinted_below:
                comfortable.append(here)
            elif m < p.pointed_below:
                learning.append(here)
        if comfortable:
            sentences.append(
                f"The user is already comfortable with {_join(comfortable)} in {app}; "
                "keep it brief."
            )
        if learning:
            sentences.append(
                f"The user is still learning {_join(learning)} in {app}; explain each step."
            )
        return " ".join(sentences[:2]) or None

    def _best_neighbour(
        self, concept: str, rows: Mapping[str, _Row], now: datetime
    ) -> str | None:
        p = self._params
        best: tuple[float, str] | None = None
        for neighbour, weight in self._graph.related(concept).items():
            row = rows.get(neighbour)
            if row is None or not row.apps:
                continue
            m = decayed(row.mastery, row.last_practiced, now, p)
            if m < p.known_well:
                continue
            score = weight * (m - p.p_init)
            if best is None or score > best[0]:
                best = (score, neighbour)
        return best[1] if best else None

    async def reset(self) -> None:
        def work() -> None:
            with closing(self._connect()) as conn, conn:
                conn.execute("DELETE FROM evidence")
                conn.execute("DELETE FROM skills")

        async with self._write_lock:
            await asyncio.to_thread(work)
        self._notify()

    # --- transparency ----------------------------------------------------------

    async def reset_concept(self, concept: str) -> bool:
        """Forget one concept and its evidence. Returns whether anything was stored."""

        def work() -> bool:
            with closing(self._connect()) as conn, conn:
                conn.execute("DELETE FROM evidence WHERE concept = ?", (concept,))
                return conn.execute(
                    "DELETE FROM skills WHERE concept = ?", (concept,)
                ).rowcount > 0

        async with self._write_lock:
            removed = await asyncio.to_thread(work)
        self._notify()
        return removed

    async def evidence(self, concept: str, limit: int = 200) -> tuple[SkillEvidence, ...]:
        """Newest first."""

        def work() -> tuple[SkillEvidence, ...]:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT * FROM evidence WHERE concept = ? ORDER BY seq DESC LIMIT ?",
                    (concept, limit),
                )
                return tuple(map(_evidence, rows))

        return await asyncio.to_thread(work)

    async def export_data(self) -> dict[str, Any]:
        """Everything the model stores, as JSON-ready data."""

        def work() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            with closing(self._connect()) as conn:
                skills = [dict(r) for r in conn.execute("SELECT * FROM skills ORDER BY concept")]
                evidence = [dict(r) for r in conn.execute("SELECT * FROM evidence ORDER BY seq")]
            for skill in skills:
                skill["apps"] = json.loads(skill["apps"])
            for item in evidence:
                item.pop("seq", None)
            return skills, evidence

        skills, evidence = await asyncio.to_thread(work)
        now = self._clock()
        for skill in skills:
            skill["mastery_now"] = decayed(
                skill["mastery"], _parse_ts(skill["last_practiced"]), now, self._params
            )
        params = {
            k: v for k, v in vars(self._params).items() if k != "assistance_weights"
        }
        params["assistance_weights"] = {
            k.value: v for k, v in self._params.assistance_weights.items()
        }
        return {
            "format": "curio-skills",
            "version": _SCHEMA_VERSION,
            "exported_at": _ts(now),
            "params": params,
            "skills": skills,
            "evidence": evidence,
        }


def _join(items: Sequence[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"
