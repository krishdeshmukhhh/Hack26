"""Point-target spotlight: config, state logic, manager hooks and the overlay window."""

from __future__ import annotations

import asyncio

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from curio.config import Config, ConfigError, UiSettings
from curio.state import VoiceState
from curio.ui.spotlight import (
    ARRIVAL_FALLBACK_MS,
    AUTO_HIDE_MS,
    HOLE_RADIUS,
    SpotlightController,
    SpotlightOverlay,
)
from tests.test_walkthrough import (  # noqa: F401
    TWO_STEPS,
    _ask,
    _manager,
    _screens,
    _settle,
    qt_app,
)

# ---- config ----


def test_ui_defaults() -> None:
    assert UiSettings() == UiSettings(spotlight=True, spotlight_dim=0.35)
    assert UiSettings.from_dict({}) == UiSettings()


def test_ui_parses_values() -> None:
    ui = UiSettings.from_dict({"spotlight": False, "spotlight_dim": 0})
    assert ui == UiSettings(spotlight=False, spotlight_dim=0.0)
    assert UiSettings.from_dict({"spotlight_dim": 0.8}).spotlight_dim == 0.8


@pytest.mark.parametrize(
    "bad",
    [
        {"spotlight": "yes"},
        {"spotlight_dim": 0.9},
        {"spotlight_dim": -0.1},
        {"spotlight_dim": "x"},
        {"spotlight_dim": True},
    ],
)
def test_ui_rejects_bad_values(bad) -> None:
    with pytest.raises(ConfigError):
        UiSettings.from_dict(bad)


def test_ui_table_from_file(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'backend = "local"\n[ui]\nspotlight = false\nspotlight_dim = 0.5\n', encoding="utf-8"
    )
    config = Config.from_path(path)
    assert config.ui == UiSettings(spotlight=False, spotlight_dim=0.5)


# ---- controller state ----


class FakeOverlay:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def show_at(self, x, y, dim=None) -> None:
        self.events.append(("show", x, y, dim))

    def set_dim(self, enabled) -> None:
        self.events.append(("dim", enabled))

    def fade_out(self) -> None:
        self.events.append(("fade_out",))

    def hide_now(self) -> None:
        self.events.append(("hide_now",))

    def suspend(self) -> None:
        self.events.append(("suspend",))

    def resume(self) -> None:
        self.events.append(("resume",))


def _controller(**ui):
    overlay = FakeOverlay()
    return SpotlightController(UiSettings(**ui), lambda dim: overlay), overlay


