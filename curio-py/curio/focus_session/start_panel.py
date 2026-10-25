"""Session start panel: goal, time box, breaks, strict mode and if-then plans.

Section A of docs/focus-learning-research.md. Opened from the tray or after a
spoken "I'm doing X for N minutes" (``prefill``). Suggestions are editable;
each accepted line becomes an ``IfThenPlan``. Emits ``plan_ready(FocusPlan)``.
Async work needs the application's qasync loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from curio.design_system import DS
from curio.focus_contract import BreakStyle, IfThenPlan
from curio.focus_session.planning import (
    DEFAULT_MINUTES,
    build_plan,
    format_if_then,
    parse_if_then_text,
    split_apps,
)

Suggest = Callable[[str], Awaitable[tuple[IfThenPlan, ...]]]


class _IfThenRow(QWidget):
    def __init__(self, plan: IfThenPlan | None = None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.use = QCheckBox()
        self.use.setChecked(True)
        self.use.setAccessibleName("Use this plan")
        self.text = QLineEdit(format_if_then(plan) if plan else "")
        self.text.setPlaceholderText("if I open youtube, then I'll close it and say 'back to it'")
        self.text.setAccessibleName("If-then plan")
        self.apps = QLineEdit(", ".join(plan.cue_apps) if plan else "")
        self.apps.setPlaceholderText("apps it watches")
        self.apps.setAccessibleName("Apps this plan watches for")
        self.apps.setMaximumWidth(150)
        layout.addWidget(self.use)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.apps)

    def plan(self) -> IfThenPlan | None:
        if not self.use.isChecked() or not self.text.text().strip():
            return None
        return parse_if_then_text(self.text.text(), split_apps(self.apps.text()))


class FocusStartPanel(QWidget):
    plan_ready = Signal(object)  # FocusPlan

    def __init__(
        self,
        *,
        suggest: Suggest | None = None,
        foreground_app: Callable[[], str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        parent=None,
    ):
        super().__init__(parent)
        self._suggest = suggest
        self._foreground_app = foreground_app
        self._clock = clock
        self._tasks: set[asyncio.Task] = set()
        self.rows: list[_IfThenRow] = []
        self.setWindowTitle("Curio — Focus session")
        self.setFont(QFont("Segoe UI", 10))
        self.setMinimumWidth(460)
        self.setStyleSheet(
            f"QWidget {{ background: {DS.Colors.panel_bg}; color: {DS.Colors.text_primary}; }}"
            f"QLineEdit, QSpinBox, QComboBox {{ background: {DS.Colors.surface}; }}"
            f"QPushButton {{ padding: 6px 10px; }}"
        )
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("finish the pivot table assignment")
        self.goal.setAccessibleName("Goal")
        form.addRow("What are you working on?", self.goal)
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 240)
        self.minutes.setValue(DEFAULT_MINUTES)
        self.minutes.setSuffix(" min")
        self.minutes.setAccessibleName("Duration")
        form.addRow("For how long?", self.minutes)
        self.break_style = QComboBox()
        self.break_style.addItem("Fixed breaks (25/5)", BreakStyle.FIXED)
        self.break_style.addItem("Suggest breaks when I've gone a while", BreakStyle.SELF_PACED)
        self.break_style.addItem("No breaks", BreakStyle.NONE)
        self.break_style.setAccessibleName("Break style")
        form.addRow("Breaks", self.break_style)
        self.strict = QCheckBox("Strict mode: check in more persistently (never blocks apps)")
        form.addRow("", self.strict)
        self.allowed = QLineEdit()
        self.allowed.setPlaceholderText("excel, chrome")
        self.allowed.setAccessibleName("Allowed apps")
        form.addRow("Apps that count as working", self.allowed)
        layout.addLayout(form)

        layout.addWidget(QLabel("If-then plans (edit them so they sound like you):"))
        self.rows_layout = QVBoxLayout()
        layout.addLayout(self.rows_layout)
        plan_buttons = QHBoxLayout()
        self.suggest_button = QPushButton("Suggest plans")
        self.suggest_button.clicked.connect(self.request_suggestions)
        self.add_button = QPushButton("Add a plan")
        self.add_button.clicked.connect(lambda: self.add_row())
        plan_buttons.addWidget(self.suggest_button)
        plan_buttons.addWidget(self.add_button)
        plan_buttons.addStretch()
        layout.addLayout(plan_buttons)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAccessibleName("Focus start status")
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.close)
        self.start_button = QPushButton("Start session")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        self.suggest_button.setEnabled(suggest is not None)

    def prefill(self, goal: str = "", minutes: int | None = None) -> None:
        """Fresh form for a new session; suggests plans when there's a goal."""
        self.goal.setText(goal)
        self.minutes.setValue(minutes or DEFAULT_MINUTES)
        self.break_style.setCurrentIndex(0)
        self.strict.setChecked(False)
        current = ""
        if self._foreground_app is not None:
            try:
                current = self._foreground_app()
            except Exception:
                current = ""
        self.allowed.setText(current)
        self.set_plans(())
        self.status.setText("")
        if goal.strip():
            self.request_suggestions()

    def add_row(self, plan: IfThenPlan | None = None) -> _IfThenRow:
        row = _IfThenRow(plan)
        self.rows.append(row)
        self.rows_layout.addWidget(row)
        return row

    def set_plans(self, plans) -> None:
        for row in self.rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self.rows = []
        for plan in plans:
            self.add_row(plan)

    def request_suggestions(self) -> None:
        goal = self.goal.text().strip()
        if self._suggest is None:
            return
        if not goal:
            self.status.setText("Say what you're working on first, then I can suggest a plan.")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.status.setText("Suggestions need the application's event loop.")
            return
        self.suggest_button.setEnabled(False)
        self.status.setText("Thinking of a plan…")

        async def run() -> None:
            try:
                plans = await self._suggest(goal)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.status.setText("Couldn't suggest a plan. You can write your own.")
            else:
                kept = [row.plan() for row in self.rows if row.text.text().strip()]
                self.set_plans([p for p in kept if p] + list(plans)[: max(0, 2 - len(kept))])
                self.status.setText("Edit or untick anything that doesn't fit.")
            finally:
                self.suggest_button.setEnabled(True)

        task = loop.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def plans(self) -> tuple[IfThenPlan, ...]:
        return tuple(plan for row in self.rows if (plan := row.plan()) is not None)

    def start(self) -> None:
        unparsed = [
            row for row in self.rows
            if row.use.isChecked() and row.text.text().strip() and row.plan() is None
        ]
        if unparsed:
            self.status.setText("Write each plan as \"if …, then …\", or untick it.")
            return
        try:
            plan = build_plan(
                goal=self.goal.text(),
                minutes=self.minutes.value(),
                if_then=self.plans(),
                allowed_apps=split_apps(self.allowed.text()),
                break_style=self.break_style.currentData(),
                strict=self.strict.isChecked(),
                now=self._clock(),
            )
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.plan_ready.emit(plan)
        self.close()

    def closeEvent(self, event) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        super().closeEvent(event)
