"""System tray icon for Curio.

Minimal tray: static icon, context menu with Show Curio / Settings /
Show History / Quit.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from curio.icon_factory import icon_for_state
from curio.state import VoiceState

logger = logging.getLogger(__name__)


class TrayIcon(QSystemTrayIcon):
    """Static system tray icon with Show Curio / Settings / Show History / Quit."""

    show_history_requested = Signal()
    show_settings_requested = Signal()
    # "Show Curio" toggled. Off hides the cursor except during an interaction,
    # like the macOS menu bar toggle. Persisted across launches.
    show_cursor_toggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        # Static idle icon — no state changes
        self.setIcon(icon_for_state(VoiceState.IDLE))
        self.setToolTip("Curio")

        menu = QMenu()

        self._settings = QSettings("Curio", "Curio")
        self._show_cursor_action = QAction("Show Curio", menu)
        self._show_cursor_action.setCheckable(True)
        self._show_cursor_action.setChecked(self.show_cursor)
        self._show_cursor_action.toggled.connect(self._on_show_cursor_toggled)
        menu.addAction(self._show_cursor_action)

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

    @property
    def show_cursor(self) -> bool:
        return self._settings.value("show_cursor", True, type=bool)

    def _on_show_cursor_toggled(self, checked: bool) -> None:
        self._settings.setValue("show_cursor", checked)
        self.show_cursor_toggled.emit(checked)

    def _on_quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()
