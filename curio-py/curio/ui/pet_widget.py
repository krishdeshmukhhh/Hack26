"""Sprite presentation layered over the existing Windows companion window.

Builds on CompanionWidget's hooks (``_advance_motion``, ``_snap_to_cursor``,
``_bubble_anchor``, ``_is_pointing``): the pet's BehaviorController owns
movement and the point lifecycle, while the base class keeps the window,
capture hiding, waveform/spinner drawing, the pointer pill and greetings.
If the sprite assets can't load, the base triangle is used unchanged.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import replace

from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from curio.pet_config import PetSettings
from curio.pets import BehaviorController, Clip, SpriteCatalog, SpritePlayer
from curio.state import VoiceState
from curio.ui.companion_position import compute_position
from curio.ui.companion_widget import CompanionWidget
from curio.ui.pointer_bubble import (
    CURSOR_BLUE,
    ERROR_RED,
    random_pointer_phrase,
    step_caption,
)

logger = logging.getLogger(__name__)


class PetCompanionWidget(CompanionWidget):
    """Keep platform/window integration, waveform and pill; replace the triangle."""

    WIDGET_W = 144
    WIDGET_H = 72
    PET_SIZE = 64
    ARRIVAL_DISTANCE = 24  # px from the point target that counts as landed

    def __init__(self, parent=None, *, settings: PetSettings | None = None):
        self.settings = settings or PetSettings()
        self.catalog = None
        self._speaking = False
        self._last_tick = time.monotonic()
        self._position_initialized = False
        self._point_screen = None
        self._point_coords = None
        self._pill_anchor: QPointF | None = None
        self._point_target: tuple[float, float] | None = None
        self._arrival_sent = True
        self._pill_visit = False  # pointer pill is up for the current visit
        self._bounds: tuple[float, float, float, float] | None = None  # sprite clamp rect
        super().__init__(parent)
        self.setFixedSize(self.WIDGET_W, self.WIDGET_H)
        self._load_pet()

    def _load_pet(self):
        position = self.controller.position if hasattr(self, "controller") else (0.0, 0.0)
        self._frames = {}
        try:
            self.catalog = SpriteCatalog(self.settings.species)
            sheet = QPixmap(str(self.catalog.sheet_path))
            if sheet.isNull():
                raise ValueError("Cannot decode sprite sheet")
            self.player = SpritePlayer(self.catalog.clips)
            for clip in self.catalog.clips.values():
                for row, col in clip.frames:
                    frame = sheet.copy(col * 32, row * 32, 32, 32)
                    if frame.isNull():
                        raise ValueError("Invalid sprite frame")
                    self._frames[row, col] = frame
            self._frame = next(iter(self._frames))
        except (OSError, ValueError, KeyError) as exc:
            logger.error("Pet unavailable; using triangle: %s", exc)
            self.catalog = None
        clips = self.catalog.clips if self.catalog else {"idle": Clip(((0, 0),), (0.2,))}
        if hasattr(self, "controller"):
            self.controller.reconfigure(self.settings, clips)
        else:
            self.controller = BehaviorController(self.settings, clips=clips)
            self.controller.position = position
            self.controller.set_state(str(self._state))
            self.controller.set_speaking(self._speaking)
        self.update()

    def select_pet(self, species: str):
        self.settings = replace(self.settings, species=species)
        self._load_pet()

    def set_state(self, state):
        super().set_state(state)
        if hasattr(self, "controller"):
            self.controller.set_state(str(state))
            if state in (VoiceState.IDLE, VoiceState.LISTENING):
                self.set_speaking(False)
            if state == VoiceState.LISTENING:
                self._point_coords = None
                self._pill_anchor = None
                self._point_target = None
                self.controller.cancel()
                self.controller.set_state(str(state))

    def text_started(self, _text=""):
        # Answers stream while the spinner shows (PROCESSING), as on macOS.
        if self._state in (VoiceState.PROCESSING, VoiceState.RESPONDING):
            self.controller.text_started()

    def set_speaking(self, active: bool):
        self._speaking = active
        self.controller.set_speaking(active)

    def security_warning(self, _message=""):
        self.controller.react("warning")

    def flash_error(self, message=""):
        super().flash_error(message)
        self.controller.react("error")

    def play_clip(self, action: str) -> bool:
        """Play a named sprite clip; False with the triangle fallback or reduced motion."""
        if self.catalog is None:
            return False
        return self.controller.play(action)

    def fly_to(self, x: int, y: int, *, hold: bool = False, step=None):
        if self.catalog is None:
            return super().fly_to(x, y, hold=hold, step=step)
        screen = QApplication.screenAt(QPoint(x, y))
        if screen is None:
            return
        self._point_screen = screen
        self._point_coords = (x, y)
        self._arrival_sent = False
        self._hold = hold
        # The marker is at the exact target; the sprite sits beside it.
        self._point_target = (x - 8, y - self.PET_SIZE // 2)
        self.controller.point_to(self._point_target)
        # macOS-style pointer pill beside the target. It fades when the pet's
        # visit ends; walkthrough steps keep both until released.
        caption = step_caption(random_pointer_phrase(), step)
        # The sprite covers the target area, so put the pill just right of it.
        self._pill_anchor = QPointF(self._point_target[0] + self.PET_SIZE + 4, y)
        self._pill_visit = True
        self.bubble.show_text(caption, self._pill_anchor)

    def release_hold(self):
        if self.catalog is None:
            return super().release_hold()
        self._hold = False
        self._point_target = None
        if self._pill_anchor is not None:
            self.bubble.fade_out(self.BUBBLE_FADE_MS)

    def return_to_cursor(self):
        if self.catalog is None:
            return super().return_to_cursor()
        # Point lifecycle belongs to controller, independent of TTS completion.
        self.release_hold()

    # ------------------------------------------------------------------
    # CompanionWidget hooks
    # ------------------------------------------------------------------

    def _advance_motion(self):
        if self.catalog is None:
            return super()._advance_motion()
        self._track_cursor()
        self._check_arrival()
        if self._hold and self._point_target and not self.controller.point_active:
            # Walkthrough step: stay at the target until the user clicks,
            # instead of the controller's usual short visit.
            self.controller.point_to(self._point_target)
        elif self._pill_visit and not self.controller.point_active:
            # The pet's visit is over; fade the pill where it is.
            self._pill_visit = False
            self.bubble.fade_out(self.BUBBLE_FADE_MS)

    def _check_arrival(self):
        """Tell the spotlight once the pet has reached the point target."""
        if self._arrival_sent or not self._point_target or not self.controller.point_active:
            return
        px, py = self.controller.position
        tx, ty = self._point_target
        if self._bounds is not None:
            # The sprite is clamped to the work area, so a target on the taskbar can't
            # be reached exactly; the clamped spot is where it will actually land.
            left, top, right, bottom = self._bounds
            tx, ty = max(left, min(right, tx)), max(top, min(bottom, ty))
        if math.hypot(px - tx, py - ty) <= self.ARRIVAL_DISTANCE:
            self._arrival_sent = True
            self.pointer_arrived.emit()

    def _snap_to_cursor(self):
        if self.catalog is None or not hasattr(self, "controller"):
            return super()._snap_to_cursor()
        self._track_cursor(force=True)

    def _is_pointing(self):
        if self.catalog is None:
            return super()._is_pointing()
        return self.controller.point_active

    def _bubble_anchor(self):
        if self.catalog is None:
            return super()._bubble_anchor()
        if self._pill_anchor is not None and self.bubble.active:
            return self._pill_anchor
        self._pill_anchor = None
        # Beside the pet's head.
        return QPointF(self.x() + self.PET_SIZE - 6, self.y() + self.PET_SIZE * 0.35)

    def _track_cursor(self, force=False):
        if self.catalog is None:
            return super()._track_cursor(force)
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now
        cursor = QCursor.pos()
        screen = QApplication.screenAt(cursor) or QApplication.primaryScreen()
        if screen is None:
            return
        if self.controller.point_active and self._point_screen in QApplication.screens():
            screen = self._point_screen
        geo = screen.availableGeometry()
        placement = compute_position(
            cursor.x(),
            cursor.y(),
            (geo.x(), geo.y(), geo.width(), geo.height()),
            (self.WIDGET_W, self.WIDGET_H),
            edge_margin=self.WIDGET_W + 20,
        )
        destination = (placement.x, placement.y)
        bounds = (
            geo.left(),
            geo.top(),
            max(geo.left(), geo.right() + 1 - self.WIDGET_W),
            max(geo.top(), geo.bottom() + 1 - self.WIDGET_H),
        )
        self._bounds = bounds
        if force and not self._position_initialized:
            self.controller.position = destination
            self._position_initialized = True
        # Cross monitor gaps directly; never linger in inaccessible desktop space.
        px, py = self.controller.position
        if not geo.contains(QPoint(int(px), int(py))):
            self.controller.position = destination
        pos = self.controller.update(dt, destination, bounds)
        self.move(round(pos[0]), round(pos[1]))
        if not self.controller.point_active:
            self._point_coords = None
        self.player.set_action(self.controller.action)
        self._frame = self.player.advance(
            0
            if self.settings.reduced_motion
            else dt * (self.settings.jump_speed if self.controller.action == "jump" else 1)
        )
        self.update()

    def restore_after_capture(self):
        self._last_tick = time.monotonic()
        super().restore_after_capture()

    def paintEvent(self, event):
        if self.catalog is None:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.setOpacity(self._opacity)
        frame = self._frames[self._frame]
        painter.save()
        if self.controller.facing_left:
            painter.translate(self.PET_SIZE, 0)
            painter.scale(-1, 1)
        painter.drawPixmap(QRect(0, 0, self.PET_SIZE, self.PET_SIZE), frame)
        painter.restore()
        if self._point_coords:
            x, y = self._point_coords
            x -= self.x()
            y -= self.y()
            painter.setPen(QColor("#4a9eff"))
            painter.drawEllipse(QPoint(x, y), 5, 5)
        # Beside the pet: the listening waveform and thinking spinner from the
        # base widget. While speaking, the pet's own animation carries it.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        indicator = QPointF(self.PET_SIZE + 18, self.PET_SIZE / 2)
        color = QColor(ERROR_RED if self._error_flash else CURSOR_BLUE)
        if self._state == VoiceState.LISTENING:
            self._paint_waveform(painter, indicator, color)
        elif self._state == VoiceState.PROCESSING:
            self._paint_spinner(painter, indicator, color)
        painter.end()
