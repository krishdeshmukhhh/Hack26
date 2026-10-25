"""Real input controllers, crop metadata and widgets; fake audio/model providers."""

import asyncio
import base64
import io
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image
from pynput import keyboard
from PySide6.QtCore import QPointF, QRect, Qt

from curio import hotkey
from curio.click_watcher import ClickWatcher
from curio.config import LocalConfig
from curio.focus_selection import FocusSelectionController
from curio.hotkey import HotkeyMonitor
from curio.screen_capture import ScreenshotImage
from curio.state import VoiceState
from curio.ui import focus_overlay, target_ring
from curio.ui.companion_widget import CompanionWidget
from curio.ui.pet_widget import PetCompanionWidget
from tests.test_walkthrough import _ask, _manager, _settle


def source(color="red"):
    buf = io.BytesIO()
    Image.new("RGB", (60, 39), color).save(buf, "JPEG")
    return [ScreenshotImage(buf.getvalue(), "screen", True, 121, 80, 60, 39, 0.5, -121, -80)]


@pytest.fixture
def selection(qt_application, monkeypatch):
    monkeypatch.setattr("curio.focus_selection.mouse.Listener", Mock())
    monkeypatch.setattr("curio.focus_selection.keyboard.Listener", Mock())
    monkeypatch.setattr(
        "curio.focus_selection.display_coordinates",
        lambda: [
            focus_overlay.DisplayCoordinates((-121, -80, 121, 80), QRect(-121, -80, 121, 80)),
        ],
    )
    c = FocusSelectionController()
    c.start()
    yield c
    c.stop()


def draw(c, app):
    c._post("begin", -100, -60)
    c._post("finish", -39, -19)
    app.processEvents()


@pytest.mark.parametrize("drain_press_first", [False, True])
@pytest.mark.parametrize("binding", ["ctrl+alt", "right_ctrl"])
def test_selection_cancels_voice_without_submitting_then_fresh_chord_works(
    selection,
    qt_application,
    monkeypatch,
    drain_press_first,
    binding,
):
    monkeypatch.setattr(hotkey, "_get_async_key_state", None)

    async def run():
        manager, parts = _manager(["fresh answer [POINT:none]"], monkeypatch)
        # Replace fake input wiring with the real monitor's queued signals.
        monitor = HotkeyMonitor(binding)
        monitor.pressed.connect(manager._on_hotkey_pressed)
        monitor.released.connect(manager._on_hotkey_released)
        monitor.cancelled.connect(manager._on_hotkey_cancelled)
        monitor.selection_cancelled.connect(manager.cancel_for_selection)
        selection.selection_input_started.connect(
            monitor.suppress_for_selection,
            Qt.ConnectionType.DirectConnection,
        )
        manager._screen_capture_fn = source
        manager._transcription.stop_stream = AsyncMock()
        ctrl = keyboard.Key.ctrl_r if binding == "right_ctrl" else keyboard.Key.ctrl_l
        monitor._on_press(ctrl)
        if binding == "ctrl+alt":
            monitor._on_press(keyboard.Key.alt_l)
        if drain_press_first:
            qt_application.processEvents()
            await asyncio.sleep(0)
            assert manager._state == VoiceState.LISTENING
        selection._modifiers_down = lambda: True
        selection._win32_filter(0x201, SimpleNamespace(pt=SimpleNamespace(x=-100, y=-60)))
        # Modifier release can be queued before the selection's Qt begin event runs.
        monitor._on_release(ctrl)
        if binding == "ctrl+alt":
            monitor._on_release(keyboard.Key.alt_l)
        qt_application.processEvents()
        await asyncio.sleep(0)
        assert manager._state == VoiceState.IDLE
        manager._transcription.final_transcript.emit("discard this recording")
        await asyncio.sleep(0)
        assert not parts["llm"].requests
        monitor._on_press(ctrl)
        if binding == "ctrl+alt":
            monitor._on_press(keyboard.Key.alt_l)
        qt_application.processEvents()
        await asyncio.sleep(0)
        assert manager._state == VoiceState.LISTENING
        monitor._on_release(ctrl)
        if binding == "ctrl+alt":
            monitor._on_release(keyboard.Key.alt_l)
        qt_application.processEvents()
        manager._transcription.final_transcript.emit("fresh question")
        await _settle(manager)
        assert len(parts["llm"].requests) == 1
        monitor.stop()

    asyncio.run(run())


