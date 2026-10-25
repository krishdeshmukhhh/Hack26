"""Optional real SAPI checks: CURIO_TEST_SAPI=1 uv run pytest -s -k native_sapi.

These briefly open the Windows speech microphone. No audio is saved/uploaded.
Emulated recognition validates event delivery, not acoustic accuracy.
"""

from __future__ import annotations

import os
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication

from curio.hands_free import (
    WindowsMessagePump,
    WindowsWakeListener,
    configure_wake_microphone,
    create_wake_grammar,
    set_command_mode,
)
from curio.speech_activity import SpeechClassifier

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("CURIO_TEST_SAPI") != "1",
    reason="explicit opt-in required for native Windows microphone checks",
)


def test_native_sapi_grammar_events():
    from comtypes.client import CreateObject, GetEvents

    recognizer = CreateObject("SAPI.SpInprocRecognizer")
    from comtypes.gen import SpeechLib

    recognizer.State = 0
    configure_wake_microphone(recognizer)
    context, grammar = create_wake_grammar(recognizer)
    events = []

    class Events:
        def Recognition(self, *args):
            if int(args[-2]) & 2:  # Emulated input only; exclude ambient live speech.
                events.append(args[-1].PhraseInfo.GetText())

    connection = GetEvents(context, Events(), interface=SpeechLib._ISpeechRecoContextEvents)
    messages = WindowsMessagePump()
    try:
        recognizer.State = 1
        for phrase in ("hey curio", "okay curio"):
            recognizer.EmulateRecognition(phrase)
            deadline = time.monotonic() + 3
            while phrase not in events and time.monotonic() < deadline:
                messages.pump()
                time.sleep(0.01)
            assert phrase in events
        before = len(events)
        recognizer.EmulateRecognition("this is unrelated background speech")
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            messages.pump()
            time.sleep(0.01)
        assert len(events) == before
    finally:
        recognizer.State = 0
        connection.disconnect()


def test_native_sapi_worker_and_cpu():
    app = QCoreApplication.instance() or QCoreApplication([])
    listener = WindowsWakeListener()
    ready, errors = [], []
    listener.ready.connect(lambda: ready.append(True))
    listener.failed.connect(errors.append)
    listener.start()
    try:
        deadline = time.monotonic() + 10
        while not ready and not errors and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not errors
        assert ready
        for armed in (True, False):
            listener.arm(armed)
            # Exclude cold engine activation from steady-state measurements.
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            wall_start, cpu_start = time.monotonic(), time.process_time()
            time.sleep(3)  # Measure the native worker without Qt harness polling.
            cpu = time.process_time() - cpu_start
            wall = time.monotonic() - wall_start
            print(f"SAPI armed={armed}: {cpu:.4f}s CPU / {wall:.2f}s wall "
                  f"({100 * cpu / wall:.2f}% of one logical core)")
            assert not errors
            assert listener.isRunning()
    finally:
        listener.close()
        assert listener.wait(10000)


def test_native_sapi_live_microphone_stream_advances():
    """A valid grammar/emulated event is insufficient: real mic input must flow."""
    from comtypes.client import CreateObject

    recognizer = CreateObject("SAPI.SpInprocRecognizer")
    recognizer.State = 0
    configure_wake_microphone(recognizer)
    context, grammar = create_wake_grammar(recognizer)
    messages = WindowsMessagePump()
    try:
        recognizer.State = 1
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            messages.pump()
            if int(recognizer.Status.CurrentStreamPosition) > 0:
                break
            time.sleep(0.02)
        assert int(recognizer.Status.CurrentStreamPosition) > 0
    finally:
        recognizer.State = 0


