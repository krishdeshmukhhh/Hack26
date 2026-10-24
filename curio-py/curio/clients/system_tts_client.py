"""Offline text-to-speech using the Windows voices via ``QTextToSpeech``.

Drop-in replacement for ``TTSClient`` (same ``speak`` / ``stop`` API and
signals). No network, no API key — it uses whatever voices are installed
under Windows Settings > Time & language > Speech.
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtTextToSpeech import QTextToSpeech

logger = logging.getLogger(__name__)


class SystemTTSClient(QObject):
    """Speak text with the OS speech engine, awaiting until it finishes.

    Signals:
        playback_started: Emitted when speech begins.
        playback_finished: Emitted when speech completes normally.
        error(str): Emitted on engine errors.
    """

    playback_started = Signal()
    playback_finished = Signal()
    error = Signal(str)

    def __init__(self, voice: str = "", *, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = QTextToSpeech(self)
        self._engine.stateChanged.connect(self._on_state_changed)
        self._engine.errorOccurred.connect(self._on_error)
        self._playback_future: asyncio.Future[bool] | None = None
        self._started = False

        if voice:
            self._select_voice(voice)
        logger.info(
            "system TTS engine=%s voice=%s",
            self._engine.engine(), self._engine.voice().name(),
        )

    def _select_voice(self, wanted: str) -> None:
        voices = self._engine.availableVoices()
        for candidate in voices:
            if wanted.lower() in candidate.name().lower():
                self._engine.setVoice(candidate)
                return
        logger.warning(
            "TTS voice %r not found; available: %s",
            wanted, ", ".join(v.name() for v in voices),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def speak(self, text: str) -> None:
        """Speak ``text`` and return once the engine is idle again."""
        if not text.strip():
            return
        self._started = False
        self._playback_future = asyncio.get_running_loop().create_future()
        self._engine.say(text)
        await self._playback_future

    def stop(self) -> None:
        """Stop speaking and resolve the pending future."""
        self._engine.stop(QTextToSpeech.BoundaryHint.Immediate)
        self._resolve(False)

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _resolve(self, finished: bool) -> None:
        if self._playback_future and not self._playback_future.done():
            self._playback_future.set_result(finished)

    def _on_state_changed(self, state: QTextToSpeech.State) -> None:
        if state == QTextToSpeech.State.Speaking:
            if not self._started:
                self._started = True
                self.playback_started.emit()
        elif state == QTextToSpeech.State.Ready and self._started:
            self._started = False
            self._resolve(True)
            self.playback_finished.emit()

    def _on_error(self, _reason: QTextToSpeech.ErrorReason, message: str) -> None:
        self._resolve(False)
        self.error.emit(f"speech engine error: {message}")
