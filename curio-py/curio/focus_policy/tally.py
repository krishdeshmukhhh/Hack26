"""Accumulates a session's timeline for the end-of-session summary (section F)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from curio.focus_contract import (
    FocusPlan,
    FocusSignal,
    Intervention,
    InterventionKind,
    InterventionResponse,
    SessionSummary,
    SignalKind,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _State(StrEnum):
    ON_GOAL = "on_goal"
    OFF_GOAL = "off_goal"
    BREAK = "break"


class SessionTally:
    """Feed it every signal, shown intervention and response; ask for a summary at the end.

    Off-goal time starts when the drift began (the signal's ``at`` minus its
    ``drift_seconds``), not when the threshold was crossed. A "not a
    distraction" response moves that drift's time back to on-goal and removes
    it from the drift count, so the timeline matches what the learner says.
    """

    def __init__(self, plan: FocusPlan, *, clock: Clock = _utc_now) -> None:
        self._plan = plan
        self._clock = clock
        self._started_at = clock()
        self._mark = self._started_at
        self._state = _State.ON_GOAL
        self._seconds = dict.fromkeys(_State, 0.0)
        self._drift_count = 0
        self._false_alarms = 0
        self._interventions = 0
        self._concepts: list[str] = []
        self._episode_start: datetime | None = None
        self._last_episode_seconds = 0.0  # a finished drift a false alarm can still undo

    def observe(self, signal: FocusSignal) -> None:
        at = max(signal.at, self._mark)
        if signal.kind is SignalKind.DRIFT_STARTED and self._state is _State.ON_GOAL:
            began = max(self._mark, at - timedelta(seconds=signal.drift_seconds))
            self._advance(began)
            self._state = _State.OFF_GOAL
            self._episode_start = began
            self._last_episode_seconds = 0.0
            self._drift_count += 1
        elif signal.kind is SignalKind.RETURNED and self._state is _State.OFF_GOAL:
            self._end_episode(at)
            self._state = _State.ON_GOAL
        elif signal.kind is SignalKind.BREAK_OVER and self._state is _State.BREAK:
            self._advance(at)
            self._state = _State.ON_GOAL

    def start_break(self, at: datetime | None = None) -> None:
        moment = max(at or self._clock(), self._mark)
        if self._state is _State.OFF_GOAL:
            self._end_episode(moment)
        self._advance(moment)
        self._state = _State.BREAK

    def record_intervention(self, intervention: Intervention) -> None:
        self._interventions += 1

    def record_response(self, intervention: Intervention, response: InterventionResponse) -> None:
        if response is InterventionResponse.FALSE_ALARM:
            self._false_alarms += 1
            self._undo_drift()
        elif (
            intervention.kind is InterventionKind.BREAK_START
            and response is InterventionResponse.ACCEPTED
        ):
            self.start_break()

    def add_concepts(self, concepts: Iterable[str]) -> None:
        for concept in concepts:
            if concept not in self._concepts:
                self._concepts.append(concept)

    def summary(self, *, reflection: str = "") -> SessionSummary:
        ended_at = max(self._clock(), self._mark)
        self._advance(ended_at)
        return SessionSummary(
            plan_id=self._plan.id,
            goal=self._plan.goal,
            started_at=self._started_at,
            ended_at=ended_at,
            on_goal_seconds=self._seconds[_State.ON_GOAL],
            off_goal_seconds=self._seconds[_State.OFF_GOAL],
            break_seconds=self._seconds[_State.BREAK],
            drift_count=self._drift_count,
            interventions=self._interventions,
            false_alarms=self._false_alarms,
            concepts_practised=tuple(self._concepts),
            reflection=reflection,
        )

    def _advance(self, to: datetime) -> None:
        if to > self._mark:
            self._seconds[self._state] += (to - self._mark).total_seconds()
            self._mark = to

    def _end_episode(self, at: datetime) -> None:
        self._advance(at)
        if self._episode_start is not None:
            self._last_episode_seconds = (at - self._episode_start).total_seconds()
        self._episode_start = None

    def _undo_drift(self) -> None:
        if self._state is _State.OFF_GOAL:
            self._end_episode(max(self._clock(), self._mark))
            self._state = _State.ON_GOAL
        moved = min(self._last_episode_seconds, self._seconds[_State.OFF_GOAL])
        if moved <= 0:
            return
        self._seconds[_State.OFF_GOAL] -= moved
        self._seconds[_State.ON_GOAL] += moved
        self._last_episode_seconds = 0.0
        self._drift_count = max(0, self._drift_count - 1)
