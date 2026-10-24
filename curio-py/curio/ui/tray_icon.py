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
    # Lab mode: the student says they're stuck (or not), or picks their step.
    lab_stuck_toggled = Signal(bool)
    lab_step_selected = Signal(int)

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

        # Lab mode menu; hidden unless [lab] is enabled.
        self._lab_menu = menu.addMenu("Lab")
        self._lab_status = QAction("Connecting to the lab...", self)
        self._lab_status.setEnabled(False)
        self._lab_menu.addAction(self._lab_status)
        self._lab_stuck = QAction("I'm stuck (tell the TA)", self)
        self._lab_stuck.setCheckable(True)
        self._lab_stuck.triggered.connect(self.lab_stuck_toggled.emit)
        self._lab_menu.addAction(self._lab_stuck)
        self._lab_steps_menu = self._lab_menu.addMenu("I'm on step")
        self._lab_step_group = QActionGroup(self)
        self._lab_step_group.setExclusive(True)
        self._lab_step_group.triggered.connect(
            lambda action: self.lab_step_selected.emit(action.data())
        )
        self._lab_step_titles: tuple[str, ...] = ()
        self._lab_menu.menuAction().setVisible(False)

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

    def set_selected_pet(self, species: str) -> None:
        """Synchronize the menu after loading or persisting a selection."""
        if species in self._pet_actions:
            self._pet_actions[species].setChecked(True)

    def set_lab_enabled(self, enabled: bool) -> None:
        self._lab_menu.menuAction().setVisible(enabled)

    def update_lab(
        self,
        steps: list[tuple[int, str]],
        step: int,
        stuck: bool,
        *,
        connected: bool,
        error: str = "",
    ) -> None:
        """Refresh the Lab menu from the student's lab state."""
        if not connected:
            status = f"Lab: not connected ({error})" if error else "Lab: connecting..."
            self._lab_status.setText(status)
        elif stuck:
            self._lab_status.setText(f"Lab: step {step or '?'} - your TA can see you're stuck")
        else:
            self._lab_status.setText(f"Lab: step {step}" if step else "Lab: connected")
        self._lab_stuck.setChecked(stuck)
        titles = tuple(f"{index}. {title}" for index, title in steps)
        if titles != self._lab_step_titles:
            self._lab_step_titles = titles
            self._lab_steps_menu.clear()
            for action in self._lab_step_group.actions():
                self._lab_step_group.removeAction(action)
            for (index, _), text in zip(steps, titles, strict=True):
                action = QAction(text, self)
                action.setCheckable(True)
                action.setData(index)
                self._lab_step_group.addAction(action)
                self._lab_steps_menu.addAction(action)
        self._lab_steps_menu.setEnabled(bool(steps))
        for action in self._lab_step_group.actions():
            action.setChecked(action.data() == step)

    def _on_quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()
