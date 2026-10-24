"""Classroom lab mode: tracker, server room, HTTP round trip and hint delivery."""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest

from curio import companion_manager
from curio.clients.lab_client import LabClient
from curio.companion_manager import CompanionManager
from curio.config import Config
from curio.lab import (
    LabHint,
    LabSettings,
    LabStep,
    LabTracker,
    asks_for_human,
    parse_lab_tag,
)
from curio.lab_server import LabDefinition, LabRequestError, LabRoom, LabServer
from curio.point_parser import strip_tags_for_display
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

STEPS = (LabStep(1, "Open MATLAB"), LabStep(2, "Load the data"), LabStep(3, "Plot v against t"))
LAB = LabDefinition("Lab 3", STEPS, code="PLOT3", instructor_key="secret")


# ---------------------------------------------------------------------------
# Settings, tags and the student's tracker
# ---------------------------------------------------------------------------


def test_settings_validation() -> None:
    assert LabSettings.from_dict({}) == LabSettings()
    settings = LabSettings.from_dict(
        {"enabled": True, "server_url": "http://10.0.0.5:8765/", "code": " PLOT3 "}
    )
    assert settings.server_url == "http://10.0.0.5:8765"
    assert settings.code == "PLOT3"
    with pytest.raises(ValueError, match="server_url"):
        LabSettings.from_dict({"enabled": True, "server_url": "10.0.0.5", "code": "X"})
    with pytest.raises(ValueError, match="code"):
        LabSettings.from_dict({"enabled": True, "server_url": "http://x"})
    with pytest.raises(ValueError, match="stuck_after_questions"):
        LabSettings.from_dict({"stuck_after_questions": 0})


def test_config_reads_lab_section(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'backend = "local"\n[lab]\nenabled = true\nserver_url = "http://lab:8765"\ncode = "A1"\n'
    )
    assert Config.from_path(path).lab.code == "A1"


def test_lab_tag_is_parsed_and_hidden() -> None:
    text, step = parse_lab_tag("click the import button. [LAB:2] [POINT:10,20:import]")
    assert step == 2
    assert text == "click the import button. [POINT:10,20:import]"
    assert parse_lab_tag("no tag here") == ("no tag here", None)
    assert strip_tags_for_display("over here [LAB:2] [POINT:1,2:x]") == "over here"
    assert strip_tags_for_display("over here [LAB:") == "over here"


def test_asks_for_human() -> None:
    assert asks_for_human("i'm stuck on this plot")
    assert asks_for_human("can you get the TA")
    assert not asks_for_human("where's the run button")


def test_tracker_marks_stuck_after_repeated_questions() -> None:
    changes = []
    tracker = LabTracker(stuck_after_questions=3, on_change=lambda: changes.append(1))
    tracker.set_lab("Lab 3", STEPS)
    tracker.record_turn("where's the run button", 3, is_question=True)
    tracker.record_turn("what does this error mean", None, is_question=True)
    assert (tracker.step, tracker.stuck) == (3, False)
    # Walkthrough continuations aren't the student asking.
    tracker.record_turn("i did step 1. what's next?", None, is_question=False)
    assert not tracker.stuck
    tracker.record_turn("why is my plot empty", None, is_question=True)
    assert tracker.stuck
    # Moving on clears it.
    tracker.record_turn("ok what now", 2, is_question=False)
    assert (tracker.step, tracker.stuck) == (2, False)
    assert changes


def test_tracker_asking_for_ta_is_stuck_at_once_and_ignores_bad_steps() -> None:
    tracker = LabTracker()
    tracker.set_lab("Lab 3", STEPS)
    tracker.record_turn("i'm lost", 9, is_question=True)  # step 9 doesn't exist
    assert (tracker.step, tracker.stuck) == (0, True)


def test_tracker_prompt_lists_steps_and_hint_relevance() -> None:
    tracker = LabTracker()
    assert tracker.prompt_context() is None
    tracker.set_lab("Lab 3", STEPS)
    tracker.set_step(2)
    prompt = tracker.prompt_context()
    assert "3. Plot v against t" in prompt
    assert "[LAB:k]" in prompt
    assert "step 2" in prompt
    assert tracker.wants_hint(LabHint(1, 2, "x"))
    assert not tracker.wants_hint(LabHint(1, 3, "x"))


# ---------------------------------------------------------------------------
# Server room
# ---------------------------------------------------------------------------


def _check_in(room: LabRoom, student: str, step: int, stuck: bool, now: float = 0.0, since=0):
    return room.check_in(
        {"code": "plot3", "student": student, "step": step, "stuck": stuck, "since": since}, now
    )


