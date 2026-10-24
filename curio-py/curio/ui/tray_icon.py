"""System tray icon for Curio.

Minimal tray: static icon, context menu with Settings / Show History / Quit.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from curio.icon_factory import icon_for_state
from curio.state import VoiceState

logger = logging.getLogger(__name__)


class TrayIcon(QSystemTrayIcon):
    """Static system tray icon with Settings / Show History / Quit menu."""

    show_history_requested = Signal()
    show_settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        # Static idle icon — no state changes
        self.setIcon(icon_for_state(VoiceState.IDLE))
        self.setToolTip("Curio")

        menu = QMenu()

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(lambda: self.show_settings_requested.emit())
        menu.addAction(settings_action)

        history_action = QAction("Show History", menu)
        history_action.triggered.connect(lambda: self.show_history_requested.emit())
        menu.addAction(history_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._on_quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _on_quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()
