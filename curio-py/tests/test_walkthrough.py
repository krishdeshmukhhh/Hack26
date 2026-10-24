"""CompanionManager guided-walkthrough flow, driven with fake clients."""

from __future__ import annotations

import asyncio

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from curio import companion_manager
from curio.companion_manager import CompanionManager
from curio.config import Config
from curio.screen_capture import ScreenshotImage
from curio.state import VoiceState


class FakeMic(QObject):
    audio_level = Signal(float)
    pcm_chunk = Signal(object)

    def start(self) -> None: ...
    def stop(self) -> None: ...


class FakeHotkey(QObject):
    pressed = Signal()
    released = Signal()
    cancelled = Signal()
    escape_pressed = Signal()


class FakeTranscription(QObject):
    interim_transcript = Signal(str)
    final_transcript = Signal(str)
    error = Signal(str)

    async def start_stream(self, chunks) -> None:
        async for _ in chunks:
            pass

    async def stop_stream(self) -> None: ...


class FakeLLM(QObject):
    delta = Signal(str)
    error = Signal(str)

    def __init__(self, replies: list[str]) -> None:
        super().__init__()
        self.replies = list(replies)
        self.requests: list[list[dict]] = []

    async def send(self, messages, system, model, max_tokens=1024) -> str:
        self.requests.append(messages)
        return self.replies.pop(0)


class FakeTTS(QObject):
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.spoken: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None: ...


class FakeOverlays:
    def __init__(self) -> None:
        self.flights: list[tuple[int, int]] = []

    def hide_for_capture(self) -> None: ...
    def restore_after_capture(self) -> None: ...

    def fly_to(self, x: int, y: int) -> None:
        self.flights.append((x, y))


class FakeClickWatcher(QObject):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.active = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


def _screens() -> list[ScreenshotImage]:
    return [ScreenshotImage(b"jpeg", "screen", True, 1920, 1080, 1280, 720, 1280 / 1920, 0, 0)]


@pytest.fixture
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def _manager(replies: list[str], monkeypatch) -> tuple[CompanionManager, dict]:
    monkeypatch.setattr(companion_manager, "WALKTHROUGH_SETTLE_SECONDS", 0)
    monkeypatch.setattr(companion_manager, "get_foreground_window_title", lambda: "Explorer")
    config = Config(
        worker_url="", hotkey="ctrl+alt", default_model="m", log_level="INFO",
        knowledge_dir=None,
    )
    parts = {
        "hotkey": FakeHotkey(), "llm": FakeLLM(replies), "tts": FakeTTS(),
        "overlays": FakeOverlays(), "clicks": FakeClickWatcher(),
    }
    manager = CompanionManager(
        config=config, mic=FakeMic(), hotkey=parts["hotkey"],
        transcription=FakeTranscription(), llm=parts["llm"], tts=parts["tts"],
        screen_capture_fn=_screens, panel_visibility_controller=parts["overlays"],
        click_watcher=parts["clicks"],
    )
    parts["annotations"] = []
    manager.response_annotated.connect(lambda *a: parts["annotations"].append(a))
    parts["states"] = []
    manager.state_changed.connect(parts["states"].append)
    return manager, parts


async def _settle(manager: CompanionManager) -> None:
    """Let the current turn and its speech finish."""
    # The turn sleeps briefly and screenshots on a worker thread, so wait in
    # real time rather than just yielding.
    for _ in range(200):
        await asyncio.sleep(0.01)
        tasks = [t for t in (manager._current_task, manager._speak_task) if t is not None]
        if tasks and all(t.done() for t in tasks):
            break
    await asyncio.sleep(0.01)


def _ask(manager: CompanionManager, text: str) -> None:
    manager._set_state(VoiceState.PROCESSING)  # as after releasing the hotkey
    manager._on_final_transcript(text)


TWO_STEPS = [
    "click new in the toolbar. [POINT:40,120:new button] [STEP:1/2]",
    "now pick folder. [POINT:70,190:folder] [STEP:2/2]",
]


def test_two_step_walkthrough(qt_app, monkeypatch) -> None:
    manager, parts = _manager(TWO_STEPS, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)
        assert manager._state == VoiceState.GUIDING
        assert parts["clicks"].active
        assert parts["annotations"] == [("new button", 1, 2)]
        assert parts["tts"].spoken == ["click new in the toolbar."]

        parts["clicks"].clicked.emit()  # user did step 1
        assert manager._state == VoiceState.PROCESSING
        assert not parts["clicks"].active
        await _settle(manager)

    asyncio.run(run())
    assert parts["annotations"][-1] == ("folder", 2, 2)
    assert parts["tts"].spoken[-1] == "now pick folder."
    assert len(parts["overlays"].flights) == 2
    # Final step: no more waiting.
    assert manager._state == VoiceState.IDLE
    assert not parts["clicks"].active
    # The follow-up request carried a fresh screenshot and the continuation text.
    follow_up = parts["llm"].requests[1][-1]["content"]
    assert any(block["type"] == "image" for block in follow_up)
    request_text = follow_up[-1]["text"]
    assert request_text.startswith("i did step 1. what's next?")
    assert "[STEP:2/N]" in request_text  # per-request reminder for step 2
    # History keeps the plain text, without the reminder.
    assert manager._history._turns[1][0] == "i did step 1. what's next?"


def test_escape_ends_walkthrough(qt_app, monkeypatch) -> None:
    manager, parts = _manager(TWO_STEPS, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)
        parts["hotkey"].escape_pressed.emit()

    asyncio.run(run())
    assert manager._state == VoiceState.IDLE
    assert not parts["clicks"].active
    assert len(parts["llm"].requests) == 1


def test_new_question_ends_walkthrough(qt_app, monkeypatch) -> None:
    manager, parts = _manager(TWO_STEPS, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)
        parts["hotkey"].pressed.emit()  # Ctrl+Alt: ask something else
        assert manager._state == VoiceState.LISTENING
        assert not parts["clicks"].active
        parts["hotkey"].cancelled.emit()

    asyncio.run(run())


def test_clicks_ignored_outside_walkthrough(qt_app, monkeypatch) -> None:
    manager, parts = _manager(["html is markup. [POINT:none]"], monkeypatch)

    async def run() -> None:
        _ask(manager, "what is html")
        await _settle(manager)
        parts["clicks"].clicked.emit()

    asyncio.run(run())
    assert manager._state == VoiceState.IDLE
    assert not parts["clicks"].active
    assert parts["annotations"] == [("", 0, 0)]
    assert len(parts["llm"].requests) == 1
