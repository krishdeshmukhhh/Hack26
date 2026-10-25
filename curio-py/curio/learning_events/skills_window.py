"""Placeholder "Skills…" window: a plain list of the skill model's snapshot.

Replaced by the skill model's own widget once that branch is merged.
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget

from curio.learning_contract import SkillModel, SkillState

logger = logging.getLogger(__name__)


def describe_skill(state: SkillState) -> str:
    apps = f" ({', '.join(state.apps)})" if state.apps else ""
    tries = "try" if state.attempts == 1 else "tries"
    return f"{state.concept}{apps}: {round(state.mastery * 100)}% after {state.attempts} {tries}"


class SkillsWindow(QWidget):
    def __init__(self, skill_model: SkillModel, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Curio skills")
        self.resize(360, 420)
        self._skill_model = skill_model
        self._status = QLabel("Loading…")
        self._list = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addWidget(self._list)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        asyncio.ensure_future(self.refresh())

    async def refresh(self) -> None:
        try:
            states = await self._skill_model.snapshot()
        except Exception:  # noqa: BLE001
            logger.exception("skills window: snapshot failed")
            self._status.setText("Couldn't load skills.")
            return
        self.set_states(states)

    def set_states(self, states: tuple[SkillState, ...]) -> None:
        self._list.clear()
        ordered = sorted(states, key=lambda s: (-s.mastery, s.concept))
        for state in ordered:
            self._list.addItem(describe_skill(state))
        self._status.setText(
            "Skills from your walkthroughs:" if ordered
            else "No skills yet. Finish a guided walkthrough and they'll show up here."
        )
