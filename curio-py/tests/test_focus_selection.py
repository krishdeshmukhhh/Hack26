import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pynput import keyboard, mouse
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication

from curio.focus_selection import FocusRegion, FocusSelectionController
from curio.ui.focus_overlay import DisplayCoordinates, FocusOverlay


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(app, monkeypatch):
    display = DisplayCoordinates((-1920, -200, 1920, 1080), QRect(-1280, -100, 1280, 720))
    monkeypatch.setattr("curio.focus_selection.display_coordinates", lambda: [display])
    monkeypatch.setattr("curio.focus_selection.mouse.Listener", Mock())
    monkeypatch.setattr("curio.focus_selection.keyboard.Listener", Mock())
    c = FocusSelectionController()
    c._modifiers_down = lambda: (
        bool(c._held & {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r})
        and bool(c._held & {keyboard.Key.alt_l, keyboard.Key.alt_r})
    )
    c.start()
    yield c
    c.stop()


def dispatch(c, app, kind, *args):
    c._post(kind, *args)
    app.processEvents()


@pytest.mark.parametrize(
    "start,end",
    [
        ((-1800, 0), (-1700, 100)),
        ((-1700, 100), (-1800, 0)),
        ((-1800, 100), (-1700, 0)),
        ((-1700, 0), (-1800, 100)),
    ],
)
def test_normalized_drags_and_event_order(controller, app, start, end):
    c = controller
    events = []
    c.selection_started.connect(lambda: events.append(("start", c.selecting)))
    c.region_changed.connect(lambda r: events.append(("region", r)))
    dispatch(c, app, "begin", *start)
    assert events == [("start", True)]
    dispatch(c, app, "move", *end)
    assert c.region is None
    dispatch(c, app, "finish", *end)
    assert c.region == FocusRegion(-1800, 0, 100, 100)
    assert events[-1] == ("region", c.region)
    assert not c.selecting
    assert c._overlay.isVisible()


@pytest.mark.parametrize(
    "width,height,valid", [(7, 20, False), (20, 7, False), (0, 0, False), (8, 8, True)]
)
def test_minimum_size(controller, app, width, height, valid):
    dispatch(controller, app, "begin", -1800, 0)
    dispatch(controller, app, "finish", -1800 + width, height)
    assert (controller.region is not None) == valid


def test_replace_cancel_clear_and_capture(controller, app):
    c = controller
    dispatch(c, app, "begin", -1800, 0)
    dispatch(c, app, "finish", -1700, 100)
    old = c.region
    c.hide_for_capture()
    c.hide_for_capture()
    assert not c._overlay.isVisible()
    c.restore_after_capture()
    assert not c._overlay.isVisible()
    c.restore_after_capture()
    assert c._overlay.isVisible()
    dispatch(c, app, "begin", -1600, 0)
    dispatch(c, app, "cancel")
    assert c.region == old
    assert not c.selecting
    dispatch(c, app, "begin", -1600, 0)
    dispatch(c, app, "finish", -1500, 100)
    assert c.region == FocusRegion(-1600, 0, 100, 100)
    c.hide_for_capture()
    dispatch(c, app, "clear")
    c.restore_after_capture()
    assert c.region is None
    assert not c._overlay.isVisible()


def test_clip_to_start_display(controller, app):
    dispatch(controller, app, "begin", -1800, 0)
    dispatch(controller, app, "finish", 100, 1200)
    assert controller.region == FocusRegion(-1800, 0, 1800, 880)


def test_callbacks_queue_and_modifier_release_does_not_end_drag(controller, app):
    c = controller
    c._on_key_press(keyboard.Key.ctrl_l)
    c._on_key_press(keyboard.Key.alt_r)
    c._on_click(-1800, 0, mouse.Button.left, True)
    assert not c.selecting  # No widget/state work on the hook thread.
    app.processEvents()
    assert c.selecting
    c._on_key_release(keyboard.Key.ctrl_l)
    c._on_key_release(keyboard.Key.alt_r)
    c._on_click(-1700, 100, mouse.Button.left, False)
    app.processEvents()
    assert c.region == FocusRegion(-1800, 0, 100, 100)
    c._on_click(-1600, 0, mouse.Button.left, True)
    app.processEvents()
    assert c.region is None


