"""Regression checks across focus selection and the remote walkthrough additions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF, QRect

from curio.config import UiSettings
from curio.key_finish_watcher import KeyFinishWatcher
from curio.state import VoiceState
from curio.ui import spotlight
from tests.test_key_finish_watcher import FakeTapHotkey
from tests.test_spotlight import FakeOverlay, FakeSpotlight
from tests.test_walkthrough import _ask, _manager, _settle


def test_selection_pauses_and_rearms_keyboard_step_completion(qt_application, monkeypatch):
    async def run():
        manager, parts = _manager(["Open File [STEP:1/2] [POINT:none]"], monkeypatch)
        tap = FakeTapHotkey()
        watcher = KeyFinishWatcher(tap)
        manager._key_watcher = watcher
        watcher.finished.connect(manager._on_walkthrough_click)
        _ask(manager, "how do I open this?")
        await _settle(manager)
        assert watcher.active
        parts["hotkey"].pressed.emit()
        assert not watcher.active
        manager.cancel_for_selection()
        assert watcher.active
        assert manager._state == VoiceState.GUIDING
        assert len(parts["llm"].requests) == 1
        await manager.aclose()
        assert not watcher.active

    asyncio.run(run())


def test_explicit_capture_restores_spotlight_on_failure(qt_application, monkeypatch):
    async def run():
        manager, _ = _manager([], monkeypatch)
        log = []
        manager._spotlight = FakeSpotlight(log)
        manager._screen_capture_fn = Mock(side_effect=RuntimeError("capture failed"))
        with pytest.raises(RuntimeError, match="capture failed"):
            await manager.capture_screenshots()
        assert log == ["hide_for_capture", "restore"]

    asyncio.run(run())


def test_spotlight_uses_physical_to_logical_boundary(qt_application, monkeypatch):
    screen = SimpleNamespace(geometry=lambda: QRect(-1280, 0, 1280, 720), name=lambda: "test")
    monkeypatch.setattr(
        spotlight, "logical_target", lambda x, y: (screen, QPointF(-1180, 100)), raising=False
    )
    overlay = spotlight.SpotlightOverlay()
    try:
        overlay.show_at(-1770, -50)
        assert overlay.geometry() == screen.geometry()
        assert overlay._center == QPointF(100, 100)
    finally:
        overlay.hide_now()
        overlay.close()


def test_arrival_during_capture_waits_until_restored(qt_application):
    overlay = FakeOverlay()
    controller = spotlight.SpotlightController(UiSettings(), lambda dim: overlay)
    controller.point_started(100, 200)
    controller.hide_for_capture()
    controller.arrived()
    assert overlay.events == []
    controller.restore_after_capture()
    assert overlay.events == [("show", 100, 200, 0.35)]
    controller.hide_now()