def test_dashboard_shows_only_counts() -> None:
    room = LabRoom(LAB)
    for i in range(8):
        _check_in(room, f"s{i}", 3, stuck=True)
    _check_in(room, "a", 3, stuck=False)
    _check_in(room, "b", 1, stuck=False)
    _check_in(room, "c", 0, stuck=False)
    board = room.dashboard(1.0)
    assert board["students"] == 11
    assert board["stuck"] == 8
    rows = {row["index"]: row for row in board["rows"]}
    assert (rows[3]["stuck"], rows[3]["working"]) == (8, 1)
    assert rows[0]["title"] == "Step not known yet"
    # No student ids anywhere in what the TA sees.
    assert "s0" not in repr(board)


def test_hint_reaches_only_students_stuck_on_that_step() -> None:
    room = LabRoom(LAB)
    _check_in(room, "stuck3", 3, stuck=True)
    _check_in(room, "fine3", 3, stuck=False)
    _check_in(room, "stuck1", 1, stuck=True)
    sent = room.add_hint({"step": 3, "text": "save before running", "target": "run button"}, 1)
    assert sent == {"id": 1, "recipients": 1}

    assert _check_in(room, "stuck3", 3, True, now=2)["hints"] == [
        {"id": 1, "step": 3, "text": "save before running", "target": "run button"}
    ]
    assert _check_in(room, "stuck3", 3, True, now=3, since=1)["hints"] == []
    assert _check_in(room, "fine3", 3, False, now=2)["hints"] == []
    assert _check_in(room, "stuck1", 1, True, now=2)["hints"] == []
    hint = room.dashboard(4)["hints"][0]
    assert (hint["recipients"], hint["delivered"]) == (1, 1)

    everyone = room.add_hint({"step": 3, "text": "check units", "audience": "step"}, 5)
    assert everyone["recipients"] == 2


def test_room_rejects_bad_requests_and_forgets_stale_students() -> None:
    room = LabRoom(LAB, stale_after=10)
    with pytest.raises(PermissionError):
        room.check_in({"code": "nope", "student": "x"}, 0)
    with pytest.raises(LabRequestError):
        _check_in(room, "x", 7, stuck=False)
    with pytest.raises(LabRequestError):
        room.add_hint({"step": 1, "text": "   "}, 0)
    _check_in(room, "x", 1, stuck=True, now=0)
    assert room.dashboard(5)["students"] == 1
    assert room.dashboard(11)["students"] == 0


def test_definition_needs_steps() -> None:
    with pytest.raises(ValueError, match="steps"):
        LabDefinition.from_dict({"name": "Empty"})
    lab = LabDefinition.from_dict({"steps": [{"title": "One"}, "Two"]})
    assert [s.title for s in lab.steps] == ["One", "Two"]
    assert lab.code and lab.instructor_key


# ---------------------------------------------------------------------------
# HTTP: real server, real client
# ---------------------------------------------------------------------------


@pytest.fixture
def lab_server():
    server = LabServer(("127.0.0.1", 0), LabRoom(LAB))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_client_checks_in_and_receives_hint(qt_app, lab_server) -> None:
    client = LabClient(LabSettings(enabled=True, server_url=lab_server, code="PLOT3"))
    hints: list[LabHint] = []
    client.hint_received.connect(hints.append)

    async def run() -> None:
        async with httpx.AsyncClient() as http:
            await client.check_in(http)
            assert client.connected
            assert [s.title for s in client.tracker.steps] == [s.title for s in STEPS]

            client.tracker.set_step(3)
            client.tracker.set_stuck(True)
            await client.check_in(http)

            # The TA's dashboard: key required, counts only.
            assert (await http.get(f"{lab_server}/api/dashboard")).status_code == 403
            board = (
                await http.get(f"{lab_server}/api/dashboard", headers={"X-Lab-Key": "secret"})
            ).json()
            assert board["rows"][-1] == {
                "index": 3, "title": "Plot v against t", "working": 0, "stuck": 1
            }
            sent = await http.post(
                f"{lab_server}/api/hints",
                headers={"X-Lab-Key": "secret"},
                json={"step": 3, "text": "press Run", "target": "the run button"},
            )
            assert sent.json()["recipients"] == 1

            await client.check_in(http)
            await client.check_in(http)  # no duplicate delivery

            page = await http.get(f"{lab_server}/")
            assert "Curio Lab" in page.text

    asyncio.run(run())
    assert hints == [LabHint(1, 3, "press Run", "the run button")]


def test_client_reports_wrong_code(qt_app, lab_server) -> None:
    client = LabClient(LabSettings(enabled=True, server_url=lab_server, code="WRONG"))

    async def run() -> None:
        async with httpx.AsyncClient() as http:
            with pytest.raises(RuntimeError, match="wrong lab code"):
                await client.check_in(http)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# CompanionManager: lab prompt, [LAB:k] tags and hint delivery
