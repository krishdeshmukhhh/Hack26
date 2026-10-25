"""Turns per-sample track assessments into FocusSignals (sections B, C, E).

Time comes only from ``sample.at``, so a scripted list of samples gives the
same signals every run. The interval between two samples counts under the
earlier sample's judgment, the one that held during it (capped at
``max_sample_gap_seconds``, so a laptop waking from sleep doesn't count hours
of drift).

Signals from one ``update`` come in this order: BREAK_DUE / BREAK_OVER,
SESSION_ENDING, IDLE, drift (DRIFT_STARTED / DRIFT_CONTINUING / RETURNED), then
BREAKPOINTs (IDLE_RESUME, APP_SWITCH, TYPING_PAUSE). A policy can therefore see
that the learner is drifting before it sees that they're receptive.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from curio.focus_contract import (
    ActivitySample,
    BreakpointKind,
    FocusPlan,
    FocusSignal,
    SignalKind,
    TrackAssessment,
    TrackJudgment,
)
from curio.focus_sensing.cycle import break_phase


@dataclass(frozen=True, kw_only=True)
class DriftThresholds:
    # Drift (section B): sustained off-goal time, not single switches.
    drift_after_seconds: float = 90.0
    unsure_weight: float = 0.5  # UNSURE time counts at half weight
    min_off_confidence: float = 0.5  # weaker OFF_GOAL judgments count as UNSURE
    repeat_visits: int = 3  # this many visits to one off-goal app...
    repeat_window_seconds: float = 180.0  # ...within this window is a drift too
    return_grace_seconds: float = 15.0  # on-goal time needed to end a drift (hysteresis)
    continuing_every_seconds: float = 120.0
    # Idle: input pauses this long stop drift accumulating; IDLE fires later.
    idle_pause_seconds: float = 60.0
    idle_after_seconds: float = 180.0
    # Breakpoints (section C).
    idle_resume_after_seconds: float = 60.0
    busy_events_per_sample: int = 2
    busy_stretch_seconds: float = 20.0
    typing_pause_seconds: float = 4.0
    # Session (sections E, F).
    session_ending_seconds: float = 120.0
    max_sample_gap_seconds: float = 10.0


@dataclass(frozen=True, kw_only=True)
class DriftTotals:
    """Running time split for the session timeline (section F)."""

    on_goal_seconds: float = 0.0
    off_goal_seconds: float = 0.0
    unsure_seconds: float = 0.0
    break_seconds: float = 0.0
    idle_seconds: float = 0.0
    drift_count: int = 0
    drift_seconds: float = 0.0  # summed length of finished drifts


@dataclass
class _State:
    previous: ActivitySample | None = None
    previous_assessment: TrackAssessment | None = None
    on_break: bool | None = None
    ending_sent: bool = False
    idle_sent: bool = False
    off_score: float = 0.0
    episode_start: datetime | None = None
    on_since: datetime | None = None
    on_streak: float = 0.0
    drifting: bool = False
    last_continuing: datetime | None = None
    visits: dict[str, deque[datetime]] = field(default_factory=dict)
    busy_seconds: float = 0.0
    totals: DriftTotals = field(default_factory=DriftTotals)


class ThresholdDriftTracker:
    """DriftTracker with fixed thresholds and on-goal hysteresis."""

    def __init__(
        self, thresholds: DriftThresholds | None = None, plan: FocusPlan | None = None
    ) -> None:
        self.thresholds = thresholds or DriftThresholds()
        self._plan = plan
        self._s = _State()

    @property
    def plan(self) -> FocusPlan | None:
        return self._plan

    @property
    def drifting(self) -> bool:
        return self._s.drifting

    @property
    def totals(self) -> DriftTotals:
        return self._s.totals

    def reset(self, plan: FocusPlan) -> None:
        self._plan = plan
        self._s = _State()

    def update(self, sample: ActivitySample, assessment: TrackAssessment) -> Sequence[FocusSignal]:
        t, s = self.thresholds, self._s
        now = sample.at
        previous = s.previous
        dt = 0.0
        if previous is not None:
            dt = min(max((now - previous.at).total_seconds(), 0.0), t.max_sample_gap_seconds)
        signals: list[FocusSignal] = []

        def signal(kind: SignalKind, **extra) -> None:
            signals.append(FocusSignal(kind=kind, sample=sample, at=now, **extra))

        # Fixed study/break cycle and the end of the session.
        if self._plan is not None:
            phase = break_phase(self._plan, now)
            if s.on_break is not None and phase.on_break != s.on_break:
                signal(SignalKind.BREAK_DUE if phase.on_break else SignalKind.BREAK_OVER)
                if phase.on_break:
                    self._clear_episode(finished=False)
            s.on_break = phase.on_break
            ends_at = self._plan.started_at + self._plan.duration
            if not s.ending_sent and now >= ends_at - timedelta(seconds=t.session_ending_seconds):
                s.ending_sent = True
                signal(SignalKind.SESSION_ENDING)

        # Idle: long inactivity is not drift.
        if sample.idle_seconds >= t.idle_after_seconds:
            if not s.idle_sent:
                s.idle_sent = True
                signal(SignalKind.IDLE, assessment=assessment)
        else:
            s.idle_sent = False

        signals.extend(self._account(sample, assessment, dt))

        # Breakpoints: moments the learner can respond without losing a thought.
        if (
            previous is not None
            and previous.idle_seconds > t.idle_resume_after_seconds
            and sample.idle_seconds < min(previous.idle_seconds, t.idle_resume_after_seconds)
        ):
            self._breakpoint(signals, sample, assessment, BreakpointKind.IDLE_RESUME)
        if sample.is_switch:
            self._breakpoint(signals, sample, assessment, BreakpointKind.APP_SWITCH)
        if sample.input_events >= t.busy_events_per_sample:
            s.busy_seconds += dt
        elif sample.input_events == 0 and sample.idle_seconds >= t.typing_pause_seconds:
            if s.busy_seconds >= t.busy_stretch_seconds:
                self._breakpoint(signals, sample, assessment, BreakpointKind.TYPING_PAUSE)
            s.busy_seconds = 0.0

        s.previous = sample
        s.previous_assessment = assessment
        return signals

    # --- drift accounting --------------------------------------------------------

    def _account(
        self, sample: ActivitySample, assessment: TrackAssessment, dt: float
    ) -> list[FocusSignal]:
        t, s = self.thresholds, self._s
        now = sample.at
        out: list[FocusSignal] = []

        def emit(kind: SignalKind, drift_seconds: float) -> None:
            out.append(
                FocusSignal(
                    kind=kind,
                    sample=sample,
                    assessment=assessment,
                    drift_seconds=drift_seconds,
                    at=now,
                )
            )

        # 1. The interval since the previous sample counts under the judgment
        #    that held during it (the previous sample's).
        if s.previous is not None and s.previous_assessment is not None:
            self._accrue(s.previous, s.previous_assessment, dt)

        # 2. React to the current judgment.
        judgment = assessment.judgment
        if sample.idle_seconds >= t.idle_pause_seconds:
            return out  # away, or reading without input: neither drift nor return
        if judgment == TrackJudgment.ON_BREAK:
            self._clear_episode(finished=False)
            return out
        if judgment == TrackJudgment.ON_GOAL:
            if s.on_since is None:
                s.on_since = now
                s.on_streak = 0.0
            if s.on_streak >= t.return_grace_seconds and (
                s.drifting or s.episode_start is not None
            ):
                if s.drifting and s.episode_start is not None:
                    length = max((s.on_since - s.episode_start).total_seconds(), 0.0)
                    emit(SignalKind.RETURNED, length)
                    self._add(drift_seconds=length)
                self._clear_episode(finished=True)
            return out

        # OFF_GOAL or UNSURE.
        s.on_since = None
        s.on_streak = 0.0
        if s.episode_start is None:
            s.episode_start = now
        repeated = False
        if self._strong_off(assessment):
            visits = s.visits.setdefault(sample.app, deque())
            if sample.is_switch or s.previous is None or s.previous.app != sample.app:
                visits.append(now)
            window = timedelta(seconds=t.repeat_window_seconds)
            while visits and now - visits[0] > window:
                visits.popleft()
            repeated = len(visits) >= t.repeat_visits

        length = (now - s.episode_start).total_seconds()
        if not s.drifting and (s.off_score >= t.drift_after_seconds or repeated):
            s.drifting = True
            s.last_continuing = now
            s.visits.pop(sample.app, None)
            self._add(drift_count=1)
            emit(SignalKind.DRIFT_STARTED, length)
        elif (
            s.drifting
            and s.last_continuing is not None
            and (now - s.last_continuing).total_seconds() >= t.continuing_every_seconds
        ):
            s.last_continuing = now
            emit(SignalKind.DRIFT_CONTINUING, length)
        return out

    def _accrue(self, held: ActivitySample, assessment: TrackAssessment, dt: float) -> None:
        t, s = self.thresholds, self._s
        judgment = assessment.judgment
        if held.idle_seconds >= t.idle_pause_seconds:
            self._add(idle_seconds=dt)
        elif judgment == TrackJudgment.ON_BREAK:
            self._add(break_seconds=dt)
        elif judgment == TrackJudgment.ON_GOAL:
            self._add(on_goal_seconds=dt)
            if s.on_since is not None:
                s.on_streak += dt
        elif self._strong_off(assessment):
            self._add(off_goal_seconds=dt)
            if s.episode_start is not None:
                s.off_score += dt
        else:
            self._add(unsure_seconds=dt)
            if s.episode_start is not None:
                s.off_score += dt * t.unsure_weight

    def _strong_off(self, assessment: TrackAssessment) -> bool:
        return (
            assessment.judgment == TrackJudgment.OFF_GOAL
            and assessment.confidence >= self.thresholds.min_off_confidence
        )

    @staticmethod
    def _breakpoint(
        signals: list[FocusSignal],
        sample: ActivitySample,
        assessment: TrackAssessment,
        kind: BreakpointKind,
    ) -> None:
        signals.append(
            FocusSignal(
                kind=SignalKind.BREAKPOINT,
                sample=sample,
                assessment=assessment,
                breakpoint=kind,
                at=sample.at,
            )
        )

    def _clear_episode(self, *, finished: bool) -> None:
        s = self._s
        s.off_score = 0.0
        s.episode_start = None
        s.drifting = False
        s.last_continuing = None
        if not finished:
            s.on_streak = 0.0
            s.on_since = None

    def _add(self, **deltas: float) -> None:
        totals = self._s.totals
        self._s.totals = replace(
            totals, **{name: getattr(totals, name) + value for name, value in deltas.items()}
        )
