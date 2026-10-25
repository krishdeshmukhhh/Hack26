"""Overlay polish: ring/spotlight handoff, taskbar reach, shared theme, landing, celebrate."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect

from curio.pet_config import PetSettings
from curio.state import VoiceState
from curio.ui import landing, pointer_bubble, spotlight, target_ring, theme
from curio.ui.companion_widget import CompanionWidget
from curio.ui.pet_widget import PetCompanionWidget


def _frames(widget, seconds, step=0.1):
    for _ in range(round(seconds / step)):
        widget._last_tick = time.monotonic() - step
        widget._advance_motion()


# ---- target ring -> spotlight handoff ----


def test_target_ring_fade_out_clears_quickly(qt_application, monkeypatch):
    now = [10.0]
    monkeypatch.setattr(target_ring.time, "monotonic", lambda: now[0])
    ring = target_ring.TargetRingOverlay()
    ring.fade_out()  # nothing pulsing: no-op
    assert ring._fade_started is None
    ring.pulse_at(100, 100)
    now[0] += 0.3
    ring.fade_out()
    now[0] += 0.05
    ring._on_frame()
    assert ring.isVisible()
    assert not ring.grab().isNull()
    now[0] += target_ring.TargetRingOverlay.FADE_DURATION
    ring._on_frame()
    assert not ring.isVisible() and not ring._timer.isActive()
    ring.pulse_at(100, 100)  # a new pulse resets the fade
    assert ring._fade_started is None
    ring.close()


def test_spotlight_show_fades_target_ring_via_raise_overlays(qt_application):
    widget = CompanionWidget()
    widget.target_ring.pulse_at(100, 100)
    assert widget.target_ring._fade_started is None
    widget.raise_overlays()  # SpotlightController.raise_above calls this when it appears
    assert widget.target_ring._fade_started is not None
    widget.close()


def test_spotlight_disabled_keeps_target_ring(qt_application):
    from curio.config import UiSettings

    widget = CompanionWidget()
    controller = spotlight.SpotlightController(UiSettings(spotlight=False))
    controller.raise_above = widget.raise_overlays
    widget.target_ring.pulse_at(100, 100)
    controller.point_started(100, 100)
    controller.arrived()  # disabled: never shows, never calls raise_above
    assert widget.target_ring._fade_started is None
    widget.close()


# ---- theme ----


def test_theme_constants_are_shared():
    assert pointer_bubble.CURSOR_BLUE == theme.ACCENT
    assert pointer_bubble.ERROR_RED == theme.ERROR_RED
    assert target_ring.ACCENT is theme.ACCENT and spotlight.ACCENT is theme.ACCENT
    assert target_ring.RING_WIDTH == spotlight.RING_WIDTH == theme.RING_WIDTH
    assert spotlight.GLOW_WIDTH == theme.GLOW_WIDTH
    assert pointer_bubble.CORNER_RADIUS == theme.CORNER_RADIUS


def test_spotlight_overlay_uses_accent(qt_application):
    assert spotlight.SpotlightOverlay()._color.name().upper() == theme.ACCENT.upper()


# ---- taskbar reach ----


def _screen(full: QRect, available: QRect):
    return SimpleNamespace(geometry=lambda: full, availableGeometry=lambda: available)


def test_walk_geometry_expands_for_taskbar_target(qt_application):
    widget = PetCompanionWidget(settings=PetSettings())
    full, work = QRect(0, 0, 1920, 1080), QRect(0, 0, 1920, 1032)
    screen = _screen(full, work)
    assert widget._walk_geometry(screen, work) == work  # not pointing
    widget.fly_to(400, 300)  # the offscreen display is small; place the target by hand
    widget._point_coords = (40, 1056)  # Start button, inside the taskbar band
    assert widget.controller.point_active
    assert widget._walk_geometry(screen, work) == full
    assert widget._on_taskbar
    widget._point_coords = (400, 300)  # in the work area
    assert widget._walk_geometry(screen, work) == work
    assert not widget._on_taskbar
    widget.close()


def test_taskbar_target_lets_sprite_reach_and_arrival_fires(qt_application):
    widget = PetCompanionWidget(settings=PetSettings())
    arrived = []
    widget.pointer_arrived.connect(lambda: arrived.append(True))
    widget.fly_to(400, 780)
    tx, ty = widget._point_target
    # Full-screen bounds: the sprite can sit exactly at the target, no clamp needed.
    widget._bounds = (0, 0, 656, 728)
    widget.controller.position = (tx, ty)
    widget._check_arrival()
    assert arrived == [True]
    widget.close()


# ---- landing ----


def test_landing_scale_curve():
    assert landing.landing_scale(0.0) == 1.0
    assert landing.landing_scale(0.35) == pytest.approx(1.08)
    assert landing.landing_scale(0.7) == pytest.approx(0.97)
    assert landing.landing_scale(1.0) == 1.0
    assert 1.0 < landing.landing_scale(0.2) < 1.08


def test_landing_bounce_starts_and_stops(qt_application):
    changes = []
    bounce = landing.LandingBounce(lambda: changes.append(bounce.scale))
    assert not bounce.active
    bounce.start()
    assert bounce.active
    bounce.stop()
    assert not bounce.active and bounce.scale == 1.0


def test_arrival_starts_landing_only_when_visible_and_motion_allowed(qt_application):
    widget = PetCompanionWidget(settings=PetSettings())
    widget._start_landing()  # hidden: no animation
    assert not widget._landing.active
    widget.show()
    widget._start_landing()
    assert widget._landing.active
    widget.hide()
    assert not widget._landing.active
    widget.settings = PetSettings(reduced_motion=True)
    widget.show()
    widget._start_landing()
    assert not widget._landing.active
    widget.hide()


def test_pet_arrival_triggers_landing(qt_application):
    widget = PetCompanionWidget(settings=PetSettings())
    widget.show()
    widget.set_state(VoiceState.RESPONDING)
    widget.fly_to(400, 300)
    _frames(widget, 4.0)
    assert widget._arrival_sent
    assert not widget.grab().isNull()
    widget.hide()


# ---- walkthrough finished ----


def test_pet_celebrate_plays_clip(qt_application):
    widget = PetCompanionWidget(settings=PetSettings())
    widget.celebrate()  # hidden: nothing
    assert widget._check_started_ms is None
    widget.show()
    widget.celebrate()
    assert widget.controller.action == "jump"
    widget.hide()


def test_celebrate_check_flourish_for_triangle_and_reduced_motion(qt_application):
    widget = CompanionWidget()
    widget.show()
    widget.celebrate()
    assert widget._check_started_ms is not None
    assert not widget.grab().isNull()
    widget._check_started_ms -= widget.CHECK_MS + 1
    assert widget._check_progress() is None and widget._check_started_ms is None
    widget.hide()

    pet = PetCompanionWidget(settings=PetSettings(reduced_motion=True))
    pet.show()
    pet.celebrate()  # clip skipped under reduced motion: falls back to the check
    assert pet._check_started_ms is not None
    assert not pet.grab().isNull()
    pet.hide()
