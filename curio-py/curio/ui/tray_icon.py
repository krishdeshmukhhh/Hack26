"""System tray icon for Curio.

Minimal tray: static icon, context menu with Show Curio / Settings /
Show History / Quit.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from curio.icon_factory import icon_for_state
from curio.pet_config import SPECIES
from curio.state import VoiceState

logger = logging.getLogger(__name__)


class TrayIcon(QSystemTrayIcon):
    """Static system tray icon with Show Curio / Settings / Show History / Quit."""

    show_history_requested = Signal()
    show_memory_requested = Signal()
    show_settings_requested = Signal()
    # "Show Curio" toggled. Off hides the cursor except during an interaction,
    # like the macOS menu bar toggle. Persisted across launches.
    show_cursor_toggled = Signal(bool)
    pet_selected = Signal(str)
    hands_free_toggled = Signal(bool)

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

        self._hands_free_action = QAction('Hands-free: "Hey Curio"', menu)
        self._hands_free_action.setCheckable(True)
        self._hands_free_action.setChecked(self.hands_free_enabled)
        self._hands_free_action.toggled.connect(self._on_hands_free_toggled)
        menu.addAction(self._hands_free_action)

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(lambda: self.show_settings_requested.emit())
        menu.addAction(settings_action)

        history_action = QAction("Show History", menu)
        history_action.triggered.connect(lambda: self.show_history_requested.emit())
        menu.addAction(history_action)

        memory_action = QAction("Memories", menu)
        memory_action.triggered.connect(self.show_memory_requested.emit)
        menu.addAction(memory_action)

        pet_menu = menu.addMenu("Pet")
        self._pet_group = QActionGroup(self)
        self._pet_group.setExclusive(True)
        self._pet_actions: dict[str, QAction] = {}
        for species, label in SPECIES.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(species)
            self._pet_group.addAction(action)
            pet_menu.addAction(action)
            self._pet_actions[species] = action
        self._pet_group.triggered.connect(
            lambda action: self.pet_selected.emit(action.data())
        )
        self.set_selected_pet("fox")

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

    @property
    def hands_free_enabled(self) -> bool:
        return self._settings.value("hands_free", False, type=bool)

    def _on_hands_free_toggled(self, checked: bool) -> None:
        self._settings.setValue("hands_free", checked)
        self.hands_free_toggled.emit(checked)

    def set_hands_free_enabled(self, enabled: bool) -> None:
        self._hands_free_action.setChecked(enabled)

    def set_hands_free_available(self, available: bool) -> None:
        previous = self._hands_free_action.blockSignals(True)
        self._hands_free_action.setChecked(self.hands_free_enabled if available else False)
        self._hands_free_action.blockSignals(previous)
        self._hands_free_action.setEnabled(available)
        self._hands_free_action.setToolTip(
            'Say "Hey Curio", wait, then ask. Say "Curio, send" to finish in background speech.'
            if available else 'Hands-free requires backend = "local" and local Whisper.'
        )

    def set_selected_pet(self, species: str) -> None:
        """Synchronize the menu after loading or persisting a selection."""
        if species in self._pet_actions:
            self._pet_actions[species].setChecked(True)

    def _on_quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()
