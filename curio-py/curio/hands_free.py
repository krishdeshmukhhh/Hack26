"""Opt-in Windows wake phrases and bounded, silence-ended question capture.

SAPI owns the standby microphone on a dedicated COM thread. It is suspended
before a wake notification, and throughout transcription/inference/playback.
No standby audio is passed to Whisper, providers, or the manager's PCM queue.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from curio.speech_activity import SpeechActivityWorker
from curio.state import VoiceState

logger = logging.getLogger(__name__)


@dataclass
class QuestionEndpoint:
    """Constant-space endpoint detector; elapsed times use a monotonic clock."""

    started: float
    silence_seconds: float = 1.2
    speech_seconds: float = 0.0
    last_voice: float | None = None

    def observe(self, speech: bool, now: float) -> None:
        if speech:
            self.last_voice = now
            # MicCapture emits one level per 100 ms block. Require several
            # voiced blocks so a single click/pop cannot submit a question.
            self.speech_seconds += 0.1

    def decision(self, now: float) -> str | None:
        if self.last_voice is None and now - self.started >= 5:
            return "cancel"
        if self.last_voice is not None and now - self.last_voice >= self.silence_seconds:
            return "submit" if self.speech_seconds >= 0.3 else "cancel"
        if now - self.started >= 30:
            return "submit" if self.speech_seconds >= 0.3 else "cancel"
        return None


def strip_finish_command(text: str) -> str:
    """Remove an explicit send cue only from a hands-free command-ended turn."""
    return re.sub(
        r"(?:\s*[,.;!?]\s*|\s+|^)(?:curio|kurio|currio|cario)"
        r"\s*[,.:]?\s*(?:send(?:\s+it)?|done|finish)[.!?\s]*$", "", text,
        flags=re.IGNORECASE,
    ).strip()


class WindowsMessagePump:
    """SAPI posts window messages; COM's PumpEvents alone does not deliver them."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._message = wintypes.MSG()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT, wintypes.UINT,
        ]
        self._user32.PeekMessageW.restype = wintypes.BOOL
        self._user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.DispatchMessageW.restype = ctypes.c_ssize_t

    def pump(self) -> None:
        message = self._ctypes.byref(self._message)
        while self._user32.PeekMessageW(message, None, 0, 0, 1):
            self._user32.TranslateMessage(message)
            self._user32.DispatchMessageW(message)


def create_wake_grammar(recognizer):
    """Build the native phrase grammar on its owning COM thread."""
    context = recognizer.CreateRecoContext()
    context.EventInterests = 16  # SRERecognition only
    grammar = context.CreateGrammar(1)
    rule = grammar.Rules.Add("CurioWake", 33, 1)  # top-level | dynamic
    for phrase in ("hey curio", "okay curio"):
        # Explicit optional arguments avoid comtypes' omitted-VARIANT
        # defaults being rejected by Windows SAPI (E_INVALIDARG).
        rule.InitialState.AddWordTransition(None, phrase, " ", 1, "", 0, "", 1.0)
    grammar.Rules.Commit()
    grammar.CmdSetRuleState("CurioWake", 1)
    for name, phrases, rule_id in (
        ("CurioSend", ("curio send", "curio done", "curio finish"), 2),
        ("CurioCancel", ("curio cancel",), 3),
    ):
        command = grammar.Rules.Add(name, 33, rule_id)
        prefix = command.AddState()
        # Accept a question followed by the cue as well as a standalone cue.
        command.InitialState.AddSpecialTransition(prefix, 1, "", 0, "", 1.0)
        for phrase in phrases:
            command.InitialState.AddWordTransition(None, phrase, " ", 1, "", 0, "", 1.0)
            prefix.AddWordTransition(None, phrase, " ", 1, "", 0, "", 1.0)
    grammar.Rules.Commit()
    set_command_mode(grammar, False)
    return context, grammar


def set_command_mode(grammar, recording: bool) -> None:
    grammar.CmdSetRuleState("CurioWake", int(not recording))
    grammar.CmdSetRuleState("CurioSend", int(recording))
    grammar.CmdSetRuleState("CurioCancel", int(recording))


def configure_wake_microphone(recognizer, preferred_name: str = "") -> str:
    """Bind a real input token: AudioInput=None leaves in-process SAPI silent.

    Prefer the same device name PortAudio uses, allowing its truncated names.
    With a single Windows speech input there is no ambiguity.
    """
    inputs = recognizer.GetAudioInputs()
    if not inputs.Count:
        raise RuntimeError("no Windows speech input device")
    tokens = [inputs.Item(index) for index in range(inputs.Count)]
    names = [token.GetDescription() for token in tokens]
    preferred = preferred_name.casefold().strip()
    matches = [
        index for index, name in enumerate(names)
        if preferred and (name.casefold().startswith(preferred)
                          or preferred.startswith(name.casefold()))
    ]
    if len(matches) == 1:
        index = matches[0]
    elif len(tokens) == 1:
        index = 0
    else:
        raise RuntimeError(
            "cannot match Windows speech microphone to Curio's default input; "
            "check the Windows default recording device"
        )
    recognizer.AudioInput = tokens[index]
    # Readback also catches a silently uninitialized native input.
    if not recognizer.AudioInput.Id:
        raise RuntimeError("Windows speech microphone did not initialize")
    return names[index]