def test_shows_only_on_arrival(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.point_started(100, 200)
    assert controller.state == "pending"
    assert overlay.events == []  # still flying: no dimming yet
    controller.arrived()
    assert controller.state == "dim"
    assert overlay.events == [("show", 100, 200, 0.35)]
    assert controller._auto_timer.isActive()


def test_arrival_without_target_is_ignored(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.arrived()
    assert overlay.events == []


def test_hide_before_arrival_cancels(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.point_started(1, 2)
    controller.hide()
    controller.arrived()
    assert controller.state == "hidden"
    assert overlay.events == []


def test_hide_fades_out(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.point_started(1, 2)
    controller.arrived()
    controller.hide()
    assert overlay.events[-1] == ("fade_out",)
    assert controller.state == "hidden"
    assert not controller._auto_timer.isActive()


def test_new_point_replaces_old(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.point_started(1, 2)
    controller.arrived()
    controller.point_started(30, 40)
    assert overlay.events[-1] == ("fade_out",)
    assert controller.state == "pending"
    controller.arrived()
    assert overlay.events[-1] == ("show", 30, 40, 0.35)


def test_plain_answer_hides_after_timeout(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    assert controller._auto_timer.interval() == AUTO_HIDE_MS == 8000
    controller.point_started(1, 2, hold=False)
    controller.arrived()
    controller._on_auto_timeout()
    assert overlay.events[-1] == ("fade_out",)
    assert controller.state == "hidden"


def test_walkthrough_step_drops_to_ring_only(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.point_started(1, 2, hold=True)
    controller.arrived()
    controller._on_auto_timeout()
    assert overlay.events[-1] == ("dim", False)
    assert controller.state == "ring"
    controller.hide()  # step finished
    assert overlay.events[-1] == ("fade_out",)


def test_disabled_never_shows(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller(spotlight=False)
    controller.point_started(1, 2)
    controller.arrived()
    assert controller.state == "hidden"
    assert overlay.events == []


def test_custom_dim_is_passed(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller(spotlight_dim=0.6)
    controller.point_started(1, 2)
    controller.arrived()
    assert overlay.events == [("show", 1, 2, 0.6)]


def test_capture_suspends_and_restores_only_when_shown(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.point_started(1, 2)
    controller.arrived()
    controller.hide_for_capture()
    controller.restore_after_capture()
    assert overlay.events[-2:] == [("suspend",), ("resume",)]
    controller.hide()
    controller.hide_for_capture()
    controller.restore_after_capture()
    assert overlay.events[-2:] == [("fade_out",), ("suspend",)]  # no resume once hidden


def test_raise_hook_runs_after_show(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    raised = []
    controller.raise_above = lambda: raised.append(list(overlay.events))
    controller.point_started(1, 2)
    controller.arrived()
    assert raised == [[("show", 1, 2, 0.35)]]


def test_fallback_shows_when_arrival_never_reported(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.point_started(710, 1176)
    assert controller._fallback_timer.isActive()
    assert controller._fallback_timer.interval() == ARRIVAL_FALLBACK_MS
    controller._on_fallback()
    assert controller.state == "dim"
    assert overlay.events == [("show", 710, 1176, 0.35)]
    assert not controller._fallback_timer.isActive()


def test_fallback_is_cancelled_by_arrival_and_hide(qt_app) -> None:  # noqa: F811
    controller, overlay = _controller()
    controller.point_started(1, 2)
    controller.arrived()
    assert not controller._fallback_timer.isActive()
    controller.hide()
    controller.point_started(3, 4)
    controller.hide()
    assert not controller._fallback_timer.isActive()
    controller._on_fallback()  # a stale timeout must not resurrect it
    assert controller.state == "hidden"
    assert [e[0] for e in overlay.events] == ["show", "fade_out"]


def test_show_and_hide_are_logged(qt_app, caplog) -> None:  # noqa: F811
    import logging

    geo = QGuiApplication.primaryScreen().geometry()
    overlay = SpotlightOverlay()
    controller = SpotlightController(UiSettings(), lambda dim: overlay)
    with caplog.at_level(logging.INFO, logger="curio.ui.spotlight"):
        controller.point_started(geo.x() + 5, geo.y() + 6)
        controller.arrived()
        controller.hide()
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("spotlight: show at (") for m in messages)
    assert any(m.startswith("spotlight: hide (") for m in messages)
    overlay.hide_now()


# ---- manager hooks ----


class FakeSpotlight:
    def __init__(self, log: list) -> None:
        self.log = log

    def point_started(self, x, y, *, hold=False) -> None:
        self.log.append(("point", x, y, hold))

    def hide(self) -> None:
        self.log.append("hide")

    def hide_for_capture(self) -> None:
        self.log.append("hide_for_capture")

    def restore_after_capture(self) -> None:
        self.log.append("restore")


def _with_spotlight(replies, monkeypatch):
    manager, parts = _manager(replies, monkeypatch)
    log: list = []
    manager._spotlight = FakeSpotlight(log)

    def capture():
        log.append("capture")
        return _screens()

    manager._screen_capture_fn = capture
    return manager, parts, log


def _points(log):
    return [e for e in log if isinstance(e, tuple)]


def test_manager_spotlights_each_step_and_hides_on_click(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts, log = _with_spotlight(TWO_STEPS, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)
        assert [e[3] for e in _points(log)] == [True]  # held: a walkthrough step
        log.clear()
        parts["clicks"].clicked.emit()
        assert log[0] == "hide"  # fades as soon as the step is finished
        await _settle(manager)
        # Hidden before the screenshot, restored after, then the next target.
        assert log.index("hide_for_capture") < log.index("capture") < log.index("restore")
        assert [e[3] for e in _points(log)] == [True]
        log.clear()
        parts["clicks"].clicked.emit()
        await _settle(manager)

    asyncio.run(run())
    # Final tagless answer with POINT:none: nothing new is spotlighted.
    assert _points(log) == []
    assert log[-1] == "hide"


def test_plain_answer_point_is_not_held(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts, log = _with_spotlight(["it is here. [POINT:500,500:thing]"], monkeypatch)

    async def run() -> None:
        _ask(manager, "where is the thing")
        await _settle(manager)

    asyncio.run(run())
    points = _points(log)
    assert len(points) == 1 and points[0][0] == "point" and points[0][3] is False


def test_point_none_shows_no_spotlight(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts, log = _with_spotlight(["html is markup. [POINT:none]"], monkeypatch)

    async def run() -> None:
        _ask(manager, "what is html")
        await _settle(manager)

    asyncio.run(run())
    assert _points(log) == []
    assert log[-1] == "hide"


@pytest.mark.parametrize("signal_name", ["escape_pressed", "pressed", "cancelled"])
def test_escape_new_question_and_cancel_hide(qt_app, monkeypatch, signal_name) -> None:  # noqa: F811
    manager, parts, log = _with_spotlight(TWO_STEPS, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)
        log.clear()
        getattr(parts["hotkey"], signal_name).emit()
        assert "hide" in log
        parts["hotkey"].cancelled.emit()

    asyncio.run(run())


def test_escape_hides_even_without_walkthrough(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts, log = _with_spotlight(["here. [POINT:500,500:thing]"], monkeypatch)

    async def run() -> None:
        _ask(manager, "where")
        await _settle(manager)
        log.clear()
        parts["hotkey"].escape_pressed.emit()

    asyncio.run(run())
    assert "hide" in log


def test_manager_without_spotlight_is_unchanged(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts = _manager(TWO_STEPS, monkeypatch)
    assert manager._spotlight is None

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)
        parts["hotkey"].escape_pressed.emit()

    asyncio.run(run())
    assert manager._state == VoiceState.IDLE


# ---- overlay window (offscreen) ----


def test_overlay_is_click_through_and_non_activating(qt_app) -> None:  # noqa: F811
    overlay = SpotlightOverlay()
    flags = overlay.windowFlags()
    assert flags & Qt.WindowType.WindowTransparentForInput
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_overlay_covers_target_monitor_and_cycles(qt_app) -> None:  # noqa: F811
    geo = QGuiApplication.primaryScreen().geometry()
    overlay = SpotlightOverlay()
    overlay.show_at(geo.x() + 50, geo.y() + 60, 0.35)
    assert overlay.isVisible()
    assert overlay.geometry() == geo
    assert (overlay._center.x(), overlay._center.y()) == (50, 60)
    overlay.suspend()
    assert not overlay.isVisible()
    overlay.resume()
    assert overlay.isVisible()
    overlay.set_dim(False)
    overlay.fade_out()
    overlay.hide_now()
    assert not overlay.isVisible()
    assert not overlay._frame_timer.isActive()  # no work when hidden


def _painted(dim_level: float):
    overlay = SpotlightOverlay(dim=0.5)
    overlay.resize(400, 300)
    overlay._center.setX(200)
    overlay._center.setY(150)
    overlay._opacity = 1.0
    overlay._dim_level = dim_level
    return overlay.grab().toImage()


def test_overlay_paints_dim_hole_and_ring(qt_app) -> None:  # noqa: F811
    image = _painted(1.0)
    assert 100 <= image.pixelColor(5, 5).alpha() <= 150  # ~50% black outside
    assert image.pixelColor(200, 150).alpha() == 0       # clear hole
    ring = [image.pixelColor(200 + HOLE_RADIUS + d, 150) for d in range(-1, 5)]
    assert any(p.alpha() > 0 and p.blue() > p.red() for p in ring)  # accent-coloured ring


def test_overlay_ring_only_has_no_dim(qt_app) -> None:  # noqa: F811
    image = _painted(0.0)
    assert image.pixelColor(5, 5).alpha() == 0