# ---------------------------------------------------------------------------


class CaptionOverlays(FakeOverlays):
    def __init__(self) -> None:
        super().__init__()
        self.captions: list[str | None] = []

    def fly_to(self, x, y, *, hold=False, step=None, caption=None) -> None:
        super().fly_to(x, y, hold=hold, step=step)
        self.captions.append(caption)


class RecordingLLM(FakeLLM):
    def __init__(self, replies: list[str]) -> None:
        super().__init__(replies)
        self.systems: list[str] = []

    async def send(self, messages, system, model, max_tokens=1024) -> str:
        self.systems.append(system)
        return await super().send(messages, system, model, max_tokens)


def _lab_manager(replies, monkeypatch):
    monkeypatch.setattr(companion_manager, "get_foreground_window_title", lambda: "MATLAB")
    config = Config(
        worker_url="", hotkey="ctrl+alt", default_model="m", log_level="INFO", knowledge_dir=None
    )
    tracker = LabTracker(stuck_after_questions=2)
    tracker.set_lab("Lab 3", STEPS)
    parts = {"llm": RecordingLLM(replies), "tts": FakeTTS(), "overlays": CaptionOverlays()}
    manager = CompanionManager(
        config=config, mic=FakeMic(), hotkey=FakeHotkey(), transcription=FakeTranscription(),
        llm=parts["llm"], tts=parts["tts"], screen_capture_fn=_screens,
        panel_visibility_controller=parts["overlays"], click_watcher=FakeClickWatcher(),
        lab=tracker,
    )
    parts["deltas"] = []
    manager.response_delta.connect(parts["deltas"].append)
    return manager, tracker, parts


def test_turn_reports_lab_step_without_speaking_the_tag(qt_app, monkeypatch) -> None:
    manager, tracker, parts = _lab_manager(
        [
            "that's the import data button. [LAB:2] [POINT:40,120:import]",
            "check the column names. [LAB:2] [POINT:none]",
        ],
        monkeypatch,
    )

    async def run() -> None:
        _ask(manager, "where do i load the csv")
        await _settle(manager)
        assert (tracker.step, tracker.stuck) == (2, False)
        _ask(manager, "why is it empty")
        await _settle(manager)

    asyncio.run(run())
    assert "2. Load the data" in parts["llm"].systems[0]
    assert parts["tts"].spoken[0] == "that's the import data button."
    assert tracker.stuck  # second question on the same step


def test_hint_while_idle_points_and_speaks(qt_app, monkeypatch) -> None:
    manager, tracker, parts = _lab_manager(["[POINT:640,360:run button]"], monkeypatch)
    tracker.set_step(3)

    async def run() -> None:
        manager.deliver_hint(LabHint(1, 3, "save the script, then press Run", "the run button"))
        await _settle(manager)

    asyncio.run(run())
    request = parts["llm"].requests[0][-1]["content"]
    assert any(block["type"] == "image" for block in request)
    assert "the run button" in request[-1]["text"]
    x, y, hold, _ = parts["overlays"].flights[0]
    assert (x, y, hold) == (960, 540, False)
    assert parts["overlays"].captions == ["TA hint!"]
    assert parts["tts"].spoken == ["hint from your TA for step 3. save the script, then press Run"]
    assert parts["deltas"] == []  # the locating reply is only a tag
    assert manager._state == VoiceState.IDLE


def test_hint_waits_for_the_current_turn(qt_app, monkeypatch) -> None:
    manager, tracker, parts = _lab_manager(
        ["the run button is up top. [LAB:3] [POINT:none]", "[POINT:none]"], monkeypatch
    )

    async def run() -> None:
        _ask(manager, "how do i run it")
        await asyncio.sleep(0)
        manager.deliver_hint(LabHint(1, 3, "press F5"))
        assert len(parts["llm"].requests) == 0  # not interrupted
        await _settle(manager)
        await _settle(manager)

    asyncio.run(run())
    assert parts["tts"].spoken == [
        "the run button is up top.",
        "hint from your TA for step 3. press F5",
    ]
    assert parts["overlays"].flights == []  # nothing to point at, still spoken


def test_hint_for_a_step_the_student_left_is_dropped(qt_app, monkeypatch) -> None:
    manager, tracker, parts = _lab_manager([], monkeypatch)
    tracker.set_step(1)
    manager.deliver_hint(LabHint(1, 3, "press F5"))
    assert manager._state == VoiceState.IDLE
    assert parts["llm"].requests == []


@pytest.fixture
def qt_app():
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])
