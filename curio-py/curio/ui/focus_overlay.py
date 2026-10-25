"""Click-through focus rectangle and explicit per-monitor coordinate conversion."""

from __future__ import annotations

import ctypes
import math
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from curio.ui.window_effects import make_overlay_window

if TYPE_CHECKING:
    from curio.focus_selection import FocusRegion


@dataclass(frozen=True)
class DisplayCoordinates:
    """Physical bounds and Qt logical bounds of ONE display, never global scaling."""

    physical: tuple[int, int, int, int]
    logical: QRect
    screen: object = None

    def logical_point(self, x: int, y: int) -> QPointF:
        left, top, width, height = self.physical
        return QPointF(
            self.logical.x() + (x - left) * self.logical.width() / width,
            self.logical.y() + (y - top) * self.logical.height() / height,
        )

    def contains(self, x: int, y: int) -> bool:
        left, top, width, height = self.physical
        return left <= x < left + width and top <= y < top + height

    def logical_rect(self, region: FocusRegion) -> QRect:
        left, top, width, height = self.physical
        sx, sy = self.logical.width() / width, self.logical.height() / height
        x = self.logical.x() + (region.left - left) * sx
        y = self.logical.y() + (region.top - top) * sy
        # Enclose the physical area even for fractional scaling factors.
        return QRect(
            math.floor(x),
            math.floor(y),
            math.ceil(x + region.width * sx) - math.floor(x),
            math.ceil(y + region.height * sy) - math.floor(y),
        )


def _windows_bounds() -> dict[str, tuple[int, int, int, int]]:
    """Match native physical monitor bounds to QScreen by Windows device name."""
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("monitor", wintypes.RECT),
            ("work", wintypes.RECT),
            ("flags", wintypes.DWORD),
            ("device", wintypes.WCHAR * 32),
        ]

    user32 = ctypes.windll.user32
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    result = {}
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HANDLE,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    @callback_type
    def collect(handle, _dc, _rect, _data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.monitor
            result[info.device.casefold()] = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        return True

    previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        if not user32.EnumDisplayMonitors(None, None, collect, 0):
            raise ctypes.WinError()
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)
    return result


def _match_native_bounds(screen, bounds: dict, used: set) -> tuple | None:
    """Native bounds for a QScreen: by device name, else by size/origin.

    Qt 6 on Windows may name screens by monitor model (e.g. "N160JME_GE1") while the
    native enumeration is keyed by device name (DISPLAY1), so names alone can miss.
    """
    physical = bounds.get(screen.name().casefold())
    if physical is not None:
        return physical
    logical = screen.geometry()
    ratio = screen.devicePixelRatio()
    size = (round(logical.width() * ratio), round(logical.height() * ratio))
    candidates = [
        b for key, b in bounds.items() if key not in used and (b[2], b[3]) == size
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda b: abs(b[0] - logical.x() * ratio) + abs(b[1] - logical.y() * ratio),
    )


def display_coordinates() -> list[DisplayCoordinates]:
    """Called on the Qt thread. Windows origins come from native monitor metadata."""
    bounds = _windows_bounds() if sys.platform == "win32" else {}
    used: set = set()
    displays = []
    for screen in QGuiApplication.screens():
        logical = screen.geometry()
        physical = _match_native_bounds(screen, bounds, used)
        if physical is not None:
            used.update(k for k, b in bounds.items() if b == physical)
        else:
            ratio = screen.devicePixelRatio()
            physical = (
                round(logical.x() * ratio),
                round(logical.y() * ratio),
                round(logical.width() * ratio),
                round(logical.height() * ratio),
            )
        displays.append(DisplayCoordinates(physical, logical, screen))
    return displays


def logical_target(x: int, y: int):
    """One physical-to-Qt boundary for selection, target pulses and pet placement."""
    for display in display_coordinates():
        if display.contains(x, y):
            return display.screen, display.logical_point(x, y)
    return None, QPointF(x, y)


class FocusOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def show_region(self, region: FocusRegion, display: DisplayCoordinates) -> None:
        self.setGeometry(display.logical_rect(region))
        self.show()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        make_overlay_window(self)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(70, 150, 255, 28))
        painter.setPen(QPen(QColor(70, 150, 255, 230), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
