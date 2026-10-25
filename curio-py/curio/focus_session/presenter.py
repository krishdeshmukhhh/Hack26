"""Shows interventions: pet animation, existing TTS and a small choice bubble.

Presentation only (section H): the pet is company, never a proven focus aid,
and never sulks. AMBIENT_CUE is animation alone, with no sound. Spoken kinds
use the injected ``speak`` plus a bubble near the pet with the intervention's
choices and a "why?" link; a click or a spoken choice records the response,
and expiry records IGNORED. Construct on the Qt thread.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from curio.design_system import DS
from curio.focus_contract import (
    FocusSignal,
    Intervention,
    InterventionKind,
    InterventionResponse,
    SignalKind,
)
from curio.focus_session.rationale import why_text

Cancel = Callable[[], None]
# (seconds, callback) -> cancel. Injected so tests control expiry.
Schedule = Callable[[float, Callable[[], None]], Cancel]
Responder = Callable[[Intervention, InterventionResponse], None]

_FALSE_ALARM_RE = re.compile(
    r"not a distraction|wasn'?t a distraction|on task|it'?s for (work|study)"
)
_SNOOZE_RE = re.compile(r"snooze|later|not now|in a bit|give me|few minutes")
_DISMISS_RE = re.compile(r"keep going|no thanks|dismiss|skip|i'?m fine|all good|not yet")
_WORD_RE = re.compile(r"[a-z0-9']+")
_FILLER = {"a", "an", "the", "to", "it", "i", "uh", "um", "please", "ok", "yeah"}
DEFAULT_CHOICE = "okay"


def response_for_choice(choice: str) -> InterventionResponse:
    """Map a choice label to the response the policy learns from."""
    text = choice.lower()
    if _FALSE_ALARM_RE.search(text):
        return InterventionResponse.FALSE_ALARM
    if _SNOOZE_RE.search(text):
        return InterventionResponse.SNOOZED
    if _DISMISS_RE.search(text):
        return InterventionResponse.DISMISSED
    return InterventionResponse.ACCEPTED


def match_spoken_choice(text: str, choices: tuple[str, ...]) -> str | None:
    """The choice a spoken reply names, by exact phrase first, then word overlap."""
    spoken = " ".join(_WORD_RE.findall(text.lower()))
    if not spoken:
        return None
    for choice in sorted(choices, key=len, reverse=True):
        if " ".join(_WORD_RE.findall(choice.lower())) in spoken:
            return choice
    words = set(spoken.split()) - _FILLER
    best, best_score = None, 0.0
    for choice in choices:
        choice_words = set(_WORD_RE.findall(choice.lower())) - _FILLER
        if not choice_words:
            continue
        score = len(words & choice_words) / len(choice_words)
        if score > best_score:
            best, best_score = choice, score
    return best if best_score >= 0.5 else None


def qt_schedule(seconds: float, callback: Callable[[], None]) -> Cancel:
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(callback)
    timer.start(max(0, int(seconds * 1000)))
    return timer.stop


class PetActions(Protocol):
    def look_at_learner(self) -> None: ...

    def happy(self) -> None: ...

    def nap(self) -> None: ...

    def stretch(self) -> None: ...

    def wake(self) -> None: ...


class PetWidgetActions:
    """Drive ``PetCompanionWidget`` with clips it already has.

    The behaviour controller has no public "play this clip" call yet, so this
    uses ``_start_optional`` when present and does nothing otherwise (the
    triangle fallback has no clips). Final wiring should add a public method.
    """

    NAP_REPEAT_MS = 2500

    def __init__(self, widget) -> None:
        self._widget = widget
        self._nap = QTimer()
        self._nap.setInterval(self.NAP_REPEAT_MS)
        self._nap.timeout.connect(lambda: self._play("sleep"))

    def _play(self, action: str) -> None:
        controller = getattr(self._widget, "controller", None)
        play = getattr(controller, "_start_optional", None)
        if getattr(self._widget, "catalog", None) is not None and play is not None:
            play(action)

    def look_at_learner(self) -> None:
        self._play("attentive")

    def happy(self) -> None:
        self.wake()
        self._play("jump")

    def nap(self) -> None:
        self._play("settle")
        self._nap.start()

    def stretch(self) -> None:
        self.wake()
        self._play("wake")

    def wake(self) -> None:
        self._nap.stop()


class ChoiceBubble(QWidget):
    """Small always-on-top card beside the pet. Never takes keyboard focus."""

    chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFont(QFont("Segoe UI", 10))
        self.setMaximumWidth(340)
        self.setStyleSheet(
            f"QWidget {{ background: {DS.Colors.panel_bg}; color: {DS.Colors.text_primary}; }}"
            f"QPushButton {{ background: {DS.Colors.surface}; border: 1px solid "
            f"{DS.Colors.border}; border-radius: {DS.CornerRadius.small}px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ border-color: {DS.Colors.accent_blue}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(DS.Spacing.md, DS.Spacing.sm, DS.Spacing.md, DS.Spacing.sm)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.message)
        self.choice_row = QHBoxLayout()
        layout.addLayout(self.choice_row)
        self.why_link = QLabel(f'<a href="why" style="color:{DS.Colors.accent_blue}">why?</a>')
        self.why_link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.why_link.linkActivated.connect(self.toggle_why)
        layout.addWidget(self.why_link)
        self.why = QLabel()
        self.why.setWordWrap(True)
        self.why.setTextFormat(Qt.TextFormat.PlainText)
        self.why.setStyleSheet(f"color: {DS.Colors.text_secondary};")
        self.why.hide()
        layout.addWidget(self.why)
        self.buttons: list[QPushButton] = []

    def show_intervention(self, intervention: Intervention, anchor: QPoint | None) -> None:
        self.message.setText(intervention.message)
        self.why.setText(why_text(intervention.rationale))
        self.why.hide()
        for button in self.buttons:
            self.choice_row.removeWidget(button)
            button.deleteLater()
        self.buttons = []
        for choice in intervention.choices or (DEFAULT_CHOICE,):
            button = QPushButton(choice)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, c=choice: self.chosen.emit(c))
            self.choice_row.addWidget(button)
            self.buttons.append(button)
        self.adjustSize()
        self.move(self._position(anchor))
        self.show()

    def toggle_why(self, _link: str = "") -> None:
        self.why.setVisible(not self.why.isVisible())
        self.adjustSize()

    def _position(self, anchor: QPoint | None) -> QPoint:
        screen = QGuiApplication.screenAt(anchor) if anchor else QGuiApplication.primaryScreen()
        if screen is None:
            return anchor or QPoint(0, 0)
        geo = screen.availableGeometry()
        if anchor is None:
            anchor = QPoint(geo.right() - DS.Spacing.lg, geo.bottom() - DS.Spacing.lg)
        x = min(max(geo.left(), anchor.x() - self.width()), geo.right() - self.width())
        y = min(max(geo.top(), anchor.y() - self.height() - DS.Spacing.sm), geo.bottom())
        return QPoint(x, y)


class FocusPresenter(QObject):
    """Implements ``runtime.Presenter``. One open intervention at a time."""

    shown = Signal(object)  # Intervention with a bubble
    resolved = Signal(object, str)  # Intervention, InterventionResponse value

    def __init__(
        self,
        *,
        speak: Callable[[str], None] | None = None,
        pet: PetActions | None = None,
        anchor: Callable[[], QPoint | None] | None = None,
        schedule: Schedule = qt_schedule,
        bubble: ChoiceBubble | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._speak = speak
        self._pet = pet
        self._anchor = anchor
        self._schedule = schedule
        self.bubble = bubble or ChoiceBubble()
        self.bubble.chosen.connect(self.choose)
        self._responder: Responder | None = None
        self.current: Intervention | None = None
        self._cancel_expiry: Cancel | None = None

    def bind(self, responder: Responder) -> None:
        self._responder = responder

    def _pet_call(self, name: str) -> None:
        if self._pet is not None:
            getattr(self._pet, name)()

    def show(self, intervention: Intervention) -> None:
        if self.current is not None:
            # An unanswered card that's being replaced was never answered.
            self.resolve(InterventionResponse.IGNORED)
        if intervention.kind == InterventionKind.AMBIENT_CUE:
            self._pet_call("look_at_learner")
            return
        if intervention.kind == InterventionKind.BREAK_END:
            self._pet_call("stretch")
        self.current = intervention
        if self._speak is not None and intervention.message:
            self._speak(intervention.message)
        anchor = self._anchor() if self._anchor is not None else None
        self.bubble.show_intervention(intervention, anchor)
        seconds = max(1.0, intervention.expires_after.total_seconds())
        current_id = intervention.id
        self._cancel_expiry = self._schedule(seconds, lambda: self._expire(current_id))
        self.shown.emit(intervention)

    def _expire(self, intervention_id: str) -> None:
        if self.current is not None and self.current.id == intervention_id:
            self.resolve(InterventionResponse.IGNORED)

    def choose(self, choice: str) -> None:
        if self.current is not None:
            self.resolve(response_for_choice(choice))

    def handle_spoken(self, text: str) -> bool:
        """Route a push-to-talk reply to the open card; False if it isn't a choice."""
        if self.current is None:
            return False
        choice = match_spoken_choice(text, self.current.choices or (DEFAULT_CHOICE,))
        if choice is None:
            return False
        self.choose(choice)
        return True

    def resolve(self, response: InterventionResponse) -> None:
        intervention, self.current = self.current, None
        if intervention is None:
            return
        self._stop_expiry()
        self.bubble.hide()
        if (
            intervention.kind == InterventionKind.BREAK_START
            and response == InterventionResponse.ACCEPTED
        ):
            self._pet_call("nap")
        if self._responder is not None:
            self._responder(intervention, response)
        self.resolved.emit(intervention, response.value)

    def signal(self, signal: FocusSignal) -> None:
        if signal.kind == SignalKind.RETURNED:
            self._pet_call("happy")
        elif signal.kind == SignalKind.BREAK_OVER:
            self._pet_call("stretch")

    def _stop_expiry(self) -> None:
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None

    def clear(self) -> None:
        """Session over: close the card without recording a response."""
        self.current = None
        self._stop_expiry()
        self.bubble.hide()
        self._pet_call("wake")