def test_suppressed_windows_gesture_never_advances_walkthrough(
    selection,
    qt_application,
    monkeypatch,
):
    async def run():
        manager, parts = _manager(
            ["Open file [STEP:1/2] [POINT:none]", "Done [POINT:none]"], monkeypatch
        )
        watcher = ClickWatcher()
        watcher.set_click_source(selection)
        manager._click_watcher = watcher
        watcher.clicked.connect(manager._on_walkthrough_click)
        _ask(manager, "how do I open a file")
        await _settle(manager)

        # pynput suppression raises internally and prevents later hooks from seeing this event.
        class Suppressed(Exception):
            pass

        selection._mouse_listener.suppress_event.side_effect = Suppressed
        selection._modifiers_down = lambda: True
        with pytest.raises(Suppressed):
            selection._win32_filter(0x201, SimpleNamespace(pt=SimpleNamespace(x=-100, y=-60)))
        qt_application.processEvents()
        assert len(parts["llm"].requests) == 1
        assert manager._state == VoiceState.GUIDING
        selection._mouse_listener.suppress_event.side_effect = None
        selection._win32_filter(0x202, SimpleNamespace(pt=SimpleNamespace(x=-39, y=-19)))
        qt_application.processEvents()
        assert selection.region is not None
        selection._modifiers_down = lambda: False
        selection._win32_filter(0x201, SimpleNamespace(pt=SimpleNamespace(x=-90, y=-50)))
        qt_application.processEvents()
        assert selection.region is None
        await _settle(manager)
        assert len(parts["llm"].requests) == 2
        watcher.stop()

    asyncio.run(run())


@pytest.mark.parametrize(
    "coords,tag,expected",
    [
        ("pixel", "20,10", (-59, -40)),
        ("norm1000", "500,500", (-70, -40)),
    ],
)
def test_fresh_focused_requests_snapshot_and_point_mapping(
    selection,
    qt_application,
    monkeypatch,
    coords,
    tag,
    expected,
):
    draw(selection, qt_application)

    async def run():
        manager, parts = _manager(
            [f"Here [POINT:{tag}:target]", "Next [POINT:none]", "Normal [POINT:none]"], monkeypatch
        )
        manager._config = replace(
            manager._config,
            local=LocalConfig.from_dict(
                {
                    "point_coords": coords,
                }
            ),
        )
        manager.attach_focus_selection(selection)
        captures = []

        def capture():
            captures.append(len(captures))
            return source("red" if len(captures) == 1 else "blue")

        manager._screen_capture_fn = capture
        original_send = parts["llm"].send

        async def send(*args, **kwargs):
            selection.clear()  # Must not change the in-flight crop or POINT coordinate space.
            return await original_send(*args, **kwargs)

        parts["llm"].send = send
        _ask(manager, "what is this?")
        await _settle(manager)
        shot = manager._current_screenshots[0]
        assert (shot.image_width_px, shot.image_height_px) == (30, 20)
        assert parts["overlays"].flights[0][:2] == expected
        first_blocks = parts["llm"].requests[0][-1]["content"]
        assert any("selected focus" in b.get("text", "") for b in first_blocks)
        image = next(b for b in first_blocks if b["type"] == "image")
        with Image.open(io.BytesIO(base64.b64decode(image["source"]["data"]))) as decoded:
            assert decoded.size == (30, 20)
        draw(selection, qt_application)
        _ask(manager, "what changed?")
        await _settle(manager)
        second = manager._current_screenshots[0]
        assert shot.jpeg_bytes != second.jpeg_bytes
        _ask(manager, "whole screen now")
        await _settle(manager)
        assert manager._current_screenshots[0].image_width_px == 60
        assert len(captures) == 3

    asyncio.run(run())


@pytest.mark.parametrize(
    "widget_type,fallback",
    [
        (CompanionWidget, False),
        (PetCompanionWidget, False),
        (PetCompanionWidget, True),
    ],
)
def test_each_flight_pulses_once_and_close_stops_ring(qt_application, widget_type, fallback):
    widget = widget_type()
    if fallback:
        widget.catalog = None
    ring = widget.target_ring
    ring.pulse_at = Mock(wraps=ring.pulse_at)
    widget.fly_to(100, 100, hold=True, step=(1, 2))
    widget.fly_to(200, 200)
    assert ring.pulse_at.call_args_list == [((100, 100),), ((200, 200),)]
    widget.hide_for_capture()
    assert not ring.isVisible()
    widget.restore_after_capture()
    assert ring.isVisible()
    widget.close()
    assert not ring._timer.isActive()
    assert not widget._frame_timer.isActive()


def test_ring_uses_native_monitor_origin_with_different_qt_origin(qt_application, monkeypatch):
    screen = SimpleNamespace(
        name=lambda: "DISPLAY2",
        geometry=lambda: QRect(-1280, 0, 1280, 720),
        devicePixelRatio=lambda: 1.5,
    )
    monkeypatch.setattr(focus_overlay.QGuiApplication, "screens", lambda: [screen])
    monkeypatch.setattr(
        focus_overlay,
        "_windows_bounds",
        lambda: {
            "display2": (-1920, -200, 1920, 1080),
        },
    )
    _, point = target_ring._logical_target(-1770, -50)
    assert point == QPointF(-1180, 100)


