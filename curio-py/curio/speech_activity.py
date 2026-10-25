"""Bounded background speech detection using the VAD already shipped with Whisper."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)
WINDOW_BYTES = 32000  # One second of 16 kHz, mono PCM16.


class SpeechClassifier:
    """No download or ASR: distinguish recent speech from non-speech noise."""

    def __init__(self):
        from faster_whisper.vad import VadOptions, get_speech_timestamps, get_vad_model

        get_vad_model()  # Warm the bundled model on the worker, before activation.
        self._timestamps = get_speech_timestamps
        self._options = VadOptions(
            threshold=0.6, min_speech_duration_ms=100,
            min_silence_duration_ms=100, speech_pad_ms=0,
        )

    def __call__(self, pcm: bytes) -> bool:
        import numpy as np

        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if len(audio) < 1600:
            return False
        segments = self._timestamps(audio, self._options)
        # Only the newest 100 ms counts. Old speech in the rolling window
        # must not keep refreshing the endpoint after the person stops.
        return any(segment["end"] > len(audio) - 1600 for segment in segments)


class SpeechActivityWorker(QThread):
    """Latest-window queue: at most one second buffered, no unbounded work."""

    ready = Signal()
    activity = Signal(bool, float, int)
    failed = Signal(str)

    def __init__(self, parent=None, *, classifier_factory=SpeechClassifier):
        super().__init__(parent)
        self._factory = classifier_factory
        self._lock = threading.Lock()
        self._available = threading.Event()
        self._stopping = threading.Event()
        self._pending = None
        self._audio = bytearray()
        self._epoch = -1

    def submit(self, pcm: bytes, timestamp: float, epoch: int) -> None:
        with self._lock:
            if epoch != self._epoch:
                self._audio.clear()
                self._epoch = epoch
            self._audio.extend(pcm)
            if len(self._audio) > WINDOW_BYTES:
                del self._audio[:-WINDOW_BYTES]
            self._pending = (bytes(self._audio), timestamp, epoch)
            self._available.set()

    def reset(self) -> None:
        with self._lock:
            self._audio.clear()
            self._pending = None
            self._epoch = -1

    def close(self) -> None:
        self._stopping.set()
        self.reset()
        self._available.set()

    def run(self) -> None:
        try:
            classifier = self._factory()
            self.ready.emit()
            while not self._stopping.is_set():
                self._available.wait()
                with self._lock:
                    item = self._pending
                    self._pending = None
                    self._available.clear()
                if item is not None and not self._stopping.is_set():
                    pcm, timestamp, epoch = item
                    speech = classifier(pcm)
                    self.activity.emit(speech, timestamp, epoch)
        except Exception:
            logger.exception("hands-free speech detector failed")
            self.failed.emit("Speech detection failed; use Ctrl+Alt and check local dependencies.")