def test_escape_absorbs_release_and_lifecycle(controller, app):
    c = controller
    c._on_key_press(keyboard.Key.ctrl_l)
    c._on_key_press(keyboard.Key.alt_l)
    c._on_click(-1800, 0, mouse.Button.left, True)
    c._on_key_press(keyboard.Key.esc)
    c._on_click(-1700, 100, mouse.Button.left, False)
    app.processEvents()
    assert c.region is None and not c.selecting
    listeners = (c._mouse_listener, c._keyboard_listener)
    c.start()
    assert listeners == (c._mouse_listener, c._keyboard_listener)
    c._post("begin", -1800, 0)
    c.stop()
    c.stop()
    app.processEvents()
    assert not c.selecting and not c._overlay.isVisible()
    for listener in listeners:
        listener.stop.assert_called_once()
    c.start()
    app.processEvents()
    assert not c.selecting


def test_windows_filter_suppresses_only_selection(controller, app):
    c = controller
    c._modifiers_down = lambda: True
    c._mouse_listener.suppress_event.side_effect = None
    data = SimpleNamespace(pt=SimpleNamespace(x=-1800, y=0))
    c._win32_filter(0x201, data)
    c._modifiers_down = lambda: False
    c._win32_filter(0x200, data)
    c._on_key_press(keyboard.Key.esc)
    c._win32_filter(0x202, data)
    assert c._mouse_listener.suppress_event.call_count == 2
    c._win32_filter(0x201, data)
    c._win32_filter(0x202, data)
    c._win32_filter(0x204, data)
    assert c._mouse_listener.suppress_event.call_count == 2


def test_windows_drag_allows_cursor_motion_and_draws_preview(controller, app):
    """Low-level movement suppression freezes Windows' cursor, not just app input."""
    c = controller
    c._modifiers_down = lambda: True

    class Suppressed(Exception):
        pass

    c._mouse_listener.suppress_event.side_effect = Suppressed
    start = SimpleNamespace(pt=SimpleNamespace(x=-1800, y=0))
    end = SimpleNamespace(pt=SimpleNamespace(x=-1700, y=100))
    with pytest.raises(Suppressed):
        c._win32_filter(0x201, start)
    app.processEvents()
    assert c.selecting

    # Returning False skips duplicate pynput callbacks, while returning normally
    # from the native filter lets Windows apply movement to the visible cursor.
    assert c._win32_filter(0x200, end) is False
    app.processEvents()
    assert c._overlay.isVisible()
    assert c._preview == FocusRegion(-1800, 0, 100, 100)
    assert c.region is None

    with pytest.raises(Suppressed):
        c._win32_filter(0x202, end)
    app.processEvents()
    assert c.region == FocusRegion(-1800, 0, 100, 100)
    assert c._overlay.isVisible()
    assert c._mouse_listener.suppress_event.call_count == 2


def test_cancelled_windows_drag_still_allows_cursor_motion(controller, app):
    c = controller
    c._modifiers_down = lambda: True
    data = SimpleNamespace(pt=SimpleNamespace(x=-1800, y=0))
    c._win32_filter(0x201, data)
    c._on_key_press(keyboard.Key.esc)
    c._mouse_listener.suppress_event.reset_mock()
    c._win32_filter(0x200, data)
    c._mouse_listener.suppress_event.assert_not_called()
    c._win32_filter(0x202, data)
    c._mouse_listener.suppress_event.assert_called_once()
    app.processEvents()
    assert not c.selecting
    assert c.region is None


