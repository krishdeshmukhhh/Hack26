"""Global left-click detection for guided walkthroughs.

While a walkthrough waits on a step, Curio watches for the user's next
left click anywhere on screen, which is taken to mean "I did that step".
Same threading pattern as ``hotkey.py``: pynput calls back on its own
thread, and the signal is marshalled onto the Qt main thread.
"""

from __future__ import annotations

import logging

from pynput import mouse
from PySide6.QtCore import QMetaObject, QObject, Qt, Signal, Slot

logger = logging.getLogger(__name__)


class ClickWatcher(QObject):
    """Emits ``clicked`` on each left-button press while started."""

    clicked = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener: mouse.Listener | None = None

    @property
    def active(self) -> bool:
        return self._listener is not None

    def start(self) -> None:
        """Start watching. Idempotent."""
        if self._listener is not None:
            return
        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.start()

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()

    # Runs on pynput's thread.
    def _on_click(self, _x: int, _y: int, button: mouse.Button, pressed: bool) -> None:
        if pressed and button == mouse.Button.left:
            QMetaObject.invokeMethod(self, "_emit_clicked", Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _emit_clicked(self) -> None:
        if self._listener is not None:
            self.clicked.emit()