@pytest.mark.parametrize("cancel", [False, True])
def test_capture_failure_and_cancellation_restore_every_overlay(
    selection,
    qt_application,
    monkeypatch,
    cancel,
):
    draw(selection, qt_application)

    async def run():
        manager, parts = _manager([], monkeypatch)
        manager.attach_focus_selection(selection)
        parts["overlays"].hide_for_capture = Mock()
        parts["overlays"].restore_after_capture = Mock()

        def capture():
            assert not selection._overlay.isVisible()
            raise RuntimeError("capture failed")

        manager._screen_capture_fn = capture
        if cancel:
            task = asyncio.create_task(manager.capture_screenshots())
            await asyncio.sleep(0.01)  # Cancel during the compositor settling delay.
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(RuntimeError, match="capture failed"):
                await manager.capture_screenshots()
        parts["overlays"].restore_after_capture.assert_called_once()
        assert selection._overlay.isVisible()

    asyncio.run(run())


def test_selection_resumes_pending_step_after_voice_started(qt_application, monkeypatch):
    async def run():
        manager, parts = _manager(["Open File [STEP:1/2] [POINT:none]"], monkeypatch)
        _ask(manager, "how do I open this?")
        await _settle(manager)
        step = manager._walkthrough
        parts["hotkey"].pressed.emit()
        manager.cancel_for_selection()
        manager._on_hotkey_released()  # Defensive even if input arbitration missed a release.
        manager._transcription.final_transcript.emit("cancelled voice")
        await asyncio.sleep(0)
        assert manager._state == VoiceState.GUIDING
        assert manager._walkthrough == step
        assert parts["clicks"].active
        assert len(parts["llm"].requests) == 1
        await manager.aclose()

    asyncio.run(run())


def test_new_ui_updates_stay_hidden_until_capture_finishes(qt_application):
    widget = PetCompanionWidget()
    try:
        widget.hide_for_capture()  # Initially hidden companion and bubble.
        widget.set_state(VoiceState.LISTENING)
        widget.show_error("capture in progress")
        widget.fly_to(100, 100)
        assert not widget.isVisible()
        assert not widget.bubble.isVisible()
        assert not widget.target_ring.isVisible()
        widget.restore_after_capture()
        assert widget.isVisible()
    finally:
        widget.close()


def test_capture_worker_remains_hidden_through_repeated_cancellation(
    selection,
    qt_application,
    monkeypatch,
):
    import threading

    draw(selection, qt_application)

    async def run():
        entered, finish = threading.Event(), threading.Event()
        manager, parts = _manager([], monkeypatch)
        manager.attach_focus_selection(selection)

        def capture():
            entered.set()
            assert finish.wait(3)
            return source()

        manager._screen_capture_fn = capture
        task = asyncio.create_task(manager.capture_screenshots())
        while not entered.is_set():
            await asyncio.sleep(0.01)
        try:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not selection._overlay.isVisible()
            assert not task.done()
        finally:
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert selection._overlay.isVisible()

    asyncio.run(run())


def test_cleared_selection_and_expired_ring_not_revived_after_failed_capture(
    selection,
    qt_application,
    monkeypatch,
):
    draw(selection, qt_application)

    async def run():
        manager, _ = _manager([], monkeypatch)
        widget = PetCompanionWidget()
        manager._panel_visibility_controller = widget
        manager.attach_focus_selection(selection)
        widget.fly_to(100, 100)
        manager._screen_capture_fn = Mock(side_effect=RuntimeError("capture failed"))
        task = asyncio.create_task(manager.capture_screenshots())
        await asyncio.sleep(0.01)
        selection.clear()
        widget.target_ring._started -= 2
        with pytest.raises(RuntimeError, match="capture failed"):
            await task
        assert not selection._overlay.isVisible()
        assert not widget.target_ring.isVisible()
        assert not widget.target_ring._timer.isActive()
        widget.close()

    asyncio.run(run())


def test_fresh_chord_waits_for_cancelled_stream_cleanup(qt_application, monkeypatch):
    async def run():
        manager, parts = _manager(["Fresh [POINT:none]"], monkeypatch)
        cleanup = asyncio.Event()

        async def stop_stream():
            await cleanup.wait()
            manager._transcription.final_transcript.emit("stale cancelled transcript")

        manager._transcription.stop_stream = stop_stream
        manager._screen_capture_fn = source
        parts["hotkey"].pressed.emit()
        await asyncio.sleep(0)
        manager.cancel_for_selection()
        parts["hotkey"].pressed.emit()  # A fresh chord while old remote cleanup is still draining.
        await asyncio.sleep(0)
        cleanup.set()
        await asyncio.sleep(0.02)
        assert not parts["llm"].requests
        assert manager._state == VoiceState.LISTENING
        manager._transcription.final_transcript.emit("fresh question")
        await _settle(manager)
        assert len(parts["llm"].requests) == 1
        current_text = parts["llm"].requests[0][-1]["content"][-1]["text"]
        assert current_text == "fresh question"
        await manager.aclose()

    asyncio.run(run())


def test_close_stops_delayed_greeting(qt_application):
    widget = CompanionWidget()
    widget.start()
    widget.close()
    assert not widget._greeting_timer.isActive()
    assert not widget.bubble._type_timer.isActive()
