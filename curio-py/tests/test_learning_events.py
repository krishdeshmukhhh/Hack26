"""Event log, recorder, null implementations and prompt context."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from curio.learning_contract import (
    AssistanceLevel,
    ElementRef,
    PathStep,
    StepEvent,
    StepOutcome,
    TaskPath,
)
from curio.learning_events import (
    NullMapSync,
    NullSkillModel,
    NullTaskMap,
    PendingStep,
    SqliteEventLog,
    WalkthroughRecorder,
    element_from_point,
)
from curio.learning_events.context import (
    assistance_line,
    format_path_for_prompt,
    learning_prompt_text,
)
from curio.point_parser import PointTag
from curio.screen_capture import ScreenshotImage


def _event(**overrides) -> StepEvent:
    values = dict(
        walkthrough_id="w1", app="excel", task="insert a pivot table", step_index=1,
        instruction="click insert.", assistance=AssistanceLevel.POINTED,
        outcome=StepOutcome.SUCCEEDED,
        element=ElementRef(label="insert tab", x=0.1, y=0.05, window_title="Book1 - Excel"),
        concepts=("pivot tables",),
    )
    values.update(overrides)
    return StepEvent(**values)


def test_event_log_round_trip(tmp_path) -> None:
    log = SqliteEventLog(tmp_path / "nested" / "events.sqlite3")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first = _event(occurred_at=start)
    second = _event(
        step_index=2, element=None, concepts=(), outcome=StepOutcome.RETRIED,
        assistance=AssistanceLevel.HINTED, occurred_at=start + timedelta(seconds=5),
    )
    other = _event(walkthrough_id="w2", app="figma", occurred_at=start + timedelta(seconds=9))

    async def run() -> None:
        for event in (first, second, other):
            await log.append(event)
        assert await log.walkthrough("w1") == (first, second)
        assert await log.recent() == (other, second, first)
        assert await log.recent(limit=1) == (other,)
        assert await log.recent(app="excel") == (second, first)
        await log.clear()
        assert await log.recent() == ()
        # Reopening an existing file keeps working.
        await SqliteEventLog(log.path).append(first)
        assert await log.walkthrough("w1") == (first,)

    asyncio.run(run())


def test_event_log_rejects_duplicate_ids(tmp_path) -> None:
    log = SqliteEventLog(tmp_path / "events.sqlite3")
    event = _event()

    async def run() -> None:
        await log.append(event)
        with pytest.raises(Exception):  # noqa: B017
            await log.append(event)

    asyncio.run(run())


def _step(index: int, **overrides) -> PendingStep:
    values = dict(step_index=index, instruction=f"step {index}", assistance=AssistanceLevel.POINTED)
    values.update(overrides)
    return PendingStep(**values)


def test_recorder_settles_each_step_on_the_next_answer() -> None:
    rec = WalkthroughRecorder(app="excel", task="insert a pivot table")
    assert rec.step_answered(_step(1)) is None
    retried = rec.step_answered(_step(1, instruction="try again"))
    assert (retried.step_index, retried.outcome) == (1, StepOutcome.RETRIED)
    ok = rec.step_answered(_step(2))
    assert (ok.step_index, ok.instruction, ok.outcome) == (1, "try again", StepOutcome.SUCCEEDED)
    last, summary = rec.finish(StepOutcome.SUCCEEDED, completed=True)
    assert (last.step_index, last.outcome) == (2, StepOutcome.SUCCEEDED)
    assert summary.completed
    assert summary.walkthrough_id == rec.walkthrough_id
    assert [s.outcome for s in summary.steps] == [
        StepOutcome.RETRIED, StepOutcome.SUCCEEDED, StepOutcome.SUCCEEDED
    ]
    assert {s.walkthrough_id for s in summary.steps} == {rec.walkthrough_id}
    assert {(s.app, s.task) for s in summary.steps} == {("excel", "insert a pivot table")}


def test_recorder_abandon() -> None:
    rec = WalkthroughRecorder(app="excel", task="t")
    rec.step_answered(_step(1))
    last, summary = rec.finish(StepOutcome.ABANDONED, completed=False)
    assert last.outcome == StepOutcome.ABANDONED
    assert not summary.completed and len(summary.steps) == 1


def _shot(width=1280, height=720) -> ScreenshotImage:
    return ScreenshotImage(b"", "s", True, 1920, 1080, width, height, width / 1920, 0, 0)


def test_element_from_point() -> None:
    tag = PointTag(640, 180, "insert tab")
    assert element_from_point(tag, [_shot()], "pixel", "Book1 - Excel") == ElementRef(
        label="insert tab", x=0.5, y=0.25, window_title="Book1 - Excel"
    )
    assert element_from_point(tag, [_shot()], "norm1000") == ElementRef(
        label="insert tab", x=0.64, y=0.18
    )
    # Second screen, and out-of-range coordinates clamp to the image.
    far = PointTag(2000, 100, "x", screen=2)
    assert element_from_point(far, [_shot(), _shot(1000, 500)], "pixel").x == 1.0
    assert element_from_point(tag, [], "pixel") is None


def test_null_implementations() -> None:
    async def run() -> None:
        assert await NullTaskMap().find("excel", "t") is None
        assert await NullTaskMap().paths() == ()
        assert await NullTaskMap().merge([]) == 0
        model = NullSkillModel()
        assert await model.recommend_assistance("excel", ["x"]) == AssistanceLevel.POINTED
        assert await model.prompt_context("excel", ["x"]) is None
        assert await model.snapshot() == ()
        sync = NullMapSync()
        assert sync.step_difficulty("excel", "t", 1) is None
        assert await sync.pull() == ()

    asyncio.run(run())


PATH = TaskPath(
    app="excel", task="insert a pivot table", verified_count=3,
    steps=(
        PathStep(index=2, instruction="pick pivot table.",
                 element=ElementRef(label="pivot table", x=0.05, y=0.1), difficulty=0.7),
        PathStep(index=1, instruction="click insert.",
                 element=ElementRef(label="insert tab", x=0.5, y=0.25)),
    ),
)


def test_format_path_converts_to_active_coordinates() -> None:
    norm = format_path_for_prompt(PATH, point_coords="norm1000", image_size=(1280, 720))
    lines = norm.splitlines()
    assert "untrusted reference data" in lines[0] and "3 other users" in lines[0]
    assert "trust the screen" in lines[0]
    assert lines[1] == '1. click insert. (element "insert tab" at about 500,250)'
    assert lines[2].startswith('2. pick pivot table. (element "pivot table" at about 50,100)')
    assert "get stuck" in lines[2]
    pixel = format_path_for_prompt(
        PATH, point_coords="pixel", image_size=(1280, 720), difficulty=lambda i: 0.9
    )
    assert "at about 640,180)" in pixel
    assert pixel.count("get stuck") == 2  # crowd difficulty fills the unknown step


def test_assistance_lines() -> None:
    assert "short spoken hint" in assistance_line(AssistanceLevel.HINTED)
    assert assistance_line(AssistanceLevel.NONE) == assistance_line(AssistanceLevel.HINTED)
    assert assistance_line(AssistanceLevel.POINTED) is None
    assert "point at every step" in assistance_line(AssistanceLevel.DID_IT)
    assert learning_prompt_text(
        path_text=None, assistance=AssistanceLevel.POINTED, skill_context=None
    ) is None
