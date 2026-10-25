"""Hands-free boundaries, routing and cancellation without physical audio."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QByteArray, QCoreApplication, QObject, Signal

from curio.clients.whisper_transcription_client import WhisperTranscriptionClient
from curio.hands_free import (
    HandsFreeController,
    QuestionEndpoint,
    configure_wake_microphone,
    strip_finish_command,
)
from curio.speech_activity import WINDOW_BYTES, SpeechActivityWorker
from curio.state import VoiceState
from tests.test_walkthrough import _manager, _settle


class FakeListener(QObject):
    woke = Signal()
    failed = Signal(str)
    finished = Signal()
    send_requested = Signal(int)
    cancel_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.armed = False
        self.closed = False
        self.started = False

    def start(self):
        self.started = True

    def arm(self, enabled):
        self.armed = enabled

    def close(self):
        self.closed = True

    def listen_for_finish(self, epoch):
        self.armed = False

    def wait(self, timeout=None):
        return True


class FakeSpeechWorker(FakeListener):
    ready = Signal()
    activity = Signal(bool, float, int)

    def start(self):
        self.ready.emit()

    def submit(self, pcm, timestamp, epoch):
        pass

    def reset(self):
        pass


@pytest.fixture
def setup_controller(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    manager, parts = _manager([], monkeypatch)
    now = [0.0]
    controller = HandsFreeController(
        manager, manager._mic, parts["hotkey"],
        listener_factory=FakeListener, speech_factory=FakeSpeechWorker, clock=lambda: now[0],
    )
    yield controller, manager, parts, now, app
    controller.close()


def test_endpoint_silence_noise_and_duration_limits():
    assert QuestionEndpoint(0).decision(5) == "cancel"
    endpoint = QuestionEndpoint(0)
    endpoint.observe(0.1, 1)
    assert endpoint.decision(2.3) == "cancel"  # single pop
    endpoint = QuestionEndpoint(0)
    for now in (0.1, 0.2, 0.3):
        endpoint.observe(0.1, now)
    assert endpoint.decision(1.4) is None
    assert endpoint.decision(1.6) == "submit"
    endpoint.observe(0.1, 29.9)
    assert endpoint.decision(30) == "submit"  # bounded even in continuous noise


@pytest.mark.parametrize(
    ("names", "preferred", "expected"),
    [
        (["Realtek microphone"], "", 0),
        (["USB headset", "Microphone Array (2- Realtek(R) Audio)"],
         "Microphone Array (2- Realtek(R)", 1),
        (["Realtek microphone", "USB headset"], "USB headset", 1),
    ],
)
def test_wake_binds_explicit_matching_audio_token(names, preferred, expected):
    tokens = [SimpleNamespace(Id=str(index), GetDescription=lambda n=name: n)
              for index, name in enumerate(names)]
    inputs = SimpleNamespace(Count=len(tokens), Item=lambda index: tokens[index])
    recognizer = SimpleNamespace(GetAudioInputs=lambda: inputs, AudioInput=None)
    assert configure_wake_microphone(recognizer, preferred) == names[expected]
    assert recognizer.AudioInput is tokens[expected]


@pytest.mark.parametrize("names", [[], ["headset one", "headset two"]])
def test_unavailable_or_ambiguous_wake_input_fails_explicitly(names):
    tokens = [SimpleNamespace(Id=name, GetDescription=lambda n=name: n) for name in names]
    inputs = SimpleNamespace(Count=len(tokens), Item=lambda index: tokens[index])
    recognizer = SimpleNamespace(GetAudioInputs=lambda: inputs, AudioInput=None)
    with pytest.raises(RuntimeError):
        configure_wake_microphone(recognizer, "unmatched device")
    assert recognizer.AudioInput is None


def test_cancelled_wake_does_not_invoke_whisper(setup_controller, monkeypatch):
    _, manager, _, _, _ = setup_controller
    transcription = WhisperTranscriptionClient("base.en")
    manager._transcription = transcription
    transcribed = []
    monkeypatch.setattr(transcription, "_transcribe", lambda pcm: transcribed.append(pcm))

    async def run():
        manager.begin_hands_free()
        await asyncio.sleep(0)
        manager._on_pcm_chunk(QByteArray(b"\x00\x00" * 16000))
        await asyncio.sleep(0)
        assert transcription._pcm
        manager.cancel_hands_free()
        await asyncio.sleep(0)
        await transcription.stop_stream()
        assert not transcription._pcm
        assert not transcribed
        assert manager._state == VoiceState.IDLE

    asyncio.run(run())


def test_disabled_has_no_worker_or_timer_and_ignores_idle_pcm(setup_controller):
    controller, manager, _, _, _ = setup_controller
    assert controller._listener is None
    assert not controller._timer.isActive()
    for _ in range(10000):
        manager._on_pcm_chunk(QByteArray(b"audio"))
    assert not manager._pcm["deque"]


def test_wake_records_then_silence_submits_once(setup_controller):
    controller, manager, _, now, _ = setup_controller

    async def run():
        controller.set_enabled(True)
        now[0] = 1
        controller._tick()
        listener = controller._listener
        assert listener.armed
        listener.woke.emit()
        assert manager._state == VoiceState.LISTENING
        assert not listener.armed
        # A stray key release must not prematurely finish hands-free capture.
        manager._on_hotkey_released()
        assert manager._state == VoiceState.LISTENING
        for moment in (1.1, 1.2, 1.3):
            now[0] = moment
            controller._on_speech(True, now[0], controller._capture_epoch)
            manager._on_pcm_chunk(QByteArray(b"pcm"))
        await asyncio.sleep(0)
        now[0] = 2.6
        controller._tick()
        assert manager._state == VoiceState.PROCESSING
        assert not controller._timer.isActive()
        assert controller._endpoint is None
        assert not listener.armed
        await asyncio.sleep(0)
        controller._tick()
        assert manager._state == VoiceState.PROCESSING

    asyncio.run(run())


def test_wake_to_whisper_to_answer_preserves_pointing(setup_controller, monkeypatch):
    controller, manager, parts, now, _ = setup_controller
    transcription = WhisperTranscriptionClient("base.en")
    monkeypatch.setattr(transcription, "_transcribe", lambda pcm: "where is the button")
    transcription.final_transcript.connect(manager._on_final_transcript)
    manager._transcription = transcription
    parts["llm"].replies.append("Right here. [POINT:100,100:button]")

    async def run():
        controller.set_enabled(True)
        now[0] = 1
        controller._listener.woke.emit()
        for moment in (1.1, 1.2, 1.3, 1.4):
            now[0] = moment
            manager._mic.audio_level.emit(0.1)
            controller._on_speech(True, now[0], controller._capture_epoch)
            manager._on_pcm_chunk(QByteArray(b"\x01\x00" * 1600))
        await asyncio.sleep(0)
        now[0] = 2.7
        controller._tick()
        # stop_stream performs local inference on its worker before assigning
        # the normal manager task; wait for that callback before settling it.
        for _ in range(100):
            await asyncio.sleep(0.01)
            if parts["llm"].requests:
                break
        await _settle(manager)
        assert len(parts["llm"].requests) == 1
        assert parts["tts"].spoken == ["Right here."]
        assert len(parts["overlays"].flights) == 1
        assert manager._state == VoiceState.IDLE
        assert not manager._pcm["deque"]

    asyncio.run(run())


def test_no_speech_aborts_without_llm_or_screenshots(setup_controller):
    controller, manager, parts, now, _ = setup_controller

    async def run():
        controller.set_enabled(True)
        now[0] = 1
        controller._listener.woke.emit()
        await asyncio.sleep(0)
        now[0] = 6
        controller._tick()
        assert manager._state == VoiceState.IDLE
        assert not parts["llm"].requests
        assert not manager._current_screenshots
        await asyncio.sleep(0)

    asyncio.run(run())


def test_background_volume_does_not_refresh_speech_endpoint(setup_controller):
    controller, manager, _, now, _ = setup_controller

    async def run():
        controller.set_enabled(True)
        now[0] = 1
        controller._listener.woke.emit()
        for moment in (1.1, 1.2, 1.3):
            controller._on_speech(True, moment, controller._capture_epoch)
        for moment in (1.5, 2, 2.7):
            now[0] = moment
            manager._mic.audio_level.emit(0.9)  # loud background is not speech evidence
            controller._on_speech(False, moment, controller._capture_epoch)
        controller._tick()
        assert manager._state == VoiceState.PROCESSING
        await asyncio.sleep(0)

    asyncio.run(run())


@pytest.mark.parametrize("command", ["send", "cancel"])
def test_voice_command_ends_capture_even_with_continuous_background_speech(
    setup_controller, command,
):
    controller, manager, _, now, _ = setup_controller

    async def run():
        controller.set_enabled(True)
        now[0] = 1
        controller._listener.woke.emit()
        epoch = controller._capture_epoch
        for moment in (1.1, 1.2, 1.3, 2, 3):
            controller._on_speech(True, moment, epoch)
        now[0] = 3
        if command == "send":
            controller._listener.send_requested.emit(epoch)
            assert manager._state == VoiceState.PROCESSING
        else:
            controller._listener.cancel_requested.emit(epoch)
            assert manager._state == VoiceState.IDLE
        assert controller._endpoint is None
        await asyncio.sleep(0)

    asyncio.run(run())


def test_old_detector_and_command_results_cannot_end_new_recording(setup_controller):
    controller, manager, _, now, _ = setup_controller

    async def run():
        controller.set_enabled(True)
        now[0] = 1
        controller._listener.woke.emit()
        old_epoch = controller._capture_epoch
        controller._cancel_question()
        await asyncio.sleep(0)
        now[0] = 2
        controller._listener.woke.emit()
        controller._on_speech(True, 20, old_epoch)
        controller._listener.send_requested.emit(old_epoch)
        controller._listener.cancel_requested.emit(old_epoch)
        assert controller._endpoint.last_voice is None
        assert manager._state == VoiceState.LISTENING
        controller._cancel_question()
        await asyncio.sleep(0)

    asyncio.run(run())


@pytest.mark.parametrize("cue", ["Curio, send.", "kurio done", "Currio finish!"])
def test_explicit_send_cue_removed_from_transcript(cue):
    assert strip_finish_command("Where is export? " + cue) == "Where is export"
    assert strip_finish_command(cue) == ""
    assert strip_finish_command("How do I click Send?") == "How do I click Send?"


def test_speech_work_queue_is_bounded_and_resets_between_questions(setup_controller):
    worker = SpeechActivityWorker()
    for index in range(1000):
        worker.submit(b"\x01\x00" * 1600, index / 10, 1)
    assert len(worker._audio) == WINDOW_BYTES
    assert len(worker._pending[0]) == WINDOW_BYTES
    worker.submit(b"\x02\x00" * 1600, 101, 2)
    assert worker._pending == (b"\x02\x00" * 1600, 101, 2)
    worker.close()
    assert not worker._audio
    assert worker._pending is None


def test_push_to_talk_takes_over_without_silence_releasing_key(setup_controller):
    controller, manager, parts, now, _ = setup_controller

    async def run():
        controller.set_enabled(True)
        now[0] = 1
        controller._listener.woke.emit()
        await asyncio.sleep(0)
        parts["hotkey"].pressed.emit()
        assert controller._endpoint is None
        assert not manager._hands_free_recording
        now[0] = 50
        controller._tick()
        assert manager._state == VoiceState.LISTENING
        parts["hotkey"].released.emit()
        assert manager._state == VoiceState.PROCESSING
        await asyncio.sleep(0)

    asyncio.run(run())


def test_manual_release_still_closes_mic_after_early_cloud_transcript(
    setup_controller, monkeypatch,
):
    _, manager, parts, _, _ = setup_controller
    stops = []
    monkeypatch.setattr(manager._mic, "stop", lambda: stops.append(True))

    async def run():
        parts["hotkey"].pressed.emit()
        await asyncio.sleep(0)
        # AssemblyAI may finish during a pause while the key is still held.
        manager._set_state(VoiceState.RESPONDING)
        parts["hotkey"].released.emit()
        await asyncio.sleep(0)
        assert stops == [True]
        assert manager._pcm["done"]

    asyncio.run(run())


@pytest.mark.parametrize("state", [VoiceState.PROCESSING, VoiceState.RESPONDING])
def test_no_wake_during_pipeline_or_playback(setup_controller, state):
    controller, manager, _, now, _ = setup_controller
    controller.set_enabled(True)
    manager._set_state(state)
    assert not controller._timer.isActive()
    now[0] = 2
    controller._tick()
    assert not controller._listener.armed
    controller._listener.woke.emit()
    assert manager._state == state
    manager._set_state(VoiceState.IDLE)
    controller._tick()
    assert not controller._listener.armed  # echo cooldown
    now[0] = 3
    controller._tick()
    assert controller._listener.armed


def test_disable_and_rapid_reenable_drop_stale_events(setup_controller):
    controller, manager, _, now, _ = setup_controller
    errors = []
    controller.error.connect(errors.append)
    controller.set_enabled(True)
    old = controller._listener
    controller.set_enabled(False)
    assert old.closed
    assert not old.armed
    controller.set_enabled(True)
    now[0] = 2
    old.woke.emit()
    old.failed.emit("stale failure")
    assert manager._state == VoiceState.IDLE
    assert controller._enabled
    assert not errors
    controller._listener.failed.emit("recognizer unavailable")
    assert not controller._enabled
    assert errors == ["recognizer unavailable"]


@pytest.mark.parametrize("action", ["disable", "escape", "mic_error"])
def test_cancel_capture_recovers(setup_controller, action):
    controller, manager, parts, now, _ = setup_controller

    async def run():
        controller.set_enabled(True)
        now[0] = 1
        controller._listener.woke.emit()
        await asyncio.sleep(0)
        if action == "disable":
            controller.set_enabled(False)
        elif action == "escape":
            parts["hotkey"].escape_pressed.emit()
        else:
            controller._on_mic_error("unavailable")
        assert manager._state == VoiceState.IDLE
        assert controller._endpoint is None
        await asyncio.sleep(0)

    asyncio.run(run())
