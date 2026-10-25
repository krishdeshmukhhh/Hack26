"""One owner for a focus session: sensing -> policy -> presenter, and back.

Wires ActivitySource -> TrackClassifier -> DriftTracker -> FocusPolicy and
hands each Intervention to a presenter. Responses come back through
``respond``: every response goes to the policy, and "not a distraction" also
corrects the classifier. Samples are processed in order on one asyncio task,
so a slow model judgment never reorders the timeline. Construct and use on
the Qt/qasync thread; ``aclose()`` awaits everything it started.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from curio.focus_contract import (
    ActivitySample,
    ActivitySource,
    DriftTracker,
    FocusPlan,
    FocusPolicy,
    FocusSignal,
    IfThenPlan,
    Intervention,
    InterventionKind,
    InterventionResponse,
    ModelCall,
    ResumeNote,
    ReviewItem,
    SessionStore,
    SessionSummary,
    SignalKind,
    StudyCoach,
    TrackClassifier,
    TrackJudgment,
    Unsubscribe,
)
from curio.focus_session.planning import past_distractions, suggest_if_then
from curio.focus_session.timeline import SessionTimeline, TimelineState
from curio.learning_contract import concept_key

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
Responder = Callable[[Intervention, InterventionResponse], None]
# (concepts, context notes) -> new review items; F3's generate_review_items, bound.
ReviewGenerator = Callable[[Sequence[str], str], Awaitable[Sequence[ReviewItem]]]
ResumeContext = Callable[[], ResumeNote | None]

REVIEW_LIMIT = 3


class Presenter(Protocol):
    """Shows interventions and pet reactions; reports answers to the responder."""

    def bind(self, responder: Responder) -> None: ...

    def show(self, intervention: Intervention) -> None: ...

    def signal(self, signal: FocusSignal) -> None: ...

    def clear(self) -> None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_model_call(provider, model: str, *, max_tokens: int = 400, timeout: float = 30.0):
    """A text-only ModelCall over a dedicated LLM client (one not used for voice)."""

    async def call(system: str, user_text: str) -> str:
        async with asyncio.timeout(timeout):
            return await provider.send(
                [{"role": "user", "content": user_text}],
                system=system,
                model=model,
                max_tokens=max_tokens,
            )

    return call


@dataclass
class _Pending:
    intervention: Intervention
    sample: ActivitySample | None


class FocusRuntime(QObject):
    session_started = Signal(object)  # FocusPlan
    timeline_changed = Signal()
    intervention_shown = Signal(object)  # Intervention
    session_ended = Signal(object)  # SessionSummary
    error = Signal(str)

    def __init__(
        self,
        *,
        source: ActivitySource,
        classifier: TrackClassifier,
        tracker: DriftTracker,
        policy: FocusPolicy,
        presenter: Presenter,
        coach: StudyCoach | None = None,
        store: SessionStore | None = None,
        generate_reviews: ReviewGenerator | None = None,
        model_call: ModelCall | None = None,
        resume_context: ResumeContext | None = None,
        clock: Clock = _utc_now,
        parent=None,
    ):
        super().__init__(parent)
        self.source = source
        self.classifier = classifier
        self.tracker = tracker
        self.policy = policy
        self.presenter = presenter
        self.coach = coach
        self.store = store
        self.model_call = model_call
        self._generate_reviews = generate_reviews
        self._resume_context = resume_context
        self._clock = clock
        self.plan: FocusPlan | None = None
        self.timeline: SessionTimeline | None = None
        self._queue: asyncio.Queue[ActivitySample] | None = None
        self._worker: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._unsubscribe: Unsubscribe | None = None
        self._tasks: set[asyncio.Task] = set()
        self._pending: dict[str, _Pending] = {}
        self._last_sample: ActivitySample | None = None
        self._last_resume: ResumeNote | None = None
        self._drifting = False
        self._in_break = False
        self._drift_apps: list[str] = []
        self._concepts: dict[str, None] = {}
        self._notes: list[str] = []
        self._interventions = 0
        self._false_alarms = 0
        self._ending = False
        self._closed = False
        presenter.bind(self.respond)

    # --- lifecycle --------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.plan is not None and not self._ending

    def start(self, plan: FocusPlan) -> None:
        if self._closed:
            raise RuntimeError("Focus runtime is closed")
        if self.plan is not None:
            raise RuntimeError("A focus session is already running")
        self._loop = asyncio.get_running_loop()
        self._reset(plan)
        self.tracker.reset(plan)
        self._queue = asyncio.Queue()
        self._worker = self._loop.create_task(self._work(self._queue))
        self._unsubscribe = self.source.subscribe(self._on_sample)
        self.source.start()
        self.session_started.emit(plan)
        self.timeline_changed.emit()

    def _reset(self, plan: FocusPlan) -> None:
        self.plan = plan
        self.timeline = SessionTimeline(plan.started_at)
        self._pending.clear()
        self._last_sample = self._last_resume = None
        self._drifting = self._in_break = self._ending = False
        self._drift_apps = []
        self._concepts = dict.fromkeys(plan.concepts)
        self._notes = []
        self._interventions = self._false_alarms = 0

    async def _detach(self, *, drain: bool) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self.source.stop()
        self.presenter.clear()
        for pending in tuple(self._pending.values()):
            self.policy.record_response(pending.intervention, InterventionResponse.IGNORED)
        self._pending.clear()
        worker, self._worker = self._worker, None
        if worker is None or worker is asyncio.current_task():
            return
        if drain and self._queue is not None:
            await self._queue.join()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    async def end(self) -> SessionSummary | None:
        """Stop sensing, process queued samples, then save and emit the summary."""
        if self.plan is None or self._ending:
            return None
        self._ending = True
        await self._detach(drain=True)
        summary = self.summary()
        await self.save(summary)
        self.session_ended.emit(summary)
        return summary

    async def cancel(self) -> None:
        """Discard the session: nothing is saved."""
        if self.plan is None:
            return
        self._ending = True
        await self._detach(drain=False)
        self.plan = None
        self.timeline_changed.emit()

    def finish(self) -> None:
        """Forget the ended session once the summary window is done with it."""
        if self._ending:
            self.plan = None
            self._ending = False

    def request_end(self) -> None:
        self._spawn(self.end())

    async def aclose(self) -> None:
        if self._closed:
            return
        await self.cancel()
        self._closed = True
        tasks = tuple(t for t in self._tasks if t is not asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _spawn(self, coro: Awaitable) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # --- context from the rest of the app -------------------------------------

    def set_resume_context(self, note: ResumeNote) -> None:
        """Latest "where you were / what's next" (walkthrough step or spoken line)."""
        self._last_resume = note
        self.policy.set_resume_note(note)

    def note_concepts(self, concepts: Sequence[str], context: str = "") -> None:
        """Concepts practised this session (from tutoring or walkthrough steps)."""
        for concept in concepts:
            if key := concept_key(concept):
                self._concepts[key] = None
        if context.strip():
            self._notes.append(" ".join(context.split())[:300])

    def _plan_resume_note(self) -> ResumeNote | None:
        if self._resume_context is not None:
            try:
                return self._resume_context()
            except Exception:
                logger.exception("Resume context provider failed")
        if self._last_resume is None and self.plan is not None:
            return ResumeNote(
                where=self.plan.goal,
                next_action=f"the next part of {self.plan.goal}",
                source="plan",
                at=self._clock(),
            )
        return None

    # --- sample pipeline --------------------------------------------------------

    def _on_sample(self, sample: ActivitySample) -> None:
        if self._queue is None or self._loop is None or self._ending:
            return
        queue = self._queue
        try:
            same_loop = asyncio.get_running_loop() is self._loop
        except RuntimeError:
            same_loop = False
        if same_loop:
            queue.put_nowait(sample)
        else:
            self._loop.call_soon_threadsafe(queue.put_nowait, sample)

    async def _work(self, queue: asyncio.Queue[ActivitySample]) -> None:
        while True:
            sample = await queue.get()
            try:
                await self.process(sample)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Focus sample processing failed")
            finally:
                queue.task_done()

    async def process(self, sample: ActivitySample) -> None:
        """Run one sample through the pipeline. Public for tests and replays."""
        plan, timeline = self.plan, self.timeline
        if plan is None or timeline is None:
            return
        assessment = await self.classifier.assess(sample, plan)
        if self.plan is not plan:
            return
        self._last_sample = sample
        timeline.observe(sample.at)
        for signal in self.tracker.update(sample, assessment):
            self._handle_signal(signal, plan, timeline)
        if assessment.judgment == TrackJudgment.ON_BREAK or self._in_break:
            state = TimelineState.BREAK
        elif self._drifting:
            state = TimelineState.DRIFTING
        else:
            state = TimelineState.ON_GOAL
        timeline.set_state(state, sample.at)
        self.timeline_changed.emit()
        if sample.at >= plan.started_at + plan.duration and not self._ending:
            self.request_end()

    def _handle_signal(self, signal: FocusSignal, plan: FocusPlan, timeline) -> None:
        if signal.kind == SignalKind.DRIFT_STARTED and not self._drifting:
            self._drifting = True
            timeline.drift_started(signal.at, signal.drift_seconds)
            sample = signal.sample or self._last_sample
            if sample is not None and sample.app:
                self._drift_apps.append(sample.app)
            note = self._plan_resume_note()
            if note is not None and note != self._last_resume:
                self._last_resume = note
                self.policy.set_resume_note(note)
        elif signal.kind == SignalKind.RETURNED:
            self._drifting = False
            timeline.set_state(TimelineState.ON_GOAL, signal.at)
        elif signal.kind == SignalKind.BREAK_OVER:
            self._in_break = False
        self.presenter.signal(signal)
        intervention = self.policy.decide(signal, plan)
        if intervention is not None:
            self._deliver(intervention, signal.sample or self._last_sample)

    def _deliver(self, intervention: Intervention, sample: ActivitySample | None) -> None:
        self._interventions += 1
        if intervention.kind == InterventionKind.BREAK_END:
            self._in_break = False
        if intervention.kind != InterventionKind.AMBIENT_CUE:
            self._pending[intervention.id] = _Pending(intervention, sample)
        self.intervention_shown.emit(intervention)
        self.presenter.show(intervention)

    # --- responses ------------------------------------------------------------

    def respond(self, intervention: Intervention, response: InterventionResponse) -> None:
        """Called by the presenter once per intervention (choice, voice or expiry)."""
        pending = self._pending.pop(intervention.id, None)
        if pending is None:
            return
        self.policy.record_response(intervention, response)
        if response == InterventionResponse.FALSE_ALARM:
            self._false_alarms += 1
            if self.timeline is not None and self._drifting and self.timeline.unmark_latest_drift():
                self._drifting = False
                if self._drift_apps:
                    self._drift_apps.pop()
                self.timeline_changed.emit()
            sample = pending.sample or self._last_sample
            if sample is not None:
                self._spawn(self._correct(sample))
        elif (
            intervention.kind == InterventionKind.BREAK_START
            and response == InterventionResponse.ACCEPTED
            and self.timeline is not None
        ):
            self._in_break = True
            self.timeline.set_state(TimelineState.BREAK, self._clock())
            self.timeline_changed.emit()

    async def _correct(self, sample: ActivitySample) -> None:
        try:
            await self.classifier.correct(sample, TrackJudgment.ON_GOAL)
        except Exception:
            logger.exception("Classifier correction failed")
            self.error.emit("Couldn't save that correction; Curio may ask about it again.")

    # --- summary and review ---------------------------------------------------

    @property
    def drift_count(self) -> int:
        return len(self._drift_apps)

    def summary(self, reflection: str = "") -> SessionSummary:
        if self.plan is None or self.timeline is None:
            raise RuntimeError("No focus session")
        totals = self.timeline.totals()
        return SessionSummary(
            plan_id=self.plan.id,
            goal=self.plan.goal,
            started_at=self.plan.started_at,
            ended_at=max(self.timeline.now, self.plan.started_at),
            on_goal_seconds=totals[TimelineState.ON_GOAL],
            off_goal_seconds=totals[TimelineState.DRIFTING],
            break_seconds=totals[TimelineState.BREAK],
            drift_count=self.drift_count,
            interventions=self._interventions,
            false_alarms=self._false_alarms,
            concepts_practised=tuple(self._concepts),
            reflection=" ".join(reflection.split())[:280],
            distractions=tuple(dict.fromkeys(self._drift_apps)),
        )

    async def save(self, summary: SessionSummary) -> bool:
        if self.store is None:
            return False
        try:
            await self.store.save_summary(summary)
        except Exception:
            logger.exception("Saving focus summary failed")
            self.error.emit("Couldn't save the session summary.")
            return False
        return True

    async def past_summaries(self, limit: int = 20) -> tuple[SessionSummary, ...]:
        if self.store is None:
            return ()
        try:
            return await self.store.summaries(limit)
        except Exception:
            logger.exception("Loading focus summaries failed")
            return ()

    async def suggest_if_then(self, goal: str) -> tuple[IfThenPlan, ...]:
        """If-then suggestions for the start panel, seeded by past drift apps."""
        distractions = past_distractions(await self.past_summaries())
        return await suggest_if_then(goal, distractions, self.model_call)

    async def review_items(self, concepts: Sequence[str] = ()) -> tuple[ReviewItem, ...]:
        """Today's quiz: new items for the session's concepts first, then due ones."""
        if self.coach is None:
            return ()
        concepts = tuple(concepts) or tuple(self._concepts)
        fresh: tuple[ReviewItem, ...] = ()
        if concepts and self._generate_reviews is not None:
            try:
                fresh = tuple(await self._generate_reviews(concepts, "\n".join(self._notes)))
                if fresh:
                    await self.coach.add_review_items(fresh)
            except Exception:
                logger.exception("Generating review items failed")
                fresh = ()
        try:
            due = await self.coach.due_reviews(self._clock(), limit=REVIEW_LIMIT)
        except Exception:
            logger.exception("Loading due reviews failed")
            due = ()
        seen = {item.id for item in fresh}
        items = fresh + tuple(item for item in due if item.id not in seen)
        return items[:REVIEW_LIMIT]

    async def record_review(self, item: ReviewItem, correct: bool) -> ReviewItem | None:
        if self.coach is None:
            return None
        try:
            return await self.coach.record_review(item, correct)
        except Exception:
            logger.exception("Recording review failed")
            return None
