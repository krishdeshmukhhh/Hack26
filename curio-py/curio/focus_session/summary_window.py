"""End-of-session card: totals, one-line reflection, review quiz (sections F, G).

The quiz is the session's REVIEW step: two or three retrieval questions from
the study coach. The learner answers (in their head or typed), then sees the
answer and marks themselves, so feedback always follows the attempt. The
summary was saved when the session ended; "Done" saves it again with the
reflection. ``runtime`` is a FocusRuntime; async work needs the qasync loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from curio.design_system import DS
from curio.focus_contract import ReviewItem, SessionSummary
from curio.focus_session.session_window import minutes_text

REFLECTION_PROMPT = "What got in the way today? (optional)"


def next_review_text(due: datetime, now: datetime) -> str:
    """'later today', 'tomorrow', 'on Tuesday' or 'on 12 Nov', in local time."""
    local_due, local_now = due.astimezone(), now.astimezone()
    days = (local_due.date() - local_now.date()).days
    if days <= 0:
        return "later today"
    if days == 1:
        return "tomorrow"
    if days < 7:
        return f"on {local_due:%A}"
    return f"on {local_due.day} {local_due:%b}"


def summary_lines(summary: SessionSummary) -> list[str]:
    lines = [
        f"On goal: {minutes_text(summary.on_goal_seconds)}",
        f"Drifting: {minutes_text(summary.off_goal_seconds)} "
        f"({summary.drift_count} {'time' if summary.drift_count == 1 else 'times'})",
    ]
    if summary.break_seconds:
        lines.append(f"Breaks: {minutes_text(summary.break_seconds)}")
    if summary.false_alarms:
        lines.append(
            f"Check-ins you said weren't distractions: {summary.false_alarms} "
            "(Curio will remember those)"
        )
    return lines


class SessionSummaryWindow(QWidget):
    done = Signal(object)  # SessionSummary with reflection

    def __init__(
        self,
        runtime,
        *,
        speak: Callable[[str], None] | None = None,
        clock: Callable[[], datetime] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.runtime = runtime
        self._speak = speak
        self._clock = clock or (lambda: datetime.now(UTC))
        self._tasks: set[asyncio.Task] = set()
        self.summary: SessionSummary | None = None
        self.items: list[ReviewItem] = []
        self.index = 0
        self.next_due: datetime | None = None
        self.next_concept = ""
        self.setWindowTitle("Curio — Session summary")
        self.setFont(QFont("Segoe UI", 10))
        self.setMinimumWidth(420)
        self.setStyleSheet(
            f"QWidget {{ background: {DS.Colors.panel_bg}; color: {DS.Colors.text_primary}; }}"
            f"QLineEdit {{ background: {DS.Colors.surface}; }}"
            f"QPushButton {{ padding: 6px 10px; }}"
        )
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setStyleSheet(f"font-size: {DS.Fonts.size_lg}px;")
        layout.addWidget(self.title)
        self.card = QLabel()
        self.card.setWordWrap(True)
        self.card.setTextFormat(Qt.TextFormat.PlainText)
        self.card.setAccessibleName("Session totals")
        layout.addWidget(self.card)
        layout.addWidget(QLabel(REFLECTION_PROMPT))
        self.reflection = QLineEdit()
        self.reflection.setMaxLength(280)
        self.reflection.setAccessibleName("Reflection")
        layout.addWidget(self.reflection)

        self.quiz = QWidget()
        quiz = QVBoxLayout(self.quiz)
        quiz.setContentsMargins(0, DS.Spacing.sm, 0, 0)
        self.quiz_heading = QLabel()
        quiz.addWidget(self.quiz_heading)
        self.question = QLabel()
        self.question.setWordWrap(True)
        self.question.setTextFormat(Qt.TextFormat.PlainText)
        quiz.addWidget(self.question)
        self.attempt = QLineEdit()
        self.attempt.setPlaceholderText("Your answer (or just think it)")
        self.attempt.setAccessibleName("Your answer")
        self.attempt.returnPressed.connect(self.reveal)
        quiz.addWidget(self.attempt)
        self.answer = QLabel()
        self.answer.setWordWrap(True)
        self.answer.setTextFormat(Qt.TextFormat.PlainText)
        self.answer.setStyleSheet(f"color: {DS.Colors.accent_green};")
        quiz.addWidget(self.answer)
        row = QHBoxLayout()
        self.reveal_button = QPushButton("Show answer")
        self.reveal_button.clicked.connect(self.reveal)
        self.right_button = QPushButton("I got it")
        self.right_button.clicked.connect(lambda: self.mark(True))
        self.wrong_button = QPushButton("Not quite")
        self.wrong_button.clicked.connect(lambda: self.mark(False))
        for button in (self.reveal_button, self.right_button, self.wrong_button):
            row.addWidget(button)
        row.addStretch()
        quiz.addLayout(row)
        layout.addWidget(self.quiz)
        self.next_review = QLabel()
        self.next_review.setWordWrap(True)
        self.next_review.setAccessibleName("Next review")
        layout.addWidget(self.next_review)
        actions = QHBoxLayout()
        actions.addStretch()
        self.done_button = QPushButton("Done")
        self.done_button.clicked.connect(self.finish)
        actions.addWidget(self.done_button)
        layout.addLayout(actions)
        self.quiz.hide()
        runtime.session_ended.connect(self.show_summary)

    # --- summary ----------------------------------------------------------------

    def show_summary(self, summary: SessionSummary) -> None:
        self.summary = summary
        self.title.setText(f"Session done: {summary.goal}")
        self.card.setText("\n".join(summary_lines(summary)))
        self.reflection.setText(summary.reflection)
        self.items, self.index, self.next_due = [], 0, None
        self.quiz.hide()
        self.next_review.setText("")
        self.show()
        self.raise_()
        self._spawn(self._load_reviews())

    def _spawn(self, coro) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        task = loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _load_reviews(self) -> None:
        items = await self.runtime.review_items()
        self.set_items(items)

    def set_items(self, items) -> None:
        self.items, self.index = list(items), 0
        if not self.items:
            self.quiz.hide()
            return
        count = len(self.items)
        self.quiz_heading.setText(
            f"Quick review: {count} question{'s' if count != 1 else ''} on today's work."
        )
        self.quiz.show()
        self._show_question()

    # --- quiz -------------------------------------------------------------------

    def _show_question(self) -> None:
        item = self.items[self.index]
        self.question.setText(f"{self.index + 1}. {item.question}")
        self.attempt.clear()
        self.attempt.setEnabled(True)
        self.attempt.show()
        self.answer.setText("")
        self.reveal_button.setEnabled(True)
        self.right_button.setEnabled(False)
        self.wrong_button.setEnabled(False)
        if self._speak is not None:
            self._speak(item.question)

    def reveal(self) -> None:
        if self.index >= len(self.items) or not self.reveal_button.isEnabled():
            return
        self.answer.setText(f"Answer: {self.items[self.index].answer}")
        self.attempt.setEnabled(False)
        self.reveal_button.setEnabled(False)
        self.right_button.setEnabled(True)
        self.wrong_button.setEnabled(True)

    def mark(self, correct: bool) -> None:
        if self.index >= len(self.items) or not self.right_button.isEnabled():
            return
        item = self.items[self.index]
        self.right_button.setEnabled(False)
        self.wrong_button.setEnabled(False)
        self._spawn(self._record(item, correct))

    async def _record(self, item: ReviewItem, correct: bool) -> None:
        updated = await self.runtime.record_review(item, correct)
        if updated is not None and (self.next_due is None or updated.due_at < self.next_due):
            self.next_due, self.next_concept = updated.due_at, updated.concept
        self.index += 1
        if self.index < len(self.items):
            self._show_question()
            return
        self.question.setText("That's the review done.")
        self.attempt.hide()
        self.answer.setText("")
        self.reveal_button.setEnabled(False)
        if self.next_due is not None:
            when = next_review_text(self.next_due, self._clock())
            self.next_review.setText(f"I'll ask you about {self.next_concept} again {when}.")

    # --- done -------------------------------------------------------------------

    def finish(self) -> None:
        summary = self.summary
        if summary is None:
            self.close()
            return
        reflection = " ".join(self.reflection.text().split())[:280]
        final = replace(summary, reflection=reflection)
        self.summary = None
        if reflection != summary.reflection:
            self._spawn(self.runtime.save(final))
        self.runtime.finish()
        self.done.emit(final)
        self.close()

    def closeEvent(self, event) -> None:
        if self.summary is not None:
            self.finish()
            return
        super().closeEvent(event)

    def dispose(self) -> None:
        self.runtime.session_ended.disconnect(self.show_summary)
        for task in tuple(self._tasks):
            task.cancel()
        self.close()
