"""Shared navigation makes the owner of push-to-talk explicit."""

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from curio.coaching_runtime import CoachingMode
from curio.live_tutoring.widget import TutoringWidget
from curio.tutorial_coach.widget import TutorialCoachWidget


class CoachingWindow(QWidget):
    def __init__(self, runtime, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self._disposed = False
        self.setWindowTitle("Curio - Coaching")
        self.setFont(QFont("Segoe UI", 10))
        self.resize(1100, 850)
        self.setMinimumSize(600, 440)
        layout = QVBoxLayout(self)
        self.mode = QComboBox()
        self.mode.addItem("Ordinary assistant", CoachingMode.ASSISTANT)
        self.mode.addItem("Tutorial URL coach", CoachingMode.TUTORIAL)
        self.mode.addItem("Live integral tutor", CoachingMode.TUTORING)
        layout.addWidget(self.mode)
        self.status = QLabel("Push-to-talk: ordinary assistant")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.pages = QStackedWidget()
        self.pages.addWidget(QLabel("Select a coaching mode, or use the ordinary assistant."))
        self.tutorial = TutorialCoachWidget(runtime.tutorial)
        self.tutorial.buttons["Stop"].clicked.connect(runtime.stop_session)
        self.pages.addWidget(self.tutorial)
        self.tutoring = TutoringWidget(
            runtime.tutor, voice_callback=lambda text, _: runtime.submit_question(text)
        )
        runtime.tutor_reply.connect(self.tutoring._append)
        runtime.error.connect(self.tutoring._append)
        runtime.error.connect(self.status.setText)
        runtime.interrupted.connect(self.tutoring.cancel)
        self.pages.addWidget(self.tutoring)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.pages)
        layout.addWidget(scroll)
        stop = QPushButton("Stop coaching and return to ordinary assistant")
        stop.clicked.connect(runtime.stop_session)
        layout.addWidget(stop)
        self.mode.currentIndexChanged.connect(
            lambda index: runtime.set_mode(self.mode.itemData(index))
        )
        runtime.mode_changed.connect(self._sync)

    def _sync(self, mode):
        index = self.mode.findData(CoachingMode(mode))
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(index)
        self.mode.blockSignals(False)
        self.pages.setCurrentIndex(index)
        self.status.setText(
            f"Push-to-talk: {self.mode.currentText()}. Screenshots require a button action."
        )

    def open_mode(self, mode):
        self.runtime.set_mode(mode)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.runtime.stop_session()
        self.tutoring.cancel()
        super().closeEvent(event)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self.close()
        self.tutorial.close()
        self.tutoring.close()
        self.runtime.tutor_reply.disconnect(self.tutoring._append)
        self.runtime.error.disconnect(self.tutoring._append)
        self.runtime.error.disconnect(self.status.setText)
        self.runtime.interrupted.disconnect(self.tutoring.cancel)
        self.runtime.mode_changed.disconnect(self._sync)

    async def aclose(self):
        self.dispose()
        await self.tutorial.aclose()
        await self.tutoring.aclose()
