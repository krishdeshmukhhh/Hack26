"""Global Ctrl+Alt selection. Public coordinates are physical desktop pixels.

Windows suppresses only the selection's left down/up via pynput's
win32_event_filter (never suppress=True). Movement passes through so Windows
can update the cursor. Escape still swallows the matching button-up.
Other platforms observe the gesture without suppression.
Input arbitration with voice/walkthrough listeners belongs to integration:
selection_started is queued and cannot arbitrate another listener's hook race.

Manual Windows QA still needed: drag over another application's controls,
release modifiers before the button, cancel with Escape while dragging, and
repeat on negative-origin monitors with different scaling. Elevated windows
may require the application to run at the same integrity level for hooks.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from dataclasses import dataclass

from pynput import keyboard, mouse
from PySide6.QtCore import QObject, Qt, Signal, Slot

from curio.ui.focus_overlay import DisplayCoordinates, FocusOverlay, display_coordinates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FocusRegion:
    left: int
    top: int
    width: int
    height: int


class FocusSelectionController(QObject):
    selection_started = Signal()
    region_changed = Signal(object)
    # Input-thread notification for the hotkey arbiter ONLY; connect directly.
    # Emitted before Windows suppress_event() raises to stop the hook chain.
    selection_input_started = Signal()
    ordinary_clicked = Signal()
    _event = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._region: FocusRegion | None = None
        self._selecting = False
        self._overlay = FocusOverlay()
        self._display: DisplayCoordinates | None = None
        self._region_display: DisplayCoordinates | None = None
        self._anchor = (0, 0)
        self._preview: FocusRegion | None = None
        self._capture_depth = 0
        self._mouse_listener = None
        self._keyboard_listener = None
        self._lock = threading.RLock()
        self._held = set()
        self._gesture = False
        self._cancelled = False
        self._generation = 0
        self._active = False
        self._callback_error_logged = False
        self._event.connect(self._receive, Qt.ConnectionType.QueuedConnection)

    @property
    def region(self) -> FocusRegion | None:
        return self._region

    @property
    def selecting(self) -> bool:
        return self._selecting

    def start(self) -> None:
        """Install listeners; call lifecycle and capture methods on the Qt thread."""
        if self._active:
            return
        self._active = True
        self._generation += 1
        generation = self._generation

        def guarded(callback):
            def invoke(*args):
                try:
                    with self._lock:
                        if self._active and generation == self._generation:
                            return callback(*args)
                except Exception as exc:
                    # pynput's own control-flow exceptions (stop / suppress_event)
                    # must reach the listener; anything else must not kill it.
                    if isinstance(exc, keyboard.Listener.StopException) or (
                        "Suppress" in type(exc).__name__
                    ):
                        raise
                    if not self._callback_error_logged:
                        self._callback_error_logged = True
                        logger.warning("focus selection input callback failed", exc_info=True)
                return None

            return invoke

        options = {}
        if sys.platform == "win32":
            options["win32_event_filter"] = guarded(self._win32_filter)
        self._mouse_listener = mouse.Listener(
            on_click=guarded(self._on_click),
            on_move=guarded(self._on_move),
            **options,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=guarded(self._on_key_press),
            on_release=guarded(self._on_key_release),
        )
        try:
            self._keyboard_listener.start()
            self._mouse_listener.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        with self._lock:
            self._active = False
            self._generation += 1
            listeners = (self._mouse_listener, self._keyboard_listener)
            self._mouse_listener = self._keyboard_listener = None
            self._held.clear()
            self._gesture = self._cancelled = False
        for listener in listeners:
            if listener is not None:
                listener.stop()
        self._selecting = False
        self._preview = None
        self._capture_depth = 0
        self.clear()
        self._overlay.close()

    def clear(self) -> None:
        self._region_display = None
        self._selecting = False
        self._preview = None
        if self._region is not None:
            self._region = None
            self.region_changed.emit(None)
        self._overlay.hide()

    def hide_for_capture(self) -> None:
        self._capture_depth += 1
        self._overlay.hide()

    def restore_after_capture(self) -> None:
        if self._capture_depth:
            self._capture_depth -= 1
            if not self._capture_depth:
                self._render()

    def _post(self, kind: str, *args) -> None:
        self._event.emit((self._generation, kind, args))

    def _on_key_press(self, key, injected=False) -> None:
        with self._lock:
            self._held.add(key)
            if key == keyboard.Key.esc and self._gesture:
                self._cancelled = True
                self._post("cancel")

    def _on_key_release(self, key, injected=False) -> None:
        with self._lock:
            self._held.discard(key)

    def _modifiers_down(self) -> bool:
        if sys.platform == "win32":
            state = ctypes.windll.user32.GetAsyncKeyState
            return bool(state(0x11) & 0x8000 and state(0x12) & 0x8000)
        return bool(self._held & {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}) and bool(
            self._held & {keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr}
        )

    def _on_click(self, x, y, button, pressed, injected=False) -> None:
        if button != mouse.Button.left:
            return
        with self._lock:
            if pressed:
                if self._modifiers_down():
                    self._gesture = True
                    self._cancelled = False
                    self.selection_input_started.emit()
                    self._post("begin", int(x), int(y))
                else:
                    self._post("clear")
            elif self._gesture:
                if not self._cancelled:
                    self._post("finish", int(x), int(y))
                self._gesture = self._cancelled = False

    def _on_move(self, x, y, injected=False) -> None:
        with self._lock:
            if self._gesture and not self._cancelled:
                self._post("move", int(x), int(y))

    def _win32_filter(self, message, data):
        """Dispatch here, before suppression prevents pynput's normal callbacks."""
        with self._lock:
            # Suppressing WM_MOUSEMOVE freezes the native cursor. Blocking the
            # button pair alone prevents an underlying application drag.
            suppress = self._gesture and message == 0x202
            if message == 0x201:
                modified = self._modifiers_down()
                suppress = modified
                if modified:
                    self._gesture = True
                    self._cancelled = False
                    self.selection_input_started.emit()
                    self._post("begin", data.pt.x, data.pt.y)
                else:
                    self._post("clear")
            elif message == 0x202 and self._gesture:
                if not self._cancelled:
                    self._post("finish", data.pt.x, data.pt.y)
                self._gesture = self._cancelled = False
            elif message == 0x200:
                self._on_move(data.pt.x, data.pt.y)
            if suppress:
                self._mouse_listener.suppress_event()
        # Skip duplicate pynput callbacks, but allow normal events to the OS.
        return False

    @Slot(object)
    def _receive(self, event) -> None:
        generation, kind, args = event
        if not self._active or generation != self._generation:
            return
        if kind == "clear":
            self.clear()
            self.ordinary_clicked.emit()
        elif kind == "begin":
            self._anchor = args
            self._display = next((d for d in display_coordinates() if d.contains(*args)), None)
            self._selecting = True
            self._preview = None
            self._overlay.hide()
            self.selection_started.emit()
        elif kind == "cancel":
            self._selecting = False
            self._preview = None
            self._render()
        elif kind in ("move", "finish") and self._selecting:
            self._preview = self._box(*args)
            if kind == "finish":
                self._selecting = False
                candidate = self._preview
                if candidate and candidate.width >= 8 and candidate.height >= 8:
                    self._region_display = self._display
                    if self._region != candidate:
                        self._region = candidate
                        self.region_changed.emit(candidate)
                self._preview = None
            self._render()

    def _box(self, x: int, y: int) -> FocusRegion | None:
        if self._display is None:
            return None
        left, top, width, height = self._display.physical
        x, y = min(max(x, left), left + width), min(max(y, top), top + height)
        ax, ay = self._anchor
        return FocusRegion(min(ax, x), min(ay, y), abs(x - ax), abs(y - ay))

    def _render(self) -> None:
        region = self._preview if self._selecting else self._region
        display = self._display if self._selecting else self._region_display
        if not self._capture_depth and region and display and region.width and region.height:
            self._overlay.show_region(region, display)
        else:
            self._overlay.hide()
