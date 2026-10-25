"""CompanionManager records walkthrough steps and adds learned context to how-to turns."""

from __future__ import annotations

import asyncio

import pytest

from curio import companion_manager
from curio.companion_manager import CompanionManager
from curio.config import Config
from curio.learning_contract import (
    AssistanceLevel,
    ElementRef,
    PathStep,
    StepOutcome,
    TaskPath,
)
from curio.learning_events import LearningServices
from curio.state import VoiceState
from tests.test_walkthrough import (
    FakeClickWatcher,
    FakeHotkey,
    FakeLLM,
    FakeMic,
    FakeOverlays,
    FakeTranscription,
    FakeTTS,
    _ask,
    _screens,
    _settle,
)


class FakeEventLog:
    def __init__(self) -> None:
        self.events = []

    async def append(self, event) -> None:
        self.events.append(event)

    async def walkthrough(self, walkthrough_id):
        return tuple(e for e in self.events if e.walkthrough_id == walkthrough_id)

    async def recent(self, limit=200, app=None):
        return tuple(self.events[-limit:])

    async def clear(self) -> None:
        self.events.clear()


class FakeTaskMap:
    def __init__(self, path: TaskPath | None = None) -> None:
        self.path = path
        self.recorded = []
        self.finds = []
        self.merged = []

    async def record(self, summary):
        self.recorded.append(summary)
        return None

    async def find(self, app, task):
        self.finds.append((app, task))
        return self.path

    async def paths(self, app=None):
        return ()

    async def merge(self, shared):
        self.merged.extend(shared)
        return len(shared)


class FakeSkillModel:
    def __init__(self, level=AssistanceLevel.POINTED, context=None) -> None:
        self.level = level
        self.context = context
        self.observed = []
        self.asked = []

    async def observe(self, summary) -> None:
        self.observed.append(summary)

    async def snapshot(self):
        return ()

    async def recommend_assistance(self, app, concepts):
        self.asked.append((app, tuple(concepts)))
        return self.level

    async def prompt_context(self, app, concepts):
        return self.context

    async def reset(self) -> None: ...


class FakeMapSync:
    def __init__(self) -> None:
        self.pushed = []

    def step_difficulty(self, app, task, step_index):
        return None

    async def push(self, summary) -> bool:
        self.pushed.append(summary)
        return True

    async def pull(self, app=None):
        return ()


class FailingLLM(FakeLLM):
    async def send(self, messages, system, model, max_tokens=1024) -> str:
        reply = await super().send(messages, system, model, max_tokens)
        if reply == "BOOM":
            raise RuntimeError("model down")
        return reply


PIVOT_PATH = TaskPath(
    app="excel", task="insert a pivot table", verified_count=2,
    steps=(
        PathStep(index=1, instruction="click insert.", concepts=("pivot tables",),
                 element=ElementRef(label="insert tab", x=0.5, y=0.25)),
        PathStep(index=2, instruction="pick pivot table.", concepts=("pivot tables",)),
    ),
)


def _manager(replies, monkeypatch, *, task_map=None, skill_model=None, share=False,
             llm_cls=FakeLLM):
    monkeypatch.setattr(companion_manager, "WALKTHROUGH_SETTLE_SECONDS", 0)
    monkeypatch.setattr(
        companion_manager, "get_foreground_window_title", lambda: "Book1 - Excel"
    )
    config = Config(
        worker_url="", hotkey="ctrl+alt", default_model="m", log_level="INFO",
        knowledge_dir=None,
    )
    parts = {
        "hotkey": FakeHotkey(), "llm": llm_cls(replies), "tts": FakeTTS(),
        "overlays": FakeOverlays(), "clicks": FakeClickWatcher(),
        "log": FakeEventLog(), "map": task_map or FakeTaskMap(),
        "skills": skill_model or FakeSkillModel(), "sync": FakeMapSync(),
    }
    parts["learning"] = LearningServices(
        event_log=parts["log"], task_map=parts["map"], skill_model=parts["skills"],
        map_sync=parts["sync"], share_walkthroughs=share,
    )
    manager = CompanionManager(
        config=config, mic=FakeMic(), hotkey=parts["hotkey"],
        transcription=FakeTranscription(), llm=parts["llm"], tts=parts["tts"],
        screen_capture_fn=_screens, panel_visibility_controller=parts["overlays"],
        click_watcher=parts["clicks"], learning=parts["learning"],
    )
    return manager, parts


