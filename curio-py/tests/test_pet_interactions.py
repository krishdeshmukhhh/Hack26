"""Turn lifecycle integration without microphone, network or actual speech."""

import asyncio
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from curio.companion_manager import CompanionManager
from curio.config import Config
from curio.state import VoiceState


class Events(QObject):
    pressed = Signal()
    released = Signal()
    cancelled = Signal()
    audio_level = Signal(float)
    pcm_chunk = Signal(object)
    interim_transcript = Signal(str)
    final_transcript = Signal(str)
    delta = Signal(str)
    error = Signal(str)
    playback_started = Signal()
    playback_finished = Signal()

    def stop(self):
        pass


class FakeTTS(Events):
    async def speak(self, text):
        self.playback_started.emit()
        await asyncio.sleep(0)
        self.playback_finished.emit()


def manager(tts):
    events = Events()
    config = Config("https://example.com", "ctrl+alt", "claude-sonnet-4-6", "INFO", None)
    return CompanionManager(
        config, events, events, events, events, tts, lambda: [], SimpleNamespace()
    )


def test_tts_events_are_independent_and_clear_on_finish():
    async def run():
        m = manager(FakeTTS())
        seen = []
        m.speaking_changed.connect(seen.append)
        m._set_state(VoiceState.RESPONDING)
        assert seen == []
        await m._speak("hello", 0)
        assert seen[0] is True and seen[-1] is False
        assert m._state == VoiceState.IDLE

    asyncio.run(run())


def test_stale_speech_completion_does_not_reset_new_turn():
    class Interrupted(FakeTTS):
        async def speak(self, text):
            self.playback_started.emit()
            m._generation += 1
            m._set_state(VoiceState.LISTENING)
            self.playback_finished.emit()

    async def run():
        nonlocal m
        m = manager(Interrupted())
        m._set_state(VoiceState.RESPONDING)
        await m._speak("old", 0)
        assert m._state == VoiceState.LISTENING

    m = None
    asyncio.run(run())


def test_cancelled_old_turn_does_not_reset_listening():
    async def run():
        m = manager(FakeTTS())
        m._set_state(VoiceState.LISTENING)
        task = asyncio.create_task(m._run_turn("old", 0))
        m._generation = 1
        await asyncio.sleep(0)
        task.cancel()
        await task
        assert m._state == VoiceState.LISTENING

    asyncio.run(run())


def test_stale_client_error_does_not_interrupt_listening():
    async def run():
        m = manager(FakeTTS())
        m._set_state(VoiceState.LISTENING)
        m._llm.error.emit("old failed request")
        assert m._state == VoiceState.LISTENING

    asyncio.run(run())


def test_cancellation_stops_pending_speech_task():
    class Pending(FakeTTS):
        async def speak(self, text):
            await asyncio.sleep(60)

        async def stop_stream(self):
            pass

    async def run():
        tts = Pending()
        m = manager(tts)
        m._transcription = tts
        m._set_state(VoiceState.RESPONDING)
        m._speak_task = asyncio.create_task(m._speak("pending", 0))
        await asyncio.sleep(0)
        m._on_hotkey_cancelled()
        await asyncio.sleep(0)
        assert m._speak_task.done()
        assert m._state == VoiceState.IDLE

    asyncio.run(run())
