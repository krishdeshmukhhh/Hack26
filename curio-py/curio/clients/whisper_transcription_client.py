"""Local speech-to-text via faster-whisper.

Drop-in replacement for ``TranscriptionClient`` (same signals and
``start_stream`` / ``stop_stream`` coroutines). Instead of streaming to a
service, it buffers the push-to-talk PCM and transcribes it once on release,
so a pause mid-question never splits it into two turns.

There are no interim transcripts; ``final_transcript`` fires exactly once per
session (with ``""`` when nothing intelligible was said, which the
``CompanionManager`` treats as a silent abort).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
from PySide6.QtCore import QByteArray, QObject, Signal

from curio.mic_capture import SAMPLE_RATE_HZ

logger = logging.getLogger(__name__)

# Shorter than this is almost certainly an accidental tap of the hotkey.
_MIN_AUDIO_SECONDS = 0.3
# How long stop_stream waits for start_stream to drain the PCM iterator.
_COLLECT_TIMEOUT_SECONDS = 1.0


def pcm16_to_float32(pcm: bytes) -> np.ndarray:
    """Convert little-endian int16 mono PCM to float32 samples in [-1, 1]."""
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


class WhisperTranscriptionClient(QObject):
    """Buffer push-to-talk audio and transcribe it locally with faster-whisper."""

    interim_transcript = Signal(str)
    final_transcript = Signal(str)
    error = Signal(str)

    def __init__(
        self, model_name: str, device: str = "cpu", parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._model_name = model_name
        self._device = device
        self._model: Any = None
        self._model_lock = threading.Lock()

        self._pcm = bytearray()
        self._collected: asyncio.Event | None = None
        # Bumped on every start_stream so a slow transcription from a previous
        # press can't emit into the next session.
        self._session = 0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    async def preload(self) -> None:
        """Load (and on first run, download) the model in the background."""
        try:
            await asyncio.to_thread(self._get_model)
        except Exception as exc:  # noqa: BLE001 — surfaced again on first use
            logger.error("whisper preload failed: %s", exc)

    async def start_stream(self, pcm_chunk_iterator: AsyncIterator[QByteArray]) -> None:
        self._session += 1
        self._pcm = bytearray()
        collected = self._collected = asyncio.Event()
        try:
            async for chunk in pcm_chunk_iterator:
                self._pcm += bytes(chunk)
        finally:
            collected.set()

    async def stop_stream(self) -> None:
        session = self._session
        collected = self._collected
        if collected is None:
            return
        self._collected = None

        try:
            await asyncio.wait_for(collected.wait(), timeout=_COLLECT_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("PCM iterator did not finish; transcribing what we have")

        pcm = bytes(self._pcm)
        if len(pcm) < _MIN_AUDIO_SECONDS * SAMPLE_RATE_HZ * 2:
            self._emit_final(session, "")
            return

        try:
            text = await asyncio.to_thread(self._transcribe, pcm)
        except Exception as exc:  # noqa: BLE001 — funnel to the error signal
            logger.error("whisper transcription failed: %s", exc)
            if session == self._session:
                self.error.emit(f"local transcription failed: {exc}")
            return

        self._emit_final(session, text)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _emit_final(self, session: int, text: str) -> None:
        if session != self._session:
            logger.debug("dropping transcript from stale session %d", session)
            return
        self.final_transcript.emit(text)

    def _get_model(self) -> Any:
        with self._model_lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError(
                        "faster-whisper is not installed — run `uv sync --extra local`"
                    ) from exc
                compute_type = "float16" if self._device == "cuda" else "int8"
                logger.info(
                    "loading whisper model %s on %s (%s)",
                    self._model_name, self._device, compute_type,
                )
                self._model = WhisperModel(
                    self._model_name, device=self._device, compute_type=compute_type
                )
            return self._model

    def _transcribe(self, pcm: bytes) -> str:
        model = self._get_model()
        language = "en" if self._model_name.endswith(".en") else None
        segments, _info = model.transcribe(
            pcm16_to_float32(pcm), language=language, vad_filter=True
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        logger.debug("whisper transcript: %r", text)
        return text