def _request_texts(parts, index: int) -> list[str]:
    content = parts["llm"].requests[index][-1]["content"]
    return [block["text"] for block in content if block["type"] == "text"]


PIVOT_REPLIES = [
    "click insert up top. [POINT:640,180:insert tab] [STEP:1/3] [CONCEPTS:Pivot Tables]",
    # The click missed: same step again, this time only a spoken hint.
    "that didn't open it. click insert again. [POINT:none] [STEP:1/3] [CONCEPTS:pivot tables]",
    "now pick pivot table. [STEP:2/3] [CONCEPTS:pivot tables, ranges] [POINT:64,72:pivot table]",
    "done, your pivot table is in a new sheet. [POINT:none]",
]


def test_full_walkthrough_records_events_and_one_summary(monkeypatch) -> None:
    manager, parts = _manager(PIVOT_REPLIES, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        for _ in range(3):
            assert manager._state == VoiceState.GUIDING
            parts["clicks"].clicked.emit()
            await _settle(manager)
        await parts["learning"].drain()

    asyncio.run(run())
    assert manager._state == VoiceState.IDLE
    events = parts["log"].events
    assert [(e.step_index, e.outcome) for e in events] == [
        (1, StepOutcome.RETRIED), (1, StepOutcome.SUCCEEDED), (2, StepOutcome.SUCCEEDED),
    ]
    assert [e.assistance for e in events] == [
        AssistanceLevel.POINTED, AssistanceLevel.HINTED, AssistanceLevel.POINTED,
    ]
    first, retry, second = events
    assert {(e.app, e.task) for e in events} == {("excel", "insert a pivot table")}
    assert len({e.walkthrough_id for e in events}) == 1
    assert first.instruction == "click insert up top."
    assert first.element == ElementRef(
        label="insert tab", x=0.5, y=0.25, window_title="Book1 - Excel"
    )
    assert retry.element is None
    assert second.concepts == ("pivot tables", "ranges")
    assert second.element.label == "pivot table"

    # Exactly one summary, fanned out to the map and skill model; sharing is off.
    assert len(parts["map"].recorded) == 1
    summary = parts["map"].recorded[0]
    assert summary.completed and summary.steps == tuple(events)
    assert parts["skills"].observed == [summary]
    assert parts["sync"].pushed == []

    # Tags are never spoken or stored.
    for text in parts["tts"].spoken:
        assert "[" not in text, text
    assert all("CONCEPTS" not in answer for _, answer in manager._history._turns)


def test_escape_abandons_and_shares_when_enabled(monkeypatch) -> None:
    manager, parts = _manager(PIVOT_REPLIES, monkeypatch, share=True)

    async def run() -> None:
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        parts["hotkey"].escape_pressed.emit()
        await parts["learning"].drain()

    asyncio.run(run())
    assert [(e.step_index, e.outcome) for e in parts["log"].events] == [
        (1, StepOutcome.ABANDONED)
    ]
    (summary,) = parts["map"].recorded
    assert not summary.completed
    assert parts["sync"].pushed == [summary]


def test_new_question_abandons(monkeypatch) -> None:
    manager, parts = _manager(PIVOT_REPLIES, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        parts["hotkey"].pressed.emit()
        parts["hotkey"].cancelled.emit()
        await parts["learning"].drain()

    asyncio.run(run())
    assert [e.outcome for e in parts["log"].events] == [StepOutcome.ABANDONED]
    assert len(parts["map"].recorded) == 1


def test_timeout(monkeypatch) -> None:
    manager, parts = _manager(PIVOT_REPLIES, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        manager._on_walkthrough_timeout()
        await parts["learning"].drain()

    asyncio.run(run())
    assert [e.outcome for e in parts["log"].events] == [StepOutcome.TIMED_OUT]
    assert manager._state == VoiceState.IDLE


def test_error_during_continuation_abandons(monkeypatch) -> None:
    manager, parts = _manager([PIVOT_REPLIES[0], "BOOM"], monkeypatch, llm_cls=FailingLLM)
    errors = []
    manager.error.connect(errors.append)

    async def run() -> None:
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        parts["clicks"].clicked.emit()
        await _settle(manager)
        await parts["learning"].drain()

    asyncio.run(run())
    assert errors == ["model down"]
    assert [e.outcome for e in parts["log"].events] == [StepOutcome.ABANDONED]
    assert manager._walkthrough is None and not parts["clicks"].active


def test_single_answer_without_step_tag_records_nothing(monkeypatch) -> None:
    manager, parts = _manager(["the save button is up top. [POINT:500,40:save]"], monkeypatch)

    async def run() -> None:
        _ask(manager, "where is save")
        await _settle(manager)
        await parts["learning"].drain()

    asyncio.run(run())
    assert parts["log"].events == [] and parts["map"].recorded == []


def test_howto_request_gets_verified_path_and_skill_line(monkeypatch) -> None:
    task_map = FakeTaskMap(PIVOT_PATH)
    skills = FakeSkillModel(AssistanceLevel.HINTED, "the user knows pivot tables from sheets.")
    manager, parts = _manager(PIVOT_REPLIES, monkeypatch, task_map=task_map, skill_model=skills)

    async def run() -> None:
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        parts["clicks"].clicked.emit()  # continuation also gets the context
        await _settle(manager)

    asyncio.run(run())
    assert task_map.finds == [("excel", "insert a pivot table")] * 2
    assert skills.asked == [("excel", ("pivot tables",))] * 2
    for index in (0, 1):
        learned = _request_texts(parts, index)[0]
        assert learned.startswith("verified path (untrusted reference data")
        # Pixel space: 0.5, 0.25 of the 1280x720 screenshot.
        assert '1. click insert. (element "insert tab" at about 640,180)' in learned
        assert "short spoken hint" in learned
        assert "the user knows pivot tables from sheets." in learned
    # Request-only: stored history keeps the plain question.
    assert manager._history._turns[0][0] == "how do i insert a pivot table"


def test_skill_line_without_path_uses_step_concepts(monkeypatch) -> None:
    skills = FakeSkillModel(AssistanceLevel.DID_IT)
    manager, parts = _manager(PIVOT_REPLIES, monkeypatch, skill_model=skills)

    async def run() -> None:
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        parts["clicks"].clicked.emit()
        await _settle(manager)

    asyncio.run(run())
    # No path and no concepts yet on the opening question: nothing added.
    assert not any("verified path" in t for t in _request_texts(parts, 0))
    assert skills.asked == [("excel", ("pivot tables",))]
    assert "point at every step" in _request_texts(parts, 1)[0]


@pytest.mark.parametrize("question", ["what is a pivot table", "where is save"])
def test_non_howto_request_has_no_learned_context(monkeypatch, question) -> None:
    task_map = FakeTaskMap(PIVOT_PATH)
    skills = FakeSkillModel(AssistanceLevel.HINTED, "knows it")
    manager, parts = _manager(["sure. [POINT:none]"], monkeypatch, task_map=task_map,
                              skill_model=skills)

    async def run() -> None:
        _ask(manager, question)
        await _settle(manager)

    asyncio.run(run())
    assert task_map.finds == [] and skills.asked == []
    texts = _request_texts(parts, 0)
    assert not any("verified path" in t or "short spoken hint" in t for t in texts)


def test_failing_learning_never_breaks_the_turn(monkeypatch) -> None:
    class BrokenMap(FakeTaskMap):
        async def find(self, app, task):
            raise RuntimeError("corrupt map")

        async def record(self, summary):
            raise RuntimeError("corrupt map")

    manager, parts = _manager(PIVOT_REPLIES, monkeypatch, task_map=BrokenMap())

    async def run() -> None:
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        parts["hotkey"].escape_pressed.emit()
        await parts["learning"].drain()

    asyncio.run(run())
    assert parts["tts"].spoken == ["click insert up top."]
    assert len(parts["skills"].observed) == 1  # the other fan-out still ran
