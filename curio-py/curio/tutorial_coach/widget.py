"""Injectable Qt surface. Requires the application's existing qasync event loop."""

from __future__ import annotations

import asyncio

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from curio.coaching_contract import OperationCancelled

from .coach import Coach
from .content import CoachError
from .files import FILE_FILTER


class TutorialCoachWidget(QWidget):
    """Owns its UI tasks, but does not own provider, capture or audio clients.

    The Check screen button authorizes ONE capture. No background captures,
    link opening, model actions, automatic completion or persistent storage.
    """

    def __init__(self, coach: Coach, parent=None):
        super().__init__(parent)
        self.coach = coach
        self._tasks = set()
        self._rendering = False
        self._closed = False
        self.url = QLineEdit()
        self.url.setPlaceholderText("Public tutorial URL")
        self.video = QCheckBox("Video URL (requires actual transcript)")
        self.transcript = QTextEdit()
        self.transcript.setPlaceholderText("Optional: paste actual transcript (no video inference)")
        self.transcript.setMaximumHeight(100)
        self.preview = QPushButton("Preview plan")
        self.upload = QPushButton("Choose tutorial file and preview...")
        self.upload.setToolTip(
            "TXT, Markdown, HTML or text-based PDF. Extracted text is sent to the configured model."
        )
        self.upload.clicked.connect(self._choose_file)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Instruction (editable)", "Expected result (editable)", "Source references"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellChanged.connect(self._edited)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.question = QLineEdit()
        self.question.setPlaceholderText("Ask about this step or describe what went wrong")
        self.buttons = {}
        layout = QVBoxLayout(self)
        for widget in (
            self.url,
            self.video,
            self.transcript,
            self.preview,
            self.upload,
            self.table,
        ):
            layout.addWidget(widget)
        order = QHBoxLayout()
        for label, delta in [("Move up", -1), ("Move down", 1)]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, d=delta: self._move(d))
            order.addWidget(button)
            self.buttons[label] = button
        remove = QPushButton("Remove step")
        remove.clicked.connect(
            lambda: self._sync(lambda: coach.remove_step(self.table.currentRow()))
        )
        self.buttons["Remove step"] = remove
        order.addWidget(remove)
        layout.addLayout(order)
        controls = QHBoxLayout()
        for label, callback in [
            ("Start", coach.start),
            ("Pause", coach.pause),
            ("Resume", coach.resume),
            ("Repeat", coach.repeat),
            ("Skip", coach.skip),
            ("Stop", coach.stop),
            ("I completed it", coach.confirm),
            ("Use screen verification", coach.accept_verified),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, cb=callback: self._sync(cb))
            controls.addWidget(button)
            self.buttons[label] = button
        layout.addLayout(controls)
        layout.addWidget(self.status)
        layout.addWidget(self.output)
        layout.addWidget(self.question)
        actions = QHBoxLayout()
        for label, callback in [
            ("Ask", lambda: coach.ask(self.question.text())),
            ("Explain this", coach.explain),
            ("That didn't work", lambda: coach.recover(self.question.text())),
            ("Check screen (share now)", lambda: coach.check_screen(authorized=True)),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, cb=callback: self._launch(cb))
            actions.addWidget(button)
            self.buttons[label] = button
        layout.addLayout(actions)
        self.preview.clicked.connect(
            lambda: self._launch(
                lambda: coach.prepare(
                    self.url.text(),
                    transcript=self.transcript.toPlainText() or None,
                    video=self.video.isChecked(),
                )
            )
        )
        self.question.returnPressed.connect(
            lambda: self._launch(lambda: coach.ask(self.question.text()))
        )
        coach.changed.connect(self.refresh)
        coach.response.connect(self.output.setPlainText)
        self.refresh()

    def _choose_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Choose tutorial document", "", FILE_FILTER)
        if filename:
            self._launch(lambda: self.coach.prepare_file(filename))

    def _sync(self, callback):
        try:
            callback()
        except CoachError as exc:
            self.output.setPlainText(str(exc))

    def _launch(self, callback):
        async def run():
            try:
                await callback()
            except (asyncio.CancelledError, OperationCancelled):
                pass
            except Exception as exc:
                self.output.setPlainText(str(exc))

        try:
            task = asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            self.output.setPlainText("Tutorial coach requires the application qasync event loop.")
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _move(self, delta):
        row = self.table.currentRow()
        self._sync(lambda: self.coach.move_step(row, row + delta))

    def _edited(self, row, column):
        if self._rendering or column == 2:
            return
        self._sync(
            lambda: self.coach.edit_step(
                row, self.table.item(row, 0).text(), self.table.item(row, 1).text()
            )
        )

    def refresh(self):
        coach = self.coach
        editable = coach.state not in ("active", "paused") and not coach.busy
        self.preview.setEnabled(editable)
        self.upload.setEnabled(editable)
        steps = coach.plan.steps if coach.plan else ()
        self._rendering = True
        selected = self.table.currentRow()
        self.table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            sources = "\n".join(f"[{b.id}] {b.url}\n{b.text}" for b in step.sources)
            for col, text in enumerate((step.instruction, step.expected, sources)):
                item = QTableWidgetItem(text)
                if col == 2 or not editable:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
        self._rendering = False
        if 0 <= selected < len(steps):
            self.table.selectRow(selected)
        active = coach.state == "active"
        for label in ("Move up", "Move down", "Remove step"):
            self.buttons[label].setEnabled(editable and bool(steps))
        self.buttons["Start"].setEnabled(editable and bool(steps))
        self.buttons["Resume"].setEnabled(coach.state == "paused")
        for label in ("Pause", "Repeat", "Skip", "I completed it"):
            self.buttons[label].setEnabled(active)
        for label in ("Ask", "Explain this", "That didn't work", "Check screen (share now)"):
            self.buttons[label].setEnabled(active and not coach.busy)
        self.buttons["Check screen (share now)"].setEnabled(
            active and not coach.busy and coach.capture is not None
        )
        self.buttons["Use screen verification"].setEnabled(
            active
            and not coach.busy
            and coach.assessment is not None
            and coach.assessment.status == "verified"
        )
        assessment = f" | Screen: {coach.assessment.status}" if coach.assessment else ""
        progress = ", ".join(f"{i + 1}: {status}" for i, status in coach.completions.items())
        self.status.setText(
            f"{coach.state} | Step {min(coach.index + 1, len(steps))}/{len(steps)}"
            f"{' | Working…' if coach.busy else ''}{assessment}\n{progress}"
        )

    def closeEvent(self, event):
        if self._closed:
            super().closeEvent(event)
            return
        self._closed = True
        self.coach.stop()
        for task in tuple(self._tasks):
            task.cancel()
        self.coach.changed.disconnect(self.refresh)
        self.coach.response.disconnect(self.output.setPlainText)
        super().closeEvent(event)

    async def aclose(self):
        self.close()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
