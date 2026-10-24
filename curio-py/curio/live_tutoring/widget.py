"""Embeddable Qt workspace. Host supplies voice and async capture adapters."""

import asyncio

from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .service import TutoringService


class TutoringWidget(QWidget):
    def __init__(self, service=None, *, voice_callback=None, parent=None):
        super().__init__(parent)
        self.service = service or TutoringService()
        self.voice_callback = voice_callback
        self._task = None
        self._tasks = set()
        self.setWindowTitle("Curio live tutor")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Integrate a polynomial in x. Use * for multiplication."))
        layout.addWidget(QLabel(self.service.domain))
        self.problem = QLineEdit()
        self.problem.setPlaceholderText("2*x*(x^2+1)^2")
        layout.addWidget(self.problem)
        self.start_button = QPushButton("Start problem")
        layout.addWidget(self.start_button)
        self.workspace = QTextEdit()
        self.workspace.setReadOnly(True)
        layout.addWidget(self.workspace)
        self.progress = QLabel(self.service.progress_message)
        self.progress.setWordWrap(True)
        layout.addWidget(self.progress)
        self.step = QLineEdit()
        self.step.setPlaceholderText("u=x^2+1; submit one equation at a time")
        layout.addWidget(self.step)
        self.submit_button = QPushButton("Submit step")
        layout.addWidget(self.submit_button)
        self.help_button = QPushButton("Hint / explanation / worked step")
        layout.addWidget(self.help_button)
        self.practice_button = QPushButton("Start related unassisted problem")
        self.practice_button.setEnabled(False)
        layout.addWidget(self.practice_button)
        self.practice_button.clicked.connect(self._start_practice)
        self.capture_button = QPushButton("Capture equation (share screen)")
        self.capture_button.setEnabled(service is not None and service.capture is not None)
        layout.addWidget(self.capture_button)
        self.recognized = QLineEdit()
        self.recognized.setPlaceholderText("Review and correct recognized equation here")
        layout.addWidget(self.recognized)
        self.confirm_button = QPushButton("Confirm recognized equation and assess")
        self.confirm_button.setEnabled(False)
        layout.addWidget(self.confirm_button)
        self.question = QLineEdit()
        self.question.setPlaceholderText("Voice transcript or typed question")
        layout.addWidget(self.question)
        self.voice_button = QPushButton("Ask tutor")
        layout.addWidget(self.voice_button)
        self.understanding = QLineEdit()
        self.understanding.setPlaceholderText("Understanding check: enter u'(x), without dx")
        layout.addWidget(self.understanding)
        self.check_button = QPushButton("Check understanding")
        layout.addWidget(self.check_button)
        self.cancel_button = QPushButton("Cancel pending input")
        layout.addWidget(self.cancel_button)
        self.start_button.clicked.connect(self._start)
        self.submit_button.clicked.connect(lambda: self._submit(False))
        self.step.returnPressed.connect(lambda: self._submit(False))
        self.confirm_button.clicked.connect(lambda: self._submit(True))
        self.help_button.clicked.connect(lambda: self._run(self.service.help))
        self.capture_button.clicked.connect(self._capture)
        self.voice_button.clicked.connect(lambda: self.submit_voice_question(self.question.text()))
        self.check_button.clicked.connect(
            lambda: self._run(lambda: self.service.check_understanding(self.understanding.text()))
        )
        self.cancel_button.clicked.connect(self.cancel)

    def _append(self, text):
        # Plain text prevents recognized/provider content from injecting HTML.
        self.workspace.insertPlainText(str(text) + "\n")

    def _run(self, operation):
        try:
            result = operation()
            if hasattr(result, "status"):
                self._append(f"{result.status.value.replace('_', ' ')}: {result.message}")
            else:
                self._append(result)
        except Exception as exc:
            self._append(f"Unable to proceed: {exc}")

    def _start(self):
        def start():
            self.service.start(self.problem.text())
            self.cancel()
            self.workspace.clear()
            self._sync_practice()
            return f"Problem: integral of {self.service.problem} dx"

        self._run(start)

    def _sync_practice(self):
        self.progress.setText(self.service.progress_message)
        self.practice_button.setEnabled(self.service.complete)
        self.help_button.setEnabled(not self.service.unassisted)
        self.voice_button.setEnabled(not self.service.unassisted)
        self.check_button.setEnabled(not self.service.unassisted)

    def _start_practice(self):
        def start():
            self.service.start_practice()
            self.cancel()
            self.problem.setText(self.service.problem)
            self.step.clear()
            self._sync_practice()
            return f"Unassisted practice: integrate {self.service.problem} dx. Submit F=...+C."

        self._run(start)

    def _submit(self, confirmed):
        def submit():
            text = self.recognized.text() if confirmed else self.step.text()
            feedback = (
                self.service.confirm_equation(text) if confirmed else self.service.submit(text)
            )
            self._append(f"Attempt: {text}")
            self._sync_practice()
            if confirmed:
                self.confirm_button.setEnabled(False)
            return feedback

        self._run(submit)

    def submit_voice_question(self, transcript):
        """Connect a host's final_transcript signal here; questions never become steps."""
        if not transcript.strip():
            return
        if self.service.unassisted:
            self._append("Voice coaching is unavailable during unassisted practice.")
            return
        self._append(f"Question: {transcript}")
        if self.voice_callback is None:
            self._append("No voice question callback configured. " + self.service.help())
        else:
            self._run(lambda: self.voice_callback(transcript, self.service))

    def _capture(self):
        self.cancel()

        async def capture():
            try:
                text = await self.service.capture_equations()
                if text is not None:
                    self.recognized.setText(text)
                    self.confirm_button.setEnabled(True)
                    self._append("Review the recognized equation, then explicitly confirm it.")
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                self._append(f"Capture failed: {exc}")

        try:
            self._task = asyncio.get_running_loop().create_task(capture())
            self._tasks.add(self._task)
            self._task.add_done_callback(self._tasks.discard)
        except RuntimeError:
            self._append("Capture requires the host's running qasync event loop.")

    def cancel(self):
        self.service.cancel()
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.confirm_button.setEnabled(False)
        self.recognized.clear()

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)

    async def aclose(self):
        self.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
