"""ElevenLabs TTS client with QMediaPlayer playback.

Fetches MP3 audio from an ElevenLabs TTS endpoint via a Cloudflare Worker
proxy and plays it through ``QMediaPlayer`` with ``QAudioOutput``.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

logger = logging.getLogger(__name__)


class TTSClient(QObject):
    """Fetch MP3 audio from a TTS worker and play it via QMediaPlayer.

    Signals:
        playback_started: Emitted when audio playback begins.
        playback_finished: Emitted when audio playback completes normally.
        error(str): Emitted on HTTP or playback errors.
    """

    playback_started = Signal()
    playback_finished = Signal()
    error = Signal(str)

    def __init__(self, worker_url: str, *, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker_url = worker_url.rstrip("/")

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)

        self._player.mediaStatusChanged.connect(self._on_media_status)

        # Lifetime-critical: these must survive for the duration of playback.
        self._current_bytes: bytes | None = None
        self._current_bytearray: QByteArray | None = None
        self._current_buffer: QBuffer | None = None

        self._playback_future: asyncio.Future[bool] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def speak(self, text: str) -> None:
        """Fetch TTS audio and play it, awaiting until playback finishes.

        Args:
            text: The text to synthesise into speech.
        """
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._worker_url}/tts",
                    json={"text": text},
                )
                response.raise_for_status()
                mp3_bytes = response.content
        except Exception as exc:
            msg = f"TTS request failed: {exc}"
            logger.error(msg)
            self.error.emit(msg)
            return

        try:
            # Store all three objects as instance attrs to prevent GC.
            self._current_bytes = mp3_bytes
            self._current_bytearray = QByteArray(self._current_bytes)
            self._current_buffer = QBuffer(self._current_bytearray, parent=self)
            self._current_buffer.open(QIODevice.OpenModeFlag.ReadOnly)

            self._player.setSourceDevice(self._current_buffer)
            self._player.play()
            self.playback_started.emit()

            loop = asyncio.get_running_loop()
            self._playback_future = loop.create_future()
            await self._playback_future
        except Exception as exc:
            msg = f"TTS playback failed: {exc}"
            logger.error(msg)
            self.error.emit(msg)

    def stop(self) -> None:
        """Stop playback and resolve the pending future."""
        self._player.stop()
        if self._playback_future and not self._playback_future.done():
            self._playback_future.set_result(False)

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._playback_future and not self._playback_future.done():
                self._playback_future.set_result(True)
            self.playback_finished.emit()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            err = self._player.errorString() or "invalid media"
            if self._playback_future and not self._playback_future.done():
                self._playback_future.set_result(False)
            self.error.emit(err)
