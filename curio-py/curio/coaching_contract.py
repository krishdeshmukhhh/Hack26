"""Shared, Qt-free coaching boundary. See docs/coaching-contract.md."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol


class SessionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AssistanceLevel(StrEnum):
    HINT = "hint"
    EXPLANATION = "explanation"
    WORKED_EXAMPLE = "worked_example"


class AssessmentStatus(StrEnum):
    CONFIRMED = "confirmed"
    INCORRECT = "incorrect"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, kw_only=True)
class SourceReference:
    id: str
    uri: str  # URL or opaque local artifact ID; never implicitly fetched.
    locator: str = ""  # Section, page, timestamp, line range, or screen region.
    title: str = ""


class EvidenceKind(StrEnum):
    OBSERVATION = "observation"
    VERIFIER_RESULT = "verifier_result"
    USER_CLAIM = "user_claim"
    MODEL_CLAIM = "model_claim"
    CLICK = "click"


@dataclass(frozen=True, kw_only=True)
class Evidence:
    id: str
    kind: EvidenceKind
    summary: str
    sources: tuple[SourceReference, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Goal:
    id: str
    description: str
    success_criteria: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class TutorialStep:
    """An instruction, never a correctness verdict or completion signal."""

    id: str
    goal_id: str
    instruction: str
    sources: tuple[SourceReference, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CoachingSession:
    id: str
    goals: tuple[Goal, ...]
    status: SessionStatus = SessionStatus.CREATED
    steps: tuple[TutorialStep, ...] = ()

    def transition(self, status: SessionStatus) -> CoachingSession:
        allowed = {
            SessionStatus.CREATED: {SessionStatus.ACTIVE, SessionStatus.CANCELLED},
            SessionStatus.ACTIVE: {
                SessionStatus.PAUSED,
                SessionStatus.COMPLETED,
                SessionStatus.CANCELLED,
                SessionStatus.FAILED,
            },
            SessionStatus.PAUSED: {
                SessionStatus.ACTIVE,
                SessionStatus.CANCELLED,
                SessionStatus.FAILED,
            },
        }
        if status not in allowed.get(self.status, set()):
            raise ValueError(f"Invalid session transition: {self.status} -> {status}")
        return replace(self, status=status)


@dataclass(frozen=True, kw_only=True)
class UserQuestion:
    id: str
    session_id: str
    text: str
    step_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class SubmittedWork:
    id: str
    session_id: str
    text: str = ""
    sources: tuple[SourceReference, ...] = ()
    step_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class StepAssessment:
    session_id: str
    work_id: str
    status: AssessmentStatus
    rationale: str
    step_id: str | None = None
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        if self.status in {AssessmentStatus.CONFIRMED, AssessmentStatus.INCORRECT} and not any(
            item.kind in {EvidenceKind.OBSERVATION, EvidenceKind.VERIFIER_RESULT}
            and item.sources
            for item in self.evidence
        ):
            raise ValueError("A correctness verdict requires source-backed observed evidence")


@dataclass(frozen=True, kw_only=True)
class CoachingReply:
    text: str
    level: AssistanceLevel
    suggested_steps: tuple[TutorialStep, ...] = ()
    sources: tuple[SourceReference, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ExtractedContent:
    text: str
    sources: tuple[SourceReference, ...]


class OperationCancelled(Exception):
    """Cooperative cancellation of a coaching provider operation."""


@dataclass
class CancellationToken:
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelled()


@dataclass(frozen=True, kw_only=True)
class RequestContext:
    session_id: str
    request_id: str
    cancellation: CancellationToken


class ContentExtractor(Protocol):
    async def extract(
        self,
        source: SourceReference,
        *,
        context: RequestContext,
    ) -> ExtractedContent: ...


class CoachingProvider(Protocol):
    async def coach(
        self,
        session: CoachingSession,
        question: UserQuestion,
        *,
        level: AssistanceLevel,
        work: SubmittedWork | None,
        content: ExtractedContent | None,
        context: RequestContext,
    ) -> CoachingReply: ...


class VerificationProvider(Protocol):
    async def assess(
        self,
        session: CoachingSession,
        work: SubmittedWork,
        *,
        context: RequestContext,
    ) -> StepAssessment: ...


class EventKind(StrEnum):
    SESSION_CHANGED = "session_changed"
    STEPS_PROPOSED = "steps_proposed"
    REPLY_READY = "reply_ready"
    ASSESSMENT_READY = "assessment_ready"


@dataclass(frozen=True, kw_only=True)
class CoachingEvent:
    context: RequestContext
    kind: EventKind
    payload: CoachingSession | CoachingReply | StepAssessment


@dataclass(frozen=True, kw_only=True)
class CoachingNotification:
    context: RequestContext
    code: str  # Stable code, e.g. coaching.provider_unavailable.
    message: str  # UI-safe text; no secrets or raw work content.
    severity: str = "info"  # info, warning, error


Unsubscribe = Callable[[], None]


class CoachingEvents(Protocol):
    def subscribe_events(self, callback: Callable[[CoachingEvent], None]) -> Unsubscribe: ...

    def subscribe_notifications(
        self,
        callback: Callable[[CoachingNotification], None],
    ) -> Unsubscribe: ...
