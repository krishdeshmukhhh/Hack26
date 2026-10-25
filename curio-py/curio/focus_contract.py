"""Shared contracts for focus/learning mode.

Standard library only; no Qt, persistence, network or model clients. Behaviour
and the evidence behind each rule are in docs/focus-learning-research.md;
workstream ownership is in docs/parallel-focus/README.md. Change this file
only through the focus-session workstream.

Flow: an ActivitySource emits ActivitySamples -> a TrackClassifier judges them
against the FocusPlan -> a DriftTracker turns judgments into FocusSignals ->
the FocusPolicy decides whether to show an Intervention. Separately, a
StudyCoach picks the next TutorDirective and schedules ReviewItems.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from curio.coaching_contract import AssistanceLevel as CoachingAssistance


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


# --- Session plan -------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class IfThenPlan:
    """Implementation intention: "if <cue>, then <response>"."""

    cue: str  # e.g. "i open youtube"
    response: str  # e.g. "close it and say back to it"
    cue_apps: tuple[str, ...] = ()  # app_key()s or title substrings that trigger it


class BreakStyle(StrEnum):
    FIXED = "fixed"  # default: fixed study/break cycle
    SELF_PACED = "self_paced"
    NONE = "none"


@dataclass(frozen=True, kw_only=True)
class FocusPlan:
    goal: str
    duration: timedelta
    if_then: tuple[IfThenPlan, ...] = ()
    allowed_apps: tuple[str, ...] = ()  # app_key()s that always count as on-goal
    study_minutes: int = 25
    break_minutes: int = 5
    break_style: BreakStyle = BreakStyle.FIXED
    strict: bool = False  # more persistent check-ins; never blocks anything
    concepts: tuple[str, ...] = ()  # concept_key()s the session is about, if known
    id: str = field(default_factory=_new_id)
    started_at: datetime = field(default_factory=_utc_now)


# --- Sensing ------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ActivitySample:
    """One poll of the desktop. Never contains keystroke content."""

    app: str  # learning_contract.app_key() of the foreground window
    window_title: str  # local only; sent to a model only if the user allows it
    idle_seconds: float
    input_events: int  # key + mouse events since the previous sample, a count only
    is_switch: bool  # foreground window changed since the previous sample
    at: datetime = field(default_factory=_utc_now)


class TrackJudgment(StrEnum):
    ON_GOAL = "on_goal"
    OFF_GOAL = "off_goal"
    UNSURE = "unsure"
    ON_BREAK = "on_break"


class JudgmentSource(StrEnum):
    RULE = "rule"
    MODEL = "model"
    USER = "user"  # user corrections always win


@dataclass(frozen=True, kw_only=True)
class TrackAssessment:
    judgment: TrackJudgment
    confidence: float  # 0..1
    source: JudgmentSource
    reason: str = ""  # short, shown in "why did curio check in?"


class BreakpointKind(StrEnum):
    APP_SWITCH = "app_switch"
    IDLE_RESUME = "idle_resume"
    TYPING_PAUSE = "typing_pause"
    STEP_DONE = "step_done"  # a walkthrough or tutoring step finished


class SignalKind(StrEnum):
    DRIFT_STARTED = "drift_started"  # sustained off-goal time crossed the threshold
    DRIFT_CONTINUING = "drift_continuing"
    RETURNED = "returned"  # back on goal after a drift
    BREAKPOINT = "breakpoint"
    IDLE = "idle"
    BREAK_DUE = "break_due"
    BREAK_OVER = "break_over"
    SESSION_ENDING = "session_ending"


@dataclass(frozen=True, kw_only=True)
class FocusSignal:
    kind: SignalKind
    sample: ActivitySample | None = None
    assessment: TrackAssessment | None = None
    breakpoint: BreakpointKind | None = None
    drift_seconds: float = 0.0
    at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, kw_only=True)
class ResumeNote:
    """Where the learner was and what's next ("ready to resume" plan)."""

    where: str
    next_action: str
    source: str = ""  # "walkthrough", "plan", "spoken"
    at: datetime = field(default_factory=_utc_now)


# --- Interventions ------------------------------------------------------------


class InterventionKind(StrEnum):
    AMBIENT_CUE = "ambient_cue"  # pet animation only, no sound
    CHECK_IN = "check_in"  # short spoken question with choices
    PLAN_REMINDER = "plan_reminder"  # repeats the learner's own if-then plan
    RESUME = "resume"  # reads back a ResumeNote
    BREAK_START = "break_start"
    BREAK_END = "break_end"
    METACOGNITIVE = "metacognitive"  # plan / monitor / evaluate prompt
    REFLECTION = "reflection"  # end-of-session
    REVIEW = "review"  # spaced retrieval questions


class InterventionResponse(StrEnum):
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"
    FALSE_ALARM = "false_alarm"  # "that wasn't a distraction"; feeds the classifier
    IGNORED = "ignored"  # expired without a response


@dataclass(frozen=True, kw_only=True)
class Intervention:
    kind: InterventionKind
    message: str  # spoken text; offers choices, never orders
    choices: tuple[str, ...] = ()  # e.g. ("back to it", "take a break", "not a distraction")
    rationale: str = ""  # section of focus-learning-research.md, e.g. "C"
    expires_after: timedelta = timedelta(seconds=30)
    id: str = field(default_factory=_new_id)
    at: datetime = field(default_factory=_utc_now)


