"""System audio output level monitor via Windows Audio Meter.

Uses pycaw/COM IAudioMeterInformation to poll the default speaker's
peak level. No loopback stream needed — just reads the mixer meter
that Windows already maintains. Emits audio_level(float) on a QTimer
for the companion waveform to visualize during TTS playback.
"""

from __future__ import annotations

import logging
from ctypes import POINTER, cast

from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

POLL_INTERVAL_MS = 33  # ~30fps, matches companion cursor tracking


class OutputCapture(QObject):
    """Monitors system audio output level for waveform display.

    Signals
    -------
    audio_level(float)
        Peak audio level from the default output device, [0.0, 1.0].
    """

    audio_level = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._meter: POINTER(IAudioMeterInformation) | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._init_meter()

    def _init_meter(self) -> None:
        """Initialize the COM audio meter interface."""
        try:
            device = AudioUtilities.GetSpeakers()
            interface = device._dev.Activate(
                IAudioMeterInformation._iid_, CLSCTX_ALL, None
            )
            self._meter = cast(interface, POINTER(IAudioMeterInformation))
        except Exception:  # noqa: BLE001
            logger.warning("audio meter unavailable — output waveform disabled")
            self._meter = None

    def start(self) -> None:
        """Start polling the audio meter. Idempotent."""
        if self._meter is not None and not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Stop polling. Idempotent."""
        self._timer.stop()
        # Emit zero level so waveform settles
        self.audio_level.emit(0.0)

    def _poll(self) -> None:
        """Read peak level and emit signal."""
        if self._meter is None:
            return
        try:
            level = self._meter.GetPeakValue()
            self.audio_level.emit(min(1.0, max(0.0, level)))
        except Exception:  # noqa: BLE001
            pass