class WindowsWakeListener(QThread):
    """Small command grammar, no dictation, downloads, account or audio archive."""

    woke = Signal()
    failed = Signal(str)
    ready = Signal()
    send_requested = Signal(int)
    cancel_requested = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._armed = threading.Event()
        self._capture_epoch: int | None = None
        self._stop = threading.Event()
        self._changed = threading.Event()

    def arm(self, armed: bool) -> None:
        was_recording = self._capture_epoch is not None
        self._capture_epoch = None
        if armed == self._armed.is_set() and not was_recording:
            return
        if armed:
            self._armed.set()
        else:
            self._armed.clear()
        self._changed.set()

    def listen_for_finish(self, epoch: int) -> None:
        self._armed.clear()
        self._capture_epoch = epoch
        self._changed.set()

    def close(self) -> None:
        self._armed.clear()
        self._capture_epoch = None
        self._stop.set()
        self._changed.set()

    def run(self) -> None:
        # Lazy imports: disabled mode does not initialize speech/COM resources.
        com_initialized = False
        recognizer = context = _grammar = connection = None
        try:
            import comtypes
            from comtypes.client import CreateObject, GetEvents

            comtypes.CoInitialize()
            com_initialized = True
            messages = WindowsMessagePump()
            recognizer = CreateObject("SAPI.SpInprocRecognizer")
            from comtypes.gen import SpeechLib

            recognizer.State = 0  # SRSInactive
            import sounddevice as sd

            microphone = configure_wake_microphone(
                recognizer, sd.query_devices(kind="input")["name"]
            )
            logger.info("hands-free microphone: %s", microphone)
            context, _grammar = create_wake_grammar(recognizer)
            listener = self

            class Events:
                def Recognition(self, *args) -> None:
                    if listener._stop.is_set():
                        return
                    rule = args[-1].PhraseInfo.Rule.Name
                    epoch = listener._capture_epoch
                    if epoch is not None and rule in ("CurioSend", "CurioCancel"):
                        listener._capture_epoch = None
                        listener._changed.set()
                        recognizer.State = 0
                        signal = (listener.send_requested if rule == "CurioSend"
                                  else listener.cancel_requested)
                        signal.emit(epoch)
                        return
                    if not listener._armed.is_set() or rule != "CurioWake":
                        return
                    # Disable BEFORE notifying Qt: never recognize our own TTS.
                    listener._armed.clear()
                    listener._changed.set()
                    recognizer.State = 0
                    logger.info("hands-free wake phrase recognized")
                    listener.woke.emit()

            connection = GetEvents(context, Events(), interface=SpeechLib._ISpeechRecoContextEvents)
            self.ready.emit()
            logger.info("hands-free recognizer ready")
            active = None
            while not self._stop.is_set():
                wanted = ("capture", self._capture_epoch) if self._capture_epoch is not None else (
                    ("wake", None) if self._armed.is_set() else ("off", None)
                )
                if wanted != active:
                    recognizer.State = 0
                    set_command_mode(_grammar, wanted[0] == "capture")
                    if wanted[0] != "off":
                        recognizer.State = 1
                    logger.debug("hands-free native listening=%s", wanted)
                    active = wanted
                messages.pump()
                # While the response pipeline is busy, sleep until explicitly
                # rearmed/stopped: no recognizer work or polling in that path.
                listening = self._armed.is_set() or self._capture_epoch is not None
                self._changed.wait(0.05 if listening else None)
                self._changed.clear()
        except Exception:
            logger.exception("Windows hands-free recognizer failed")
            self.failed.emit(
                "Hands-free unavailable. Check the microphone and install/configure "
                "Windows English speech recognition in Windows Settings. Ctrl+Alt still works."
            )
        finally:
            if recognizer is not None:
                with suppress(Exception):
                    recognizer.State = 0
            if connection is not None:
                with suppress(Exception):
                    connection.disconnect()
            connection = _grammar = context = recognizer = None
            if com_initialized:
                comtypes.CoUninitialize()


