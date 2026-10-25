"""Local neural text-to-speech with Kokoro (kokoro-onnx, CPU).

Drop-in replacement for ``TTSClient`` (same ``speak`` / ``stop`` API and
signals). Much more natural than the Windows voices and fully offline once
the model files (~350 MB) have been downloaded on first use.

Answers are spoken sentence by sentence: the next sentence is synthesised
while the current one plays, so speech starts after the first sentence is
ready instead of after the whole answer.

If Kokoro can't load (package missing, download failed), it logs the reason
once and speaks through ``fallback`` instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import sounddevice as sd
from platformdirs import user_data_dir
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "af_heart"
_RELEASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_MODEL_FILE = "kokoro-v1.0.onnx"
_VOICES_FILE = "voices-v1.0.bin"
# Short gap between sentences so they don't run together.
_SENTENCE_GAP_SECONDS = 0.12
# Merge fragments shorter than this into the next sentence; tiny chunks
# sound choppy and cost a synthesis round-trip each.
_MIN_CHUNK_CHARS = 24


def default_model_dir() -> Path:
    return Path(user_data_dir("Curio", appauthor=False)) / "models" / "kokoro"


def split_sentences(text: str) -> list[str]:
    """Split text into speakable chunks at sentence boundaries."""
    pieces = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+", text.strip()) if p.strip()]
    chunks: list[str] = []
    pending = ""
    for piece in pieces:
        pending = f"{pending} {piece}".strip()
        if len(pending) >= _MIN_CHUNK_CHARS:
            chunks.append(pending)
            pending = ""
    if pending:
        if chunks and len(pending) < _MIN_CHUNK_CHARS:
            chunks[-1] = f"{chunks[-1]} {pending}"
        else:
            chunks.append(pending)
    return chunks


class KokoroTTSClient(QObject):
    """Speak text with Kokoro, awaiting until playback finishes.

    Signals:
        playback_started: Emitted when the first sentence starts playing.
        playback_finished: Emitted when the last sentence finishes normally.
        error(str): Emitted on synthesis or playback errors.
    """

    playback_started = Signal()
    playback_finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        voice: str = "",
        *,
        fallback: Any = None,
        model_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._voice = voice or DEFAULT_VOICE
        self._fallback = fallback
        self._model_dir = model_dir or default_model_dir()
        self._kokoro: Any = None
        self._load_error: str | None = None
        self._load_lock = threading.Lock()
        self._stopped = False
        if fallback is not None:
            fallback.error.connect(self.error)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def preload(self) -> None:
        """Load (and on first run, download) the model in the background."""
        await asyncio.to_thread(self._get_kokoro)

    async def speak(self, text: str) -> None:
        """Speak ``text`` and return once it has finished (or been stopped)."""
        if not text.strip():
            return
        self._stopped = False

        kokoro = await asyncio.to_thread(self._get_kokoro)
        if kokoro is None:
            if self._fallback is not None:
                await self._fallback.speak(text)
            return

        chunks = split_sentences(text)
        try:
            next_audio = asyncio.ensure_future(asyncio.to_thread(self._synthesize, chunks[0]))
            for index in range(len(chunks)):
                samples, sample_rate = await next_audio
                if self._stopped:
                    return
                # Synthesise the next sentence while this one plays.
                if index + 1 < len(chunks):
                    next_audio = asyncio.ensure_future(
                        asyncio.to_thread(self._synthesize, chunks[index + 1])
                    )
                if index == 0:
                    self.playback_started.emit()
                await self._play(samples, sample_rate)
                if self._stopped:
                    return
            self.playback_finished.emit()
        except asyncio.CancelledError:
            sd.stop()
            raise
        except Exception as exc:  # noqa: BLE001 — funnel to the error signal
            msg = f"Kokoro speech failed: {exc}"
            logger.error(msg)
            self.error.emit(msg)

    async def speak_stream(self, chunks: AsyncIterator[str]) -> None:
        """Speak text chunks as they arrive, synthesising ahead of playback.

        Used while the LLM is still streaming: the first finished sentence is
        voiced immediately and later ones are synthesised during playback.
        Returns when the iterator is exhausted and everything has played, or
        after ``stop()``.
        """
        self._stopped = False
        kokoro = await asyncio.to_thread(self._get_kokoro)
        if kokoro is None:
            if self._fallback is not None:
                text = " ".join([c async for c in chunks]).strip()
                if text:
                    await self._fallback.speak(text)
            return

        audio_queue: asyncio.Queue[tuple[np.ndarray, int] | None] = asyncio.Queue()

        async def synthesize_all() -> None:
            try:
                async for chunk in chunks:
                    for sentence in split_sentences(chunk):
                        if self._stopped:
                            return
                        audio_queue.put_nowait(await asyncio.to_thread(self._synthesize, sentence))
            finally:
                audio_queue.put_nowait(None)

        producer = asyncio.ensure_future(synthesize_all())
        try:
            played_any = False
            while True:
                item = await audio_queue.get()
                if item is None or self._stopped:
                    break
                samples, sample_rate = item
                if not played_any:
                    played_any = True
                    self.playback_started.emit()
                await self._play(samples, sample_rate)
                if self._stopped:
                    return
            if self._stopped:
                return
            await producer  # surfaces synthesis errors
            if played_any:
                self.playback_finished.emit()
        except asyncio.CancelledError:
            sd.stop()
            raise
        except Exception as exc:  # noqa: BLE001 — funnel to the error signal
            msg = f"Kokoro speech failed: {exc}"
            logger.error(msg)
            self.error.emit(msg)
        finally:
            producer.cancel()

    def stop(self) -> None:
        """Stop speaking immediately."""
        self._stopped = True
        sd.stop()
        if self._fallback is not None:
            self._fallback.stop()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _play(self, samples: np.ndarray, sample_rate: int) -> None:
        gap = np.zeros(int(sample_rate * _SENTENCE_GAP_SECONDS), dtype=samples.dtype)
        sd.play(np.concatenate([samples, gap]), sample_rate)
        stream = sd.get_stream()
        while stream.active and not self._stopped:
            await asyncio.sleep(0.03)

    def _synthesize(self, text: str) -> tuple[np.ndarray, int]:
        return self._kokoro.create(text, voice=self._voice, speed=1.0, lang="en-us")

    def _get_kokoro(self) -> Any:
        """Return the loaded model, or None (after logging why) if it can't load."""
        with self._load_lock:
            if self._kokoro is not None or self._load_error is not None:
                return self._kokoro
            try:
                self._kokoro = self._load()
            except Exception as exc:  # noqa: BLE001
                self._load_error = str(exc)
                logger.error(
                    "Kokoro unavailable, using %s instead: %s",
                    "the system voice" if self._fallback is not None else "no voice",
                    exc,
                )
            return self._kokoro

    def _load(self) -> Any:
        try:
            import onnxruntime as ort
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise RuntimeError("kokoro-onnx is not installed — run `uv sync --extra local`") from exc

        model_path = self._model_dir / _MODEL_FILE
        voices_path = self._model_dir / _VOICES_FILE
        for path in (model_path, voices_path):
            if not path.exists():
                _download(f"{_RELEASE_URL}/{path.name}", path)

        # onnxruntime defaults to every core with busy-wait spinning, which
        # made synthesis 6-9x slower once the rest of the app was running.
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(8, os.cpu_count() or 4)
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        session = ort.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        kokoro = Kokoro.from_session(session, str(voices_path))

        voices = kokoro.get_voices()
        if self._voice not in voices:
            logger.warning(
                "Kokoro voice %r not found, using %s. Available: %s",
                self._voice, DEFAULT_VOICE, ", ".join(sorted(voices)),
            )
            self._voice = DEFAULT_VOICE
        # First synthesis is slow (graph warm-up); do it now, not mid-answer.
        kokoro.create("ready.", voice=self._voice, lang="en-us")
        logger.info("Kokoro ready (voice=%s)", self._voice)
        return kokoro


def _download(url: str, dest: Path) -> None:
    logger.info("downloading %s", url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        with partial.open("wb") as f:
            for chunk in response.iter_bytes(1 << 20):
                f.write(chunk)
    partial.replace(dest)
