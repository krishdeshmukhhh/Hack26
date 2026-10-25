"""One owner for a focus session: sensing -> policy -> presenter, and back.

Wires ActivitySource -> TrackClassifier -> DriftTracker -> FocusPolicy and
hands each Intervention to a presenter. Responses come back through
``respond``: every policy card's response goes to the policy, and "not a
distraction" also corrects the classifier. Samples are processed in order on
one asyncio task, so a slow model judgment never reorders the timeline.
Construct and use on the Qt/qasync thread; ``aclose()`` awaits everything it
started. The policy lives as long as the app (it learns about the learner
across sessions); the runtime calls ``start_session`` on it for each plan.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from curio.focus_session.presenter import ANSWER_CHOICE
from curio.focus_session.timeline import SessionTimeline, TimelineState
from curio.learning_contract import concept_key

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
# (intervention, response, reply): reply is the chosen label or a spoken answer.
Responder = Callable[[Intervention, InterventionResponse, str], None]
# (concepts, context notes) -> new review items; F3's generate_review_items, bound.
ReviewGenerator = Callable[[Sequence[str], str], Awaitable[Sequence[ReviewItem]]]

REVIEW_LIMIT = 3
REVIEW_OFFER_CHOICES = ("start review", "not now")
SPOKEN_KINDS = frozenset(set(InterventionKind) - {InterventionKind.AMBIENT_CUE})
# Drift nudges may be reworded by the model (up to the policy's short timeout);
# planning, break and reflection prompts are shown straight away from templates.
REPHRASED_KINDS = frozenset(
    {InterventionKind.CHECK_IN, InterventionKind.PLAN_REMINDER, InterventionKind.RESUME}
)


class Presenter(Protocol):
    """Shows interventions and pet reactions; reports answers to the responder."""

    def bind(self, responder: Responder) -> None: ...

    def show(self, intervention: Intervention) -> None: ...

    def signal(self, signal: FocusSignal) -> None: ...

    def clear(self) -> None: ...


class SessionPolicy(FocusPolicy, Protocol):
    """The contract's FocusPolicy plus the session hooks F2's policy provides."""

    def start_session(self, plan: FocusPlan) -> Intervention: ...

    def reflection_prompt(self, plan: FocusPlan) -> Intervention: ...

    def set_context(self, *, where: str, next_action: str = "", source: str = "") -> None: ...

    def begin_break(self) -> None: ...

    async def rephrase(self, intervention: Intervention) -> Intervention: ...


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
    own: bool = False  # built by the runtime (review offer), not by the policy


class FocusRuntime(QObject):
    session_started = Signal(object)  # FocusPlan
    timeline_changed = Signal()
    intervention_shown = Signal(object)  # Intervention
    session_ended = Signal(object)  # SessionSummary
    review_requested = Signal(object)  # tuple[ReviewItem, ...] due from earlier sessions
    error = Signal(str)

    def __init__(
        self,
        *,
        source: ActivitySource,
        classifier: TrackClassifier,
        tracker: DriftTracker,
        policy: SessionPolicy,
        presenter: Presenter,
        coach: StudyCoach | None = None,
        store: SessionStore | None = None,
        generate_reviews: ReviewGenerator | None = None,
        model_call: ModelCall | None = None,
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
        self._clock = clock
        self.plan: FocusPlan | None = None
        self.timeline: SessionTimeline | None = None
        self._queue: asyncio.Queue[ActivitySample] | None = None
        self._worker: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._unsubscribe: Unsubscribe | None = None
        self._tasks: set[asyncio.Task] = set()
        self._present_lock = asyncio.Lock()
        self._pending: dict[str, _Pending] = {}
        self._deferred: list[Intervention] = []
        self._last_sample: ActivitySample | None = None
        self._drifting = False
        self._in_break = False
        self._break_until: datetime | None = None
        self._drift_apps: list[str] = []
        self._concepts: dict[str, None] = {}
        self._notes: list[str] = []
        self._interventions = 0
        self._false_alarms = 0
        self._start_prompt_id: str | None = None
        self._ending_prompt_id: str | None = None
        self._reflection = ""
        self._due: tuple[ReviewItem, ...] = ()
        self._ending = False
        self._closed = False
        presenter.bind(self.respond)

    # --- lifecycle --------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.plan is not None and not self._ending

    @property
    def on_break(self) -> bool:
        return self._in_break

    def start(self, plan: FocusPlan) -> None:
        if self._closed:
            raise RuntimeError("Focus runtime is closed")
        if self.plan is not None:
            raise RuntimeError("A focus session is already running")
        self._loop = asyncio.get_running_loop()
        self._reset(plan)
        self.tracker.reset(plan)
        opening = self.policy.start_session(plan)
        self._queue = asyncio.Queue()
        self._worker = self._loop.create_task(self._work(self._queue))
        self._unsubscribe = self.source.subscribe(self._on_sample)
        self.source.start()
        self.session_started.emit(plan)
        self.timeline_changed.emit()
        self._start_prompt_id = opening.id
        self._deliver(opening, None)
        if self.coach is not None:
            self._spawn(self._offer_due_reviews(plan))

    def _reset(self, plan: FocusPlan) -> None:
        self.plan = plan
        self.timeline = SessionTimeline(plan.started_at)
        self._pending.clear()
        self._deferred.clear()
        self._last_sample = None
        self._drifting = self._in_break = self._ending = False
        self._break_until = None
        self._drift_apps = []
        self._concepts = dict.fromkeys(plan.concepts)
        self._notes = []
        self._interventions = self._false_alarms = 0
        self._start_prompt_id = self._ending_prompt_id = None
        self._reflection = ""
        self._due = ()

    async def _detach(self, *, drain: bool) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self.source.stop()
        worker, self._worker = self._worker, None
        if worker is not None and worker is not asyncio.current_task():
            if drain and self._queue is not None:
                await self._queue.join()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        self.presenter.clear()
        self._deferred.clear()
        for pending in tuple(self._pending.values()):
            if not pending.own:
                self.policy.record_response(pending.intervention, InterventionResponse.IGNORED)
        self._pending.clear()
        if self.coach is not None and hasattr(self.coach, "reset"):
            self.coach.reset()

    async def end(self) -> SessionSummary | None:
        """Stop sensing, process queued samples, then save and emit the summary."""
        if self.plan is None or self._ending:
            return None
        self._ending = True
        await self._detach(drain=True)
        summary = self.summary(self._reflection)
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
        if self.active:
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

    def set_context(self, *, where: str, next_action: str = "", source: str = "walkthrough"):
        """Latest "where you are / what's next"; the policy turns it into resume notes."""
        if self.active:
            self.policy.set_context(where=where, next_action=next_action, source=source)

    def note_concepts(self, concepts: Sequence[str], context: str = "") -> None:
        """Concepts practised this session (from tutoring or walkthrough steps)."""
        for concept in concepts:
            if key := concept_key(concept):
                self._concepts[key] = None
        if context.strip() and len(self._notes) < 40:
            self._notes.append(" ".join(context.split())[:300])

    def take_break(self) -> None:
        """The learner chose a break some other way (voice or tray)."""
        if self.active and not self._in_break:
            self.policy.begin_break()
            self._start_break(self._clock())

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
        if plan is None or timeline is None or self._ending:
            return
        if sample.at > plan.started_at + plan.duration:
            self.request_end()  # the time box is over; later samples don't count
            return
        assessment = await self.classifier.assess(sample, plan)
        if self.plan is not plan or self._ending:
            return
        self._last_sample = sample
        timeline.observe(sample.at)
        signals = list(self.tracker.update(sample, assessment))
        if (
            self._in_break
            and self._break_until is not None
            and sample.at >= self._break_until
            and not any(s.kind == SignalKind.BREAK_OVER for s in signals)
        ):
            # A break the learner chose themselves ends after the plan's break length.
            signals.append(FocusSignal(kind=SignalKind.BREAK_OVER, sample=sample, at=sample.at))
        for signal in signals:
            self._handle_signal(signal, plan, timeline)
        if assessment.judgment == TrackJudgment.ON_BREAK or self._in_break:
            state = TimelineState.BREAK
        elif self._drifting:
            state = TimelineState.DRIFTING
        else:
            state = TimelineState.ON_GOAL
        timeline.set_state(state, sample.at)
        self.timeline_changed.emit()
        if sample.at >= plan.started_at + plan.duration:
            self.request_end()

    def _handle_signal(self, signal: FocusSignal, plan: FocusPlan, timeline) -> None:
        if signal.kind == SignalKind.DRIFT_STARTED and not self._drifting:
            self._drifting = True
            timeline.drift_started(signal.at, signal.drift_seconds)
            sample = signal.sample or self._last_sample
            if sample is not None and sample.app:
                self._drift_apps.append(sample.app)
        elif signal.kind == SignalKind.RETURNED:
            self._drifting = False
            timeline.set_state(TimelineState.ON_GOAL, signal.at)
        elif signal.kind == SignalKind.BREAK_OVER:
            self._in_break = False
            self._break_until = None
        self.presenter.signal(signal)
        intervention = self.policy.decide(signal, plan)
        if intervention is None:
            return
        if signal.kind == SignalKind.SESSION_ENDING:
            self._ending_prompt_id = intervention.id
        self._deliver(intervention, signal.sample or self._last_sample)

    def _start_break(self, at: datetime) -> None:
        self._in_break = True
        self._drifting = False
        if self.plan is not None:
            self._break_until = at + timedelta(minutes=max(1, self.plan.break_minutes))
        if self.timeline is not None:
            self.timeline.set_state(TimelineState.BREAK, at)
            self.timeline_changed.emit()

    # --- presenting ---------------------------------------------------------------

    def _deliver(self, intervention: Intervention, sample: ActivitySample | None, *,
                 own: bool = False) -> None:
        self._interventions += 1
        if intervention.kind == InterventionKind.BREAK_END:
            self._in_break = False
            self._break_until = None
        if intervention.kind != InterventionKind.AMBIENT_CUE:
            self._pending[intervention.id] = _Pending(intervention, sample, own)
        self._spawn(self._present(intervention))

    async def _present(self, intervention: Intervention) -> None:
        async with self._present_lock:
            spoken = intervention.kind in SPOKEN_KINDS
            if not self.active or (spoken and intervention.id not in self._pending):
                return
            if intervention.kind in REPHRASED_KINDS and intervention.id not in self._own_ids():
                try:
                    intervention = await self.policy.rephrase(intervention)
                except Exception:
                    logger.exception("Rephrasing a focus card failed")
                if not self.active or intervention.id not in self._pending:
                    return
                self._pending[intervention.id].intervention = intervention
            self.intervention_shown.emit(intervention)
            self.presenter.show(intervention)

    def _own_ids(self) -> set[str]:
        return {key for key, pending in self._pending.items() if pending.own}

    def _offer(self, intervention: Intervention) -> None:
        """Show a runtime card once nothing else is waiting for an answer."""
        if self._pending:
            self._deferred.append(intervention)
        else:
            self._deliver(intervention, None, own=True)

    def _next_deferred(self) -> None:
        if self._deferred and not self._pending and self.active:
            self._deliver(self._deferred.pop(0), None, own=True)

    async def _offer_due_reviews(self, plan: FocusPlan) -> None:
        """Spaced review from earlier sessions, offered at the start (section G)."""
        try:
            due = tuple(await self.coach.due_reviews(self._clock(), limit=REVIEW_LIMIT))
        except Exception:
            logger.exception("Loading due reviews failed")
            return
        if not due or self.plan is not plan or not self.active:
            return
        self._due = due
        count = len(due)
        self._offer(
            Intervention(
                kind=InterventionKind.REVIEW,
                message=(
                    f"there {'is' if count == 1 else 'are'} {count} review "
                    f"question{'' if count == 1 else 's'} from last time. "
                    "want to do them before you start?"
                ),
                choices=REVIEW_OFFER_CHOICES,
                rationale="G",
                expires_after=timedelta(seconds=60),
                at=self._clock(),
            )
        )

    # --- responses ------------------------------------------------------------

    def respond(
        self, intervention: Intervention, response: InterventionResponse, reply: str = ""
    ) -> None:
        """Called by the presenter once per intervention (choice, voice or expiry)."""
        pending = self._pending.pop(intervention.id, None)
        if pending is None:
            return
        kind = intervention.kind
        if not pending.own:
            self.policy.record_response(intervention, response)
        answer = reply if reply and reply.lower() != ANSWER_CHOICE else ""
        if response == InterventionResponse.FALSE_ALARM:
            self._false_alarm(pending)
        elif response == InterventionResponse.ACCEPTED:
            if kind == InterventionKind.BREAK_START:
                self._start_break(self._clock())  # the policy begins its own break
            elif kind in (InterventionKind.CHECK_IN, InterventionKind.PLAN_REMINDER) and (
                "break" in reply.lower()
            ):
                self.take_break()
            elif kind == InterventionKind.METACOGNITIVE and answer and self.plan is not None:
                if intervention.id == self._start_prompt_id:
                    # "What's the first thing you'll do?" doubles as the first resume note.
                    self.policy.set_resume_note(
                        ResumeNote(where=self.plan.goal, next_action=answer, source="spoken",
                                   at=self._clock())
                    )
            elif kind == InterventionKind.REFLECTION:
                self._reflection = answer or self._reflection
                self.request_end()
            elif kind == InterventionKind.REVIEW and pending.own:
                self.review_requested.emit(self._due)
        if intervention.id == self._ending_prompt_id and self.active and self.plan is not None:
            self._ending_prompt_id = None
            self._deliver(self.policy.reflection_prompt(self.plan), self._last_sample)
        self._next_deferred()

    def _false_alarm(self, pending: _Pending) -> None:
        self._false_alarms += 1
        if self.timeline is not None and self._drifting and self.timeline.unmark_latest_drift():
            self._drifting = False
            if self._drift_apps:
                self._drift_apps.pop()
            self.timeline_changed.emit()
        sample = pending.sample or self._last_sample
        if sample is not None:
            self._spawn(self._correct(sample))

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

    async def due_reviews(self) -> tuple[ReviewItem, ...]:
        """Items due now, for a review outside the end-of-session card."""
        if self.coach is None:
            return ()
        try:
            return tuple(await self.coach.due_reviews(self._clock(), limit=REVIEW_LIMIT))
        except Exception:
            logger.exception("Loading due reviews failed")
            return ()

    async def record_review(self, item: ReviewItem, correct: bool) -> ReviewItem | None:
        if self.coach is None:
            return None
        try:
            return await self.coach.record_review(item, correct)
        except Exception:
            logger.exception("Recording review failed")
            return None
