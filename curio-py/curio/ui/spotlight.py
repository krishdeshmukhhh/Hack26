"""Soft spotlight on whatever the companion points at.

When the companion lands on a target, the rest of that monitor dims a little
and a feathered hole with a softly pulsing ring marks the spot. It is a
demo-friendly "click here" cue, nothing more:

- Click-through and never focused (the user must click the thing inside it).
- Hidden explicitly around every screenshot sent to the model. It is not
  excluded at the OS level, so screen recordings (OBS) still show it.
- Idle cost is zero: the frame timer only runs while it is visible.

``SpotlightOverlay`` is the window; ``SpotlightController`` is the small state
machine that CompanionManager and the companion widget drive.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from enum import Enum, auto

from PySide6.QtCore import (
    QElapsedTimer,
    QObject,
    QPoint,
    QPointF,
    QRect,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from curio.config import UiSettings
from curio.ui.pointer_bubble import CURSOR_BLUE
from curio.ui.window_effects import (
    make_non_activating,
    make_overlay_window,
    raise_without_activating,
)

logger = logging.getLogger(__name__)

HOLE_RADIUS = 70        # logical px: fully clear inside this (minus half the feather)
FEATHER = 30            # width of the soft edge, centred on HOLE_RADIUS
FADE_MS = 200
RING_ONLY_FADE_MS = 400
PULSE_MS = 1200
FRAME_MS = 33           # ~30 fps; enough for a gentle pulse and cheap on 4K
AUTO_HIDE_MS = 8000
# Show anyway if the companion never reports landing (e.g. the sprite is clamped to the
# work area and can't reach a target on the taskbar).
ARRIVAL_FALLBACK_MS = 3000


class SpotlightOverlay(QWidget):
    """A transparent window the size of one monitor that paints the dim and ring."""

    def __init__(self, dim: float = 0.35, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._dim = dim
        self._dim_level = 1.0     # 1 = full dim, 0 = ring only (animated)
        self._opacity = 0.0       # master fade for dim and ring
        self._center = QPointF()
        self._color = QColor(CURSOR_BLUE)
        self._fading_out = False
        self._suspended = False

        self._clock = QElapsedTimer()
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(FRAME_MS)
        self._frame_timer.timeout.connect(self._on_frame)

        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.valueChanged.connect(self._set_opacity)
        self._fade_anim.finished.connect(self._on_fade_finished)

        self._dim_anim = QVariantAnimation(self)
        self._dim_anim.valueChanged.connect(self._set_dim_level)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_at(self, x: int, y: int, dim: float | None = None) -> None:
        """Cover the monitor containing global point (x, y) and fade in around it."""
        if dim is not None:
            self._dim = dim
        screen = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
        geo = screen.geometry()
        self._fade_anim.stop()
        self._dim_anim.stop()
        self._fading_out = False
        self._suspended = False
        self._dim_level = 1.0
        self.setGeometry(geo)
        self._center = QPointF(x - geo.x(), y - geo.y())
        self._clock.start()
        self._set_opacity(0.0)
        self.show()
        # Targets on the taskbar (Start button) need us above it in the topmost band.
        raise_without_activating(self)
        self._frame_timer.start()
        self._animate_opacity(1.0, FADE_MS)
        logger.info(
            "spotlight: show at (%d,%d) screen=%s geometry=%dx%d",
            x, y, screen.name(), geo.width(), geo.height(),
        )

    def set_dim(self, enabled: bool) -> None:
        """Animate to the ring-only look (False) or back to the full dim (True)."""
        self._dim_anim.stop()
        self._dim_anim.setDuration(RING_ONLY_FADE_MS)
        self._dim_anim.setStartValue(self._dim_level)
        self._dim_anim.setEndValue(1.0 if enabled else 0.0)
        self._dim_anim.start()

    def fade_out(self) -> None:
        if not self.isVisible():
            self._suspended = False  # hidden for a capture; just stay hidden
            return
        self._dim_anim.stop()
        self._fading_out = True
        self._animate_opacity(0.0, FADE_MS)

    def hide_now(self) -> None:
        self._fade_anim.stop()
        self._dim_anim.stop()
        self._frame_timer.stop()
        self._fading_out = False
        self._suspended = False
        self._opacity = 0.0
        super().hide()

    def suspend(self) -> None:
        """Vanish immediately for a screen capture; ``resume`` brings it back."""
        if not self.isVisible():
            return
        self._suspended = True
        self._fade_anim.stop()
        self._dim_anim.stop()
        self._frame_timer.stop()
        super().hide()

    def resume(self) -> None:
        if not self._suspended:
            return
        self._suspended = False
        if self._fading_out:
            # The fade-out was interrupted by the capture: it is simply over.
            self._opacity = 0.0
            self._fading_out = False
            return
        self._set_dim_level(self._dim_level)
        self.show()
        raise_without_activating(self)
        self._frame_timer.start()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: ARG002
        make_overlay_window(self)   # WS_EX_LAYERED | WS_EX_TRANSPARENT (click-through)
        make_non_activating(self)   # WS_EX_NOACTIVATE (never steals focus)

    def _animate_opacity(self, end: float, ms: int) -> None:
        self._fade_anim.stop()
        self._fade_anim.setDuration(ms)
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(end)
        self._fade_anim.start()

    def _set_opacity(self, value) -> None:
        self._opacity = float(value)
        self.update()

    def _set_dim_level(self, value) -> None:
        self._dim_level = float(value)
        self.update()

    def _on_fade_finished(self) -> None:
        if self._fading_out and self._opacity <= 0.001:
            self.hide_now()

    def _ring_rect(self) -> QRect:
        reach = int(HOLE_RADIUS + FEATHER)
        return QRect(
            int(self._center.x()) - reach, int(self._center.y()) - reach, 2 * reach, 2 * reach
        )

    def _on_frame(self) -> None:
        # Only the ring moves, so repaint just its neighbourhood each frame.
        self.update(self._ring_rect())

    def _pulse(self) -> float:
        """0..1..0 over PULSE_MS."""
        phase = (self._clock.elapsed() % PULSE_MS) / PULSE_MS
        return 0.5 - 0.5 * math.cos(2 * math.pi * phase)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        c = self._center

        alpha = self._dim * self._dim_level
        if alpha > 0.001:
            outer = HOLE_RADIUS + FEATHER / 2
            inner = HOLE_RADIUS - FEATHER / 2
            gradient = QRadialGradient(c, outer)
            clear = QColor(0, 0, 0, 0)
            gradient.setColorAt(0.0, clear)
            gradient.setColorAt(inner / outer, clear)
            gradient.setColorAt(1.0, QColor(0, 0, 0, round(255 * alpha)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRect(self.rect())

        pulse = self._pulse()
        radius = HOLE_RADIUS + 3 * pulse
        glow = QColor(self._color)
        glow.setAlphaF(0.10 + 0.14 * pulse)
        painter.setPen(QPen(glow, 9))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(c, radius, radius)
        ring = QColor(self._color)
        ring.setAlphaF(0.55 + 0.40 * pulse)
        painter.setPen(QPen(ring, 2.5))
        painter.drawEllipse(c, radius, radius)
        painter.end()


class _State(Enum):
    HIDDEN = auto()
    PENDING = auto()   # target known, companion still flying there
    DIM = auto()       # dim + ring showing
    RING = auto()      # walkthrough step held past the timeout: ring only


class SpotlightController(QObject):
    """When to show and hide the spotlight; the window itself only draws.

    ``overlay_factory`` builds the overlay lazily on first use, so nothing exists
    when the feature is off or has never fired.
    """

    def __init__(
        self,
        settings: UiSettings,
        overlay_factory: Callable[[float], SpotlightOverlay] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._overlay_factory = overlay_factory or (lambda dim: SpotlightOverlay(dim))
        self._overlay: SpotlightOverlay | None = None
        self._state = _State.HIDDEN
        self._target: tuple[int, int] | None = None
        self._hold = False
        # Called after the overlay appears so the companion and pill stay on top.
        self.raise_above: Callable[[], None] | None = None

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(AUTO_HIDE_MS)
        self._auto_timer.timeout.connect(self._on_auto_timeout)

        self._fallback_timer = QTimer(self)
        self._fallback_timer.setSingleShot(True)
        self._fallback_timer.setInterval(ARRIVAL_FALLBACK_MS)
        self._fallback_timer.timeout.connect(self._on_fallback)

    @property
    def state(self) -> str:
        return self._state.name.lower()

    @property
    def enabled(self) -> bool:
        return self._settings.spotlight

    def point_started(self, x: int, y: int, *, hold: bool = False) -> None:
        """The companion is flying to (x, y). Drop any old spotlight; show on arrival."""
        self.hide()
        if not self.enabled:
            return
        self._target = (x, y)
        self._hold = hold
        self._state = _State.PENDING
        self._fallback_timer.start()
        logger.debug("spotlight: pending at (%d,%d) hold=%s", x, y, hold)

    def arrived(self) -> None:
        """The companion landed on the target."""
        if self._state is not _State.PENDING or self._target is None:
            return
        self._fallback_timer.stop()
        logger.debug("spotlight: arrival reported")
        if self._overlay is None:
            self._overlay = self._overlay_factory(self._settings.spotlight_dim)
        self._overlay.show_at(*self._target, self._settings.spotlight_dim)
        self._state = _State.DIM
        self._auto_timer.start()
        if self.raise_above is not None:
            self.raise_above()

    def hide(self, reason: str = "requested") -> None:
        """Fade out (step finished, cancelled, new target, no target)."""
        self._auto_timer.stop()
        self._fallback_timer.stop()
        if self._state in (_State.DIM, _State.RING) and self._overlay is not None:
            logger.info("spotlight: hide (%s)", reason)
            self._overlay.fade_out()
        self._state = _State.HIDDEN
        self._target = None

    def hide_now(self) -> None:
        self.hide("hide_now")
        if self._overlay is not None:
            self._overlay.hide_now()

    def hide_for_capture(self) -> None:
        """Gone this instant, so the screenshot never shows it."""
        if self._overlay is not None:
            self._overlay.suspend()

    def restore_after_capture(self) -> None:
        if self._overlay is not None and self._state in (_State.DIM, _State.RING):
            self._overlay.resume()

    def _on_fallback(self) -> None:
        if self._state is _State.PENDING:
            logger.debug("spotlight: no arrival within %d ms; showing anyway", ARRIVAL_FALLBACK_MS)
            self.arrived()

    def _on_auto_timeout(self) -> None:
        if self._state is _State.DIM and self._hold and self._overlay is not None:
            # A walkthrough step waits for the user; keep the cue but stop dimming.
            self._overlay.set_dim(False)
            self._state = _State.RING
        elif self._state is _State.DIM:
            self.hide("timeout")