def test_native_sapi_recognizes_synthesized_wake_audio(tmp_path):
    """Exercise acoustic recognition using a local TTS WAV, not emulated text."""
    from comtypes.client import CreateObject, GetEvents

    output = CreateObject("SAPI.SpFileStream")
    voice = CreateObject("SAPI.SpVoice")
    wave_path = str(tmp_path / "wake.wav")
    output.Open(wave_path, 3)  # SSFMCreateForWrite
    voice.AudioOutputStream = output
    voice.Speak("Hey Curio", 0)
    output.Close()

    recognizer = CreateObject("SAPI.SpInprocRecognizer")
    from comtypes.gen import SpeechLib

    recognizer.State = 0
    source = CreateObject("SAPI.SpFileStream")
    source.Open(wave_path, 0)  # SSFMOpenForRead
    recognizer.AudioInputStream = source
    context, grammar = create_wake_grammar(recognizer)
    events = []

    class Events:
        def Recognition(self, *args):
            events.append(args[-1].PhraseInfo.GetText().lower())

    connection = GetEvents(context, Events(), interface=SpeechLib._ISpeechRecoContextEvents)
    messages = WindowsMessagePump()
    try:
        recognizer.State = 1
        deadline = time.monotonic() + 5
        while not events and time.monotonic() < deadline:
            messages.pump()
            time.sleep(0.01)
        assert events and events[0] in ("hey curio", "hey clickie")
    finally:
        recognizer.State = 0
        connection.disconnect()
        source.Close()


def test_native_sapi_send_cancel_commands_and_mode_gating():
    from comtypes.client import CreateObject, GetEvents

    recognizer = CreateObject("SAPI.SpInprocRecognizer")
    from comtypes.gen import SpeechLib

    recognizer.State = 0
    configure_wake_microphone(recognizer)
    context, grammar = create_wake_grammar(recognizer)
    events = []

    class Events:
        def Recognition(self, *args):
            events.append(args[-1].PhraseInfo.Rule.Name)

    connection = GetEvents(context, Events(), interface=SpeechLib._ISpeechRecoContextEvents)
    pump = WindowsMessagePump()

    def emulate(text):
        before = len(events)
        recognizer.EmulateRecognition(text)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            pump.pump()
            time.sleep(0.01)
        return events[before:]

    try:
        recognizer.State = 1
        assert emulate("curio send") == []  # standby cannot send a question
        set_command_mode(grammar, True)
        assert emulate("hey curio") == []
        assert emulate("curio send") == ["CurioSend"]
        assert emulate("how do I export a video curio send") == ["CurioSend"]
        assert emulate("curio cancel") == ["CurioCancel"]
    finally:
        recognizer.State = 0
        connection.disconnect()


def test_native_vad_rejects_loud_noise_and_retains_speech(tmp_path):
    import wave

    import numpy as np
    from comtypes.client import CreateObject

    output = CreateObject("SAPI.SpFileStream")
    voice = CreateObject("SAPI.SpVoice")
    path = str(tmp_path / "question.wav")
    output.Format.Type = 18  # SAFT16kHz16BitMono, readable without optional decoders.
    output.Open(path, 3)
    voice.AudioOutputStream = output
    voice.Speak("How do I change my wallpaper in Windows?", 0)
    output.Close()
    with wave.open(path, "rb") as recording:
        assert recording.getframerate() == 16000
        speech = np.frombuffer(recording.readframes(recording.getnframes()), dtype="<i2")
        speech = speech.astype(np.float32) / 32768
    classifier = SpeechClassifier()
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 0.04, 48000).astype(np.float32)
    hum = 0.08 * np.sin(2 * np.pi * 120 * np.arange(48000) / 16000)

    def classify_windows(audio):
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        return [classifier(pcm[max(0, end - 32000):end])
                for end in range(3200, len(pcm) + 1, 3200)]

    assert not any(classify_windows(noise))
    assert not any(classify_windows(hum))
    assert sum(classify_windows(speech)) >= 3
    assert not any(classify_windows(np.concatenate([speech, noise]))[-10:])
    start = time.perf_counter()
    classify_windows(noise)
    print(f"VAD time per 100 ms window: {(time.perf_counter() - start) / 30 * 1000:.2f} ms")