class HandsFreeController(QObject):
    """Routes wake/endpoint events through the existing voice-turn lifecycle."""

    enabled_changed = Signal(bool)
    error = Signal(str)

    def __init__(self, manager, mic, hotkey, parent=None, *, listener_factory=None,
                 speech_factory=None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(parent)
        self._manager = manager
        self._clock = clock
        self._factory = listener_factory or WindowsWakeListener
        self._speech_factory = speech_factory or SpeechActivityWorker
        self._speech_worker = None
        self._speech_ready = False
        self._capture_epoch = 0
        self._listener = None
        self._workers: list[WindowsWakeListener] = []
        self._enabled = False
        self._endpoint: QuestionEndpoint | None = None
        self._state = VoiceState.IDLE
        self._ready_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        manager.state_changed.connect(self._on_state)
        mic.pcm_chunk.connect(self._on_pcm)
        mic.error.connect(self._on_mic_error)
        hotkey.pressed.connect(self._manual_override)
        hotkey.escape_pressed.connect(self._cancel_question)

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        logger.info("hands-free enabled=%s", enabled)
        if enabled:
            self._speech_ready = False
            detector = self._speech_worker = self._speech_factory(self)
            self._workers.append(detector)
            detector.ready.connect(
                lambda: self._on_speech_ready() if detector is self._speech_worker else None
            )
            detector.activity.connect(self._on_speech)
            detector.failed.connect(
                lambda msg: self._on_failure(msg) if detector is self._speech_worker else None
            )
            detector.finished.connect(lambda: self._retire(detector))
            detector.start()
            self._listener = self._factory(self)
            listener = self._listener
            self._workers.append(listener)
            listener.woke.connect(
                lambda: self._on_wake() if listener is self._listener else None
            )
            listener.failed.connect(
                lambda message: self._on_failure(message) if listener is self._listener else None
            )
            listener.finished.connect(lambda: self._retire(listener))
            listener.send_requested.connect(self._send_command)
            listener.cancel_requested.connect(self._cancel_command)
            self._listener.start()
            self._ready_at = self._clock() + 0.8
            if self._state in (VoiceState.IDLE, VoiceState.GUIDING):
                self._timer.start()
        else:
            self._timer.stop()
            if self._listener is not None:
                self._listener.arm(False)
                self._listener.close()
                self._listener = None
            self._cancel_question()
            if self._speech_worker is not None:
                self._speech_worker.close()
                self._speech_worker = None
            self._speech_ready = False
        self.enabled_changed.emit(enabled)

    def _retire(self, listener) -> None:
        if listener in self._workers:
            self._workers.remove(listener)
        listener.deleteLater()

    def _on_failure(self, message: str) -> None:
        self.set_enabled(False)
        self.error.emit(message)

    def _on_state(self, state: VoiceState) -> None:
        self._state = state
        if self._listener is not None:
            self._listener.arm(False)
        if state != VoiceState.LISTENING:
            self._endpoint = None
            if self._speech_worker is not None:
                self._speech_worker.reset()
        self._ready_at = self._clock() + 0.8
        if self._enabled and state in (VoiceState.IDLE, VoiceState.GUIDING):
            self._timer.start()
        else:
            self._timer.stop()

    def _on_wake(self) -> None:
        if (not self._enabled or not self._speech_ready or self._clock() < self._ready_at
                or self._state not in (VoiceState.IDLE, VoiceState.GUIDING)):
            return
        self._manager.begin_hands_free()
        self._capture_epoch += 1
        self._endpoint = QuestionEndpoint(self._clock())
        self._listener.listen_for_finish(self._capture_epoch)
        self._timer.start()

    def _on_speech_ready(self) -> None:
        self._speech_ready = True
        logger.info("hands-free speech detector ready")

    def _on_pcm(self, pcm) -> None:
        if self._endpoint is not None and self._speech_worker is not None:
            self._speech_worker.submit(bytes(pcm), self._clock(), self._capture_epoch)

    def _on_speech(self, speech: bool, timestamp: float, epoch: int) -> None:
        if self._endpoint is not None and epoch == self._capture_epoch:
            self._endpoint.observe(speech, timestamp)

    def _send_command(self, epoch: int) -> None:
        if self._endpoint is not None and epoch == self._capture_epoch:
            self._endpoint = None
            self._manager.finish_hands_free(strip_command=True)

    def _cancel_command(self, epoch: int) -> None:
        if epoch == self._capture_epoch:
            self._cancel_question()

    def _manual_override(self) -> None:
        # Manager's hotkey handler already started a new manual turn. Do not
        # let a pending silence timeout release that user's held hotkey.
        self._endpoint = None
        if self._speech_worker is not None:
            self._speech_worker.reset()
        self._timer.stop()

    def _cancel_question(self) -> None:
        if self._endpoint is not None:
            self._endpoint = None
            self._manager.cancel_hands_free()

    def _on_mic_error(self, message: str) -> None:
        if self._enabled:
            self.set_enabled(False)
            self.error.emit(message)

    def _tick(self) -> None:
        if not self._enabled:
            return
        now = self._clock()
        if self._endpoint is not None:
            decision = self._endpoint.decision(now)
            if decision is not None:
                self._endpoint = None
                if decision == "submit":
                    self._manager.finish_hands_free()
                else:
                    self._manager.cancel_hands_free()
        elif self._listener is not None:
            self._listener.arm(
                now >= self._ready_at
                and self._speech_ready
                and self._state in (VoiceState.IDLE, VoiceState.GUIDING)
            )

    def close(self) -> None:
        self.set_enabled(False)
        for listener in tuple(self._workers):
            listener.close()
            # Only at application shutdown; do not destroy a running QThread
            # if Windows takes a moment to finish initializing/releasing audio.
            listener.wait()