def test_per_display_conversion_and_overlay_flags(app):
    a = DisplayCoordinates((-1920, -200, 1920, 1080), QRect(-1280, -100, 1280, 720))
    b = DisplayCoordinates((0, 0, 2560, 1440), QRect(0, 0, 2560, 1440))
    assert a.logical_rect(FocusRegion(-1770, -50, 300, 150)) == QRect(-1180, 0, 200, 100)
    assert b.logical_rect(FocusRegion(150, 150, 300, 150)) == QRect(150, 150, 300, 150)
    overlay = FocusOverlay()
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert overlay.focusPolicy() == Qt.FocusPolicy.NoFocus
    overlay.close()


def test_rejected_replacement_keeps_previous_region(controller, app):
    c = controller
    dispatch(c, app, "begin", -1800, 0)
    dispatch(c, app, "finish", -1700, 100)
    previous = c.region
    events = []
    c.region_changed.connect(events.append)
    dispatch(c, app, "begin", -1600, 0)
    dispatch(c, app, "finish", -1599, 1)
    assert c.region == previous
    assert events == []
    assert c._overlay.isVisible()


def test_background_events_run_on_qt_thread(controller, app):
    c = controller
    threads = []
    c.selection_started.connect(lambda: threads.append(threading.get_ident()))
    worker = threading.Thread(target=lambda: c._post("begin", -1800, 0))
    worker.start()
    worker.join()
    assert not c.selecting
    app.processEvents()
    assert threads == [threading.get_ident()]


def test_old_hook_and_queued_events_ignored_after_restart(controller, app):
    from curio import focus_selection

    c = controller
    old_callback = focus_selection.mouse.Listener.call_args.kwargs["on_click"]
    c._post("begin", -1800, 0)
    c.stop()
    c.start()
    c._modifiers_down = lambda: True
    old_callback(-1800, 0, mouse.Button.left, True)
    app.processEvents()
    assert not c.selecting


def test_capture_hides_preview_and_restores_latest_state(controller, app):
    c = controller
    dispatch(c, app, "begin", -1800, 0)
    dispatch(c, app, "move", -1700, 100)
    assert c._overlay.isVisible()
    c.hide_for_capture()
    dispatch(c, app, "finish", -1600, 200)
    assert not c._overlay.isVisible()
    c.restore_after_capture()
    assert c._overlay.isVisible()
    assert c.region == FocusRegion(-1800, 0, 200, 200)


def test_display_matching_uses_native_origin_not_scaled_global_origin(app, monkeypatch):
    from curio.ui import focus_overlay

    screen = SimpleNamespace(name=lambda: "DISPLAY2", geometry=lambda: QRect(-1280, 0, 1280, 720))
    monkeypatch.setattr(focus_overlay.sys, "platform", "win32")
    monkeypatch.setattr(
        focus_overlay,
        "_windows_bounds",
        lambda: {
            "display2": (-1920, -200, 1920, 1080),
        },
    )
    monkeypatch.setattr(focus_overlay.QGuiApplication, "screens", lambda: [screen])
    displays = focus_overlay.display_coordinates()
    assert displays[0].physical == (-1920, -200, 1920, 1080)
    assert displays[0].logical == QRect(-1280, 0, 1280, 720)


def test_start_failure_cleans_both_listeners(app, monkeypatch):
    ml, kl = Mock(), Mock()
    monkeypatch.setattr("curio.focus_selection.mouse.Listener", Mock(return_value=ml))
    monkeypatch.setattr("curio.focus_selection.keyboard.Listener", Mock(return_value=kl))
    ml.start.side_effect = RuntimeError("hook unavailable")
    c = FocusSelectionController()
    with pytest.raises(RuntimeError, match="hook unavailable"):
        c.start()
    assert not c._active
    assert c._mouse_listener is c._keyboard_listener is None
    ml.stop.assert_called_once()
    kl.stop.assert_called_once()
