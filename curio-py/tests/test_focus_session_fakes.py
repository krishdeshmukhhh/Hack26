"""Shared helpers for the focus-session tests (no tests here).

Sensing, policy and coach are the real F1–F3 implementations on in-memory
SQLite; only the presenter (Qt UI) is faked where a test is about routing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from curio.focus_contract import ActivitySample, ReviewItem
from curio.focus_policy import AdaptiveFocusPolicy
from curio.focus_sensing import (
    FakeActivitySource,
    RuleFirstClassifier,
    SQLiteCorrectionStore,
    ThresholdDriftTracker,
    scripted_samples,
)
from curio.focus_session import FocusRuntime, SqliteSessionStore
from curio.study_coach import EvidenceBasedCoach, SqliteReviewScheduler

T0 = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)
EXCEL = ("excel", "Book1 - Excel")
YOUTUBE = ("chrome", "Cats - YouTube - Google Chrome")
REDDIT = ("chrome", "Reddit - Google Chrome")


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


def steps(*parts, start: datetime = T0) -> list[ActivitySample]:
    """``steps(EXCEL, 30, YOUTUBE, 150)`` -> samples every 2 s (F1's scripted_samples)."""
    pairs = zip(parts[::2], parts[1::2], strict=True)
    return scripted_samples([(app, title, s) for (app, title), s in pairs], start=start)


async def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def drain(runtime: FocusRuntime) -> None:
    """Wait for everything the runtime spawned (SQLite work runs on threads)."""
    while runtime._tasks:
        await asyncio.gather(*tuple(runtime._tasks), return_exceptions=True)
    await settle()


async def feed(runtime: FocusRuntime, samples, clock: Clock) -> datetime:
    """Process samples in order with the shared clock following them."""
    for s in samples:
        clock.now = s.at
        await runtime.process(s)
        await drain(runtime)
    return clock.now


class FakePresenter:
    def __init__(self) -> None:
        self.responder = None
        self.shown = []
        self.signals = []
        self.cleared = 0

    def bind(self, responder) -> None:
        self.responder = responder

    def show(self, intervention) -> None:
        self.shown.append(intervention)

    def signal(self, signal) -> None:
        self.signals.append(signal)

    def clear(self) -> None:
        self.cleared += 1

    def kinds(self):
        return [i.kind for i in self.shown]

    def last(self, kind):
        return next(i for i in reversed(self.shown) if i.kind == kind)

    def answer(self, response, intervention=None, reply: str = "") -> None:
        self.responder(intervention or self.shown[-1], response, reply)


class Recorder(AdaptiveFocusPolicy):
    """The real policy, keeping a log of the responses it was given."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.responses = []
        self.context = []

    def record_response(self, intervention, response) -> None:
        self.responses.append((intervention, response))
        super().record_response(intervention, response)

    def set_context(self, **kw) -> None:
        self.context.append(kw)
        super().set_context(**kw)


class SpyClassifier(RuleFirstClassifier):
    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.corrections = []

    async def correct(self, s, judgment) -> None:
        self.corrections.append((s, judgment))
        await super().correct(s, judgment)


def make_runtime(clock: Clock, **overrides) -> tuple[FocusRuntime, dict]:
    """A FocusRuntime over the real F1-F3 pieces; ``parts`` also holds the stores."""
    corrections = SQLiteCorrectionStore(":memory:", clock=clock)
    scheduler = SqliteReviewScheduler(":memory:", clock=clock)
    parts = {
        "source": FakeActivitySource(),
        "classifier": SpyClassifier(corrections, clock=clock),
        "tracker": ThresholdDriftTracker(),
        "policy": Recorder(clock=clock),
        "presenter": FakePresenter(),
        "store": SqliteSessionStore(":memory:"),
        "coach": EvidenceBasedCoach(scheduler),
        "clock": clock,
    }
    parts.update(overrides)
    runtime = FocusRuntime(**parts)
    parts.update(corrections=corrections, scheduler=scheduler)
    return runtime, parts


async def close(runtime: FocusRuntime, parts: dict) -> None:
    await runtime.aclose()
    for name in ("store", "corrections", "scheduler"):
        closer = getattr(parts.get(name), "close", None)
        if closer is not None:
            await closer()


def review_item(concept: str, at: datetime, question: str = "") -> ReviewItem:
    return ReviewItem(
        concept=concept,
        question=question or f"where do you find {concept}?",
        answer=f"{concept} lives in the formulas tab",
        due_at=at,
    )
