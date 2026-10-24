"""Sprite presentation layered over the existing Windows companion window."""

from __future__ import annotations

import logging
import time
from dataclasses import replace

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from curio.pet_config import PetSettings
from curio.pets import BehaviorController, Clip, SpriteCatalog, SpritePlayer
from curio.state import VoiceState
from curio.ui.companion_position import compute_position
from curio.ui.companion_widget import CompanionWidget

logger = logging.getLogger(__name__)


class PetCompanionWidget(CompanionWidget):
    """Keep platform/window integration and waveform, replace triangle painting."""

    WIDGET_W = 144
    WIDGET_H = 72
    PET_SIZE = 64

    def __init__(self, parent=None, *, settings: PetSettings | None = None):
        self.settings = settings or PetSettings()
        self.catalog = None
        self._speaking = False
        self._last_tick = time.monotonic()
        self._position_initialized = False
        self._point_screen = None
        self._point_coords = None
        super().__init__(parent)
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
                self.controller.cancel()
                self.controller.set_state(str(state))
        if self.settings.reduced_motion:
            self._stop_pulse()

    def text_started(self, _text=""):
        if self._state == VoiceState.RESPONDING:
            self.controller.text_started()

    def set_speaking(self, active: bool):
        self._speaking = active
        self.controller.set_speaking(active)

    def security_warning(self, _message=""):
        self.controller.react("warning")

    def flash_error(self, message=""):
        super().flash_error(message)
        self.controller.react("error")

    def fly_to(self, x: int, y: int):
        if self.catalog is None:
            return super().fly_to(x, y)
        screen = QApplication.screenAt(QPoint(x, y))
        if screen is None:
            return
        self._point_screen = screen
        self._point_coords = (x, y)
        # The marker is at the exact target; the sprite sits beside it.
        self.controller.point_to((x - 8, y - self.PET_SIZE // 2))

    def return_to_cursor(self):
        if self.catalog is None:
            return super().return_to_cursor()
        # Point lifecycle belongs to controller, independent of TTS completion.
        self._frozen = False

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
        if self._state == VoiceState.LISTENING:
            self._paint_waveform(painter, 74, 32)
        elif self._state == VoiceState.RESPONDING:
            self._paint_breathing_waveform(painter, 74, 32)
        elif self._state == VoiceState.PROCESSING:
            painter.setBrush(QColor("#f2b544"))
            painter.drawEllipse(QPoint(82, 32), 4, 4)
        painter.end()