# --- Study coaching -------------------------------------------------------------


class TutoringMove(StrEnum):
    """Next tutoring action, least help first (see research doc, section G)."""

    WAIT = "wait"  # let the learner work on it
    GUIDING_QUESTION = "guiding_question"
    HINT = "hint"
    PARTIAL_STEP = "partial_step"
    WORKED_EXAMPLE = "worked_example"
    SELF_EXPLAIN = "self_explain"  # "why did that work?"; never right after a worked example
    TRY_FIRST = "try_first"  # response to hint abuse: ask for an attempt
    FEEDBACK = "feedback"


HELP_LADDER: tuple[TutoringMove, ...] = (
    TutoringMove.GUIDING_QUESTION,
    TutoringMove.HINT,
    TutoringMove.PARTIAL_STEP,
    TutoringMove.WORKED_EXAMPLE,
)

# The coaching contract's assistance level that a move maps to, where one exists.
COACHING_LEVEL: dict[TutoringMove, CoachingAssistance] = {
    TutoringMove.GUIDING_QUESTION: CoachingAssistance.HINT,
    TutoringMove.HINT: CoachingAssistance.HINT,
    TutoringMove.PARTIAL_STEP: CoachingAssistance.EXPLANATION,
    TutoringMove.WORKED_EXAMPLE: CoachingAssistance.WORKED_EXAMPLE,
}


class LearnerEventKind(StrEnum):
    HELP_REQUESTED = "help_requested"
    ATTEMPT_FAILED = "attempt_failed"
    ATTEMPT_SUCCEEDED = "attempt_succeeded"
    STUCK = "stuck"  # no progress for a while (from the policy or the walkthrough)
    WORKED_EXAMPLE_SHOWN = "worked_example_shown"
    EXPLANATION_GIVEN = "explanation_given"  # learner explained their reasoning


@dataclass(frozen=True, kw_only=True)
class LearnerEvent:
    kind: LearnerEventKind
    concepts: tuple[str, ...] = ()
    problem_id: str = ""  # groups events about the same problem or step
    at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, kw_only=True)
class TutorDirective:
    """What the model should do on this turn; integration adds it to the request."""

    move: TutoringMove
    instruction: str  # one or two lines for the prompt, e.g. "give one hint, not the answer"
    wait_seconds: float = 0.0  # for WAIT: how long before offering help
    rationale: str = ""


@dataclass(frozen=True, kw_only=True)
class ReviewItem:
    concept: str
    question: str
    answer: str
    due_at: datetime
    interval_days: float = 1.0
    repetitions: int = 0
    lapses: int = 0
    id: str = field(default_factory=_new_id)


@dataclass(frozen=True, kw_only=True)
class SessionSummary:
    plan_id: str
    goal: str
    started_at: datetime
    ended_at: datetime
    on_goal_seconds: float
    off_goal_seconds: float
    break_seconds: float
    drift_count: int
    interventions: int
    false_alarms: int
    concepts_practised: tuple[str, ...] = ()
    reflection: str = ""  # learner's own words, optional


# --- Protocols -----------------------------------------------------------------


Unsubscribe = Callable[[], None]

# Injected text-only model call: (system_prompt, user_text) -> reply. The
# focus-session workstream builds it from the configured backend; others
# accept it as a constructor argument and must work (degraded) without one.
ModelCall = Callable[[str, str], Awaitable[str]]


class ActivitySource(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def subscribe(self, callback: Callable[[ActivitySample], None]) -> Unsubscribe: ...


class TrackClassifier(Protocol):
    async def assess(self, sample: ActivitySample, plan: FocusPlan) -> TrackAssessment: ...

    async def correct(self, sample: ActivitySample, judgment: TrackJudgment) -> None:
        """Remember the learner's correction for this app/title."""
        ...


class DriftTracker(Protocol):
    """Turns per-sample assessments into FocusSignals (thresholds, breakpoints)."""

    def update(
        self, sample: ActivitySample, assessment: TrackAssessment
    ) -> Sequence[FocusSignal]: ...

    def reset(self, plan: FocusPlan) -> None: ...


class FocusPolicy(Protocol):
    def decide(self, signal: FocusSignal, plan: FocusPlan) -> Intervention | None: ...

    def record_response(self, intervention: Intervention, response: InterventionResponse) -> None: ...

    def resume_note(self) -> ResumeNote | None: ...

    def set_resume_note(self, note: ResumeNote) -> None: ...


class StudyCoach(Protocol):
    def next_move(self, event: LearnerEvent, mastery: float | None = None) -> TutorDirective: ...

    async def due_reviews(self, now: datetime, limit: int = 3) -> tuple[ReviewItem, ...]: ...

    async def record_review(self, item: ReviewItem, correct: bool) -> ReviewItem: ...

    async def add_review_items(self, items: Sequence[ReviewItem]) -> None: ...


class SessionStore(Protocol):
    async def save_summary(self, summary: SessionSummary) -> None: ...

    async def summaries(self, limit: int = 50) -> tuple[SessionSummary, ...]: ...

    async def clear(self) -> None: ...
