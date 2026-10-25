"""Keyboard "step done" detection for guided walkthroughs.

Steps like "type 'dark mode' in the search box" have no click to wait for. While
a step is armed this watcher finishes it when the user presses Enter, or when
they have typed a few printable keys and then paused.

It taps the keyboard hook ``HotkeyMonitor`` already owns (no second global
hook); the monitor filters out Ctrl/Alt/Win chords and push-to-talk keys.
Privacy: only a count and timestamps are kept, never which keys were typed.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

# Printable keys needed before an idle pause counts as "finished typing".
TYPING_MIN_KEYS = 2
# Seconds without a key, after typing, before the step counts as done.
TYPING_IDLE_SECONDS = 2.0
_POLL_MS = 250


class KeyFinishWatcher(QObject):
    """Emits ``finished`` once per arming when the keyboard says the step is done."""

    finished = Signal()

    def __init__(
        self,
        hotkey: QObject,
        parent: QObject | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._clock = clock
        self._armed = False
        self._count = 0
        self._last_key_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self.tick)
        hotkey.typing_enter.connect(self._on_enter)
        hotkey.typing_printable.connect(self._on_printable)

    @property
    def active(self) -> bool:
        return self._armed

    def start(self) -> None:
        """Arm for a new step (fresh count). Idempotent apart from resetting."""
        self._armed = True
        self._count = 0
        self._hotkey.typing_tap_enabled = True
        self._timer.start()

    def stop(self) -> None:
        self._armed = False
        self._count = 0
        self._hotkey.typing_tap_enabled = False
        self._timer.stop()

    def _on_enter(self) -> None:
        if self._armed:
            self._finish()

    def _on_printable(self) -> None:
        if self._armed:
            self._count += 1
            self._last_key_at = self._clock()

    def tick(self) -> None:
        if (
            self._armed
            and self._count >= TYPING_MIN_KEYS
            and self._clock() - self._last_key_at >= TYPING_IDLE_SECONDS
        ):
            self._finish()

    def _finish(self) -> None:
        self.stop()
        self.finished.emit()
