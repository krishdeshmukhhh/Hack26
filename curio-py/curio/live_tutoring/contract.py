"""Shared provider/event adapter around the deterministic tutoring session."""

from contextlib import suppress

from curio.coaching_contract import (
    AssessmentStatus,
    AssistanceLevel,
    CoachingEvent,
    CoachingReply,
    EventKind,
    Evidence,
    EvidenceKind,
    SessionStatus,
    SourceReference,
    StepAssessment,
)

from .service import TutoringService


class TutoringProvider:
    """One provider per session. Implements coaching, verification and events.

    Call open(session, integrand, context=...) before assess/coach. All methods
    run on the host event-loop thread. Caller assigns fresh request/work IDs.
    """

    def __init__(self, service=None):
        self.service = service or TutoringService()
        self.session = None
        self._events = []
        self._notifications = []
        self._context = None
        self._requests = set()
        self._works = set()

    def subscribe_events(self, callback):
        self._events.append(callback)
        return lambda: self._remove(self._events, callback)

    def subscribe_notifications(self, callback):
        self._notifications.append(callback)
        return lambda: self._remove(self._notifications, callback)

    @staticmethod
    def _remove(listeners, callback):
        if callback in listeners:
            listeners.remove(callback)

    def _emit(self, kind, payload, context):
        event = CoachingEvent(context=context, kind=kind, payload=payload)
        for callback in tuple(self._events):
            with suppress(Exception):
                callback(event)

    def _request(self, context):
        context.cancellation.raise_if_cancelled()
        if self.session is None or context.session_id != self.session.id:
            raise ValueError("Context does not match the open session")
        if not context.request_id or context.request_id in self._requests:
            raise ValueError("A fresh nonempty request ID is required")
        if self.session.status != SessionStatus.ACTIVE:
            raise ValueError("Session is not active")
        if self._context is not None:
            self._context.cancellation.cancel()
        self._context = context
        self._requests.add(context.request_id)

    def open(self, session, integrand, *, context):
        if self.session is not None:
            raise ValueError("Create a new provider for a new session")
        goal_ids = [goal.id for goal in session.goals]
        step_ids = [step.id for step in session.steps]
        if (
            not session.id
            or not goal_ids
            or not all(goal_ids)
            or len(set(goal_ids)) != len(goal_ids)
            or not all(step_ids)
            or len(set(step_ids)) != len(step_ids)
            or any(step.goal_id not in goal_ids for step in session.steps)
        ):
            raise ValueError("Invalid goal or step references")
        if context.session_id != session.id or session.status != SessionStatus.CREATED:
            raise ValueError("Expected a matching created session")
        context.cancellation.raise_if_cancelled()
        self.service.start(integrand)
        self.session = session.transition(SessionStatus.ACTIVE)
        self._request(context)
        self._emit(EventKind.SESSION_CHANGED, self.session, context)

    def _validate_work(self, work):
        if not work.id or work.id in self._works or work.session_id != self.session.id:
            raise ValueError("Work must have a fresh ID and matching session")
        if work.step_id is not None and work.step_id not in {s.id for s in self.session.steps}:
            raise ValueError("Unknown step reference")

    async def assess(self, session, work, *, context):
        if session != self.session:
            raise ValueError("Stale session snapshot")
        self._validate_work(work)
        self._request(context)
        self._works.add(work.id)
        feedback = self.service.submit(work.text)
        status = feedback.status
        evidence = ()
        if status in {AssessmentStatus.CONFIRMED, AssessmentStatus.INCORRECT}:
            evidence = (
                Evidence(
                    id=f"{work.id}:symbolic",
                    kind=EvidenceKind.VERIFIER_RESULT,
                    summary=feedback.message,
                    sources=(
                        SourceReference(
                            id=work.id, uri=f"work:{work.id}", locator="submitted equation"
                        ),
                    ),
                ),
            )
        assessment = StepAssessment(
            session_id=session.id,
            work_id=work.id,
            step_id=work.step_id,
            status=status,
            rationale=feedback.message,
            evidence=evidence,
        )
        context.cancellation.raise_if_cancelled()
        self._emit(EventKind.ASSESSMENT_READY, assessment, context)
        return assessment

    async def coach(
        self, session, question, *, level=AssistanceLevel.HINT, work=None, content=None, context
    ):
        if session != self.session or question.session_id != session.id or not question.id:
            raise ValueError("Question does not match current session")
        if question.step_id is not None and question.step_id not in {s.id for s in session.steps}:
            raise ValueError("Unknown question step")
        if work is not None and work.session_id != session.id:
            raise ValueError("Work belongs to another session")
        self._request(context)
        self.service.hint_level = {
            AssistanceLevel.HINT: 0,
            AssistanceLevel.EXPLANATION: 1,
            AssistanceLevel.WORKED_EXAMPLE: 2,
        }[level]
        # External content and question text never authorize capture or evaluation.
        reply = CoachingReply(text=self.service.help(), level=level)
        self._emit(EventKind.REPLY_READY, reply, context)
        return reply

    def cancel(self):
        if self.session is None or self.session.status != SessionStatus.ACTIVE:
            return
        self.service.cancel()
        self._context.cancellation.cancel()
        self.session = self.session.transition(SessionStatus.CANCELLED)
        self._emit(EventKind.SESSION_CHANGED, self.session, self._context)
