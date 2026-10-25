"""Fakes of the F1–F3 protocols shared by the focus-session tests (no tests here)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from curio.focus_contract import (
    ActivitySample,
    FocusSignal,
    Intervention,
    InterventionKind,
    InterventionResponse,
    JudgmentSource,
    ResumeNote,
    ReviewItem,
    SignalKind,
    TrackAssessment,
    TrackJudgment,
)

T0 = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


def sample(app: str, at: datetime, *, title: str = "", switch: bool = False) -> ActivitySample:
    return ActivitySample(
        app=app,
        window_title=title or f"Thing - {app}",
        idle_seconds=0.0,
        input_events=3,
        is_switch=switch,
        at=at,
    )


class FakeSource:
    def __init__(self) -> None:
        self.started = self.stopped = 0
        self.callbacks: list = []

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def subscribe(self, callback):
        self.callbacks.append(callback)
        return lambda: self.callbacks.remove(callback)

    def emit(self, s: ActivitySample) -> None:
        for callback in tuple(self.callbacks):
            callback(s)


class FakeClassifier:
    """Off goal for listed apps, unless the learner corrected it."""

    def __init__(self, off_goal=("youtube",), on_break=()) -> None:
        self.off_goal = set(off_goal)
        self.on_break = set(on_break)
        self.corrections: list[tuple[ActivitySample, TrackJudgment]] = []

    async def assess(self, s, plan) -> TrackAssessment:
        if any(c.app == s.app for c, _ in self.corrections):
            return TrackAssessment(
                judgment=TrackJudgment.ON_GOAL, confidence=1.0, source=JudgmentSource.USER
            )
        if s.app in self.on_break:
            judgment = TrackJudgment.ON_BREAK
        elif s.app in self.off_goal:
            judgment = TrackJudgment.OFF_GOAL
        else:
            judgment = TrackJudgment.ON_GOAL
        return TrackAssessment(judgment=judgment, confidence=0.9, source=JudgmentSource.RULE)

    async def correct(self, s, judgment) -> None:
        self.corrections.append((s, judgment))


class FakeTracker:
    """DRIFT_STARTED after ``threshold`` seconds off goal; RETURNED when back.

    Every switch is also a BREAKPOINT. Extra scripted signals can be queued.
    """

    def __init__(self, threshold: float = 90.0) -> None:
        self.threshold = threshold
        self.plan = None
        self._off_since: datetime | None = None
        self._drifting = False
        self.queued: list[FocusSignal] = []

    def reset(self, plan) -> None:
        self.plan = plan
        self._off_since = None
        self._drifting = False

    def update(self, s, assessment):
        signals = list(self.queued)
        self.queued.clear()
        if s.is_switch:
            signals.append(FocusSignal(kind=SignalKind.BREAKPOINT, sample=s, at=s.at))
        if assessment.judgment == TrackJudgment.OFF_GOAL:
            self._off_since = self._off_since or s.at
            off = (s.at - self._off_since).total_seconds()
            if not self._drifting and off >= self.threshold:
                self._drifting = True
                signals.append(FocusSignal(
                    kind=SignalKind.DRIFT_STARTED, sample=s, assessment=assessment,
                    drift_seconds=off, at=s.at,
                ))
        else:
            if self._drifting:
                off = (s.at - self._off_since).total_seconds()
                signals.append(FocusSignal(
                    kind=SignalKind.RETURNED, sample=s, drift_seconds=off, at=s.at
                ))
            self._off_since = None
            self._drifting = False
        return signals


class FakePolicy:
    """CHECK_IN on drift, RESUME on return, BREAK_START/END for break signals."""

    def __init__(self) -> None:
        self.responses: list[tuple[Intervention, InterventionResponse]] = []
        self.notes: list[ResumeNote] = []
        self.decided: list[FocusSignal] = []

    def decide(self, signal, plan):
        self.decided.append(signal)
        kinds = {
            SignalKind.DRIFT_STARTED: (
                InterventionKind.CHECK_IN,
                f"still on {plan.goal}? we could get back to it, or take a real break.",
                ("back to it", "take a break", "not a distraction"),
            ),
            SignalKind.RETURNED: (
                InterventionKind.RESUME, "you were about to add the row fields.", ("thanks",)
            ),
            SignalKind.BREAK_DUE: (
                InterventionKind.BREAK_START, "time for a five-minute break, want to stretch?",
                ("start break", "keep going"),
            ),
            SignalKind.BREAK_OVER: (
                InterventionKind.BREAK_END, "break's over. want to pick it back up?", ("ready",)
            ),
        }
        if signal.kind not in kinds:
            return None
        kind, message, choices = kinds[signal.kind]
        return Intervention(
            kind=kind, message=message, choices=choices, rationale="C", at=signal.at
        )

    def record_response(self, intervention, response) -> None:
        self.responses.append((intervention, response))

    def resume_note(self):
        return self.notes[-1] if self.notes else None

    def set_resume_note(self, note) -> None:
        self.notes.append(note)


class FakePresenter:
    def __init__(self) -> None:
        self.responder = None
        self.shown: list[Intervention] = []
        self.signals: list[FocusSignal] = []
        self.cleared = 0

    def bind(self, responder) -> None:
        self.responder = responder

    def show(self, intervention) -> None:
        self.shown.append(intervention)

    def signal(self, signal) -> None:
        self.signals.append(signal)

    def clear(self) -> None:
        self.cleared += 1

    def answer(self, response: InterventionResponse, index: int = -1) -> None:
        self.responder(self.shown[index], response)


class FakeCoach:
    def __init__(self, due=()) -> None:
        self.due = list(due)
        self.added: list[ReviewItem] = []
        self.recorded: list[tuple[ReviewItem, bool]] = []

    def next_move(self, event, mastery=None):
        raise NotImplementedError

    async def due_reviews(self, now, limit=3):
        return tuple(i for i in self.due if i.due_at <= now)[:limit]

    async def record_review(self, item, correct):
        self.recorded.append((item, correct))
        days = item.interval_days * 2.5 if correct else 1.0
        return replace(
            item, interval_days=days, due_at=item.due_at + timedelta(days=days),
            repetitions=item.repetitions + 1,
        )

    async def add_review_items(self, items) -> None:
        self.added.extend(items)


class FakeStore:
    def __init__(self) -> None:
        self.saved = []

    async def save_summary(self, summary) -> None:
        self.saved = [s for s in self.saved if s.plan_id != summary.plan_id] + [summary]

    async def summaries(self, limit=50):
        return tuple(reversed(self.saved))[:limit]

    async def clear(self) -> None:
        self.saved.clear()


def review_item(concept: str, at: datetime, question: str = "") -> ReviewItem:
    return ReviewItem(
        concept=concept,
        question=question or f"where do you find {concept}?",
        answer=f"{concept} lives in the formulas tab",
        due_at=at,
    )
