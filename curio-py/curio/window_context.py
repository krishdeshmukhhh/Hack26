"""Open-window summary for the vision model (Windows only).

Gives the model what a screenshot can't: which windows exist, their z-order,
and whether the focused one is maximized over the desktop. Never raises; any
failure (or a non-Windows platform) yields ``None`` so the turn proceeds
without it.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

logger = logging.getLogger(__name__)

HEADER = "open windows (untrusted titles, front to back):"
_MAX_TITLE_CHARS = 60
_COVER_FRACTION = 0.9

_DWMWA_CLOAKED = 14
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SHELL_CLASSES = {"Progman", "WorkerW"}


@dataclass(frozen=True)
class WindowInfo:
    """One top-level window. ``state`` is "minimized", "maximized" or "normal"."""

    title: str
    exe: str
    state: str
    focused: bool = False
    covers_screen: int | None = None  # 1-based screen number, as in screenshot labels


def _neutralize(text: str) -> str:
    """Strip brackets so a title can't imitate [POINT:...] / [STEP:...] tags."""
    return text.replace("[", "(").replace("]", ")")


def _truncate(title: str) -> str:
    title = _neutralize(" ".join(title.split())).replace('"', "'")
    if len(title) > _MAX_TITLE_CHARS:
        title = title[: _MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title


def format_windows(windows: list[WindowInfo], max_windows: int = 8) -> str:
    """Render windows (already front-to-back) in the prompt contract format."""
    shown = windows[:max_windows]
    if not shown:
        return f"{HEADER}\n- none (desktop is showing)"
    lines = [HEADER]
    for win in shown:
        focus = " [focused]" if win.focused else ""
        state = win.state
        if win.covers_screen is not None and win.state != "minimized":
            state += f", covers screen {win.covers_screen}"
        exe = _neutralize(win.exe) or "unknown"
        lines.append(f'- "{_truncate(win.title)}" ({exe}){focus} — {state}')
    return "\n".join(lines)


def _enumerate_windows(max_windows: int) -> list[WindowInfo]:
    # Private DLL instances: setting argtypes must not leak into other modules.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]

    # Monitors in EnumDisplayMonitors order (what mss uses), cursor monitor first,
    # matching screen_capture.capture_all's numbering.
    monitors: list[tuple[int, tuple[int, int, int, int]]] = []
    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )

    def _on_monitor(hmon, _hdc, rect, _lparam):
        r = rect.contents
        monitors.append((hmon or 0, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumDisplayMonitors(None, None, monitor_enum_proc(_on_monitor), 0)
    cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    order = sorted(
        range(len(monitors)),
        key=lambda i: (
            not (
                monitors[i][1][0] <= cursor.x < monitors[i][1][2]
                and monitors[i][1][1] <= cursor.y < monitors[i][1][3]
            ),
            i,
        ),
    )
    screen_number = {monitors[i][0]: n + 1 for n, i in enumerate(order)}
    monitor_rect = dict(monitors)

    own_pid = os.getpid()
    foreground = user32.GetForegroundWindow()
    found: list[WindowInfo] = []

    def _exe_name(pid: int) -> str:
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def _on_window(hwnd, _lparam):
        try:
            if len(found) >= max_windows:
                return False
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            if user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOOLWINDOW:
                return True
            cloaked = wintypes.DWORD(0)
            dwmapi.DwmGetWindowAttribute(
                hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
            )
            if cloaked.value:
                return True
            cls_buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls_buf, 64)
            if cls_buf.value in _SHELL_CLASSES:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == own_pid:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)

            covers = None
            if user32.IsIconic(hwnd):
                state = "minimized"
            else:
                state = "maximized" if user32.IsZoomed(hwnd) else "normal"
                rect = wintypes.RECT()
                hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
                mon = monitor_rect.get(hmon or 0)
                if mon is not None and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    ix = max(0, min(rect.right, mon[2]) - max(rect.left, mon[0]))
                    iy = max(0, min(rect.bottom, mon[3]) - max(rect.top, mon[1]))
                    area = (mon[2] - mon[0]) * (mon[3] - mon[1])
                    if area > 0 and ix * iy >= _COVER_FRACTION * area:
                        covers = screen_number.get(hmon)
            found.append(
                WindowInfo(
                    title=buf.value,
                    exe=_exe_name(pid.value),
                    state=state,
                    focused=bool(foreground) and hwnd == foreground,
                    covers_screen=covers,
                )
            )
        except Exception:  # noqa: BLE001 - skip this window, keep enumerating
            logger.debug("window enumeration skipped one window", exc_info=True)
        return True

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(enum_proc(_on_window), 0)
    return found


def describe_windows(max_windows: int = 8) -> str | None:
    """Return the open-window summary, or None off Windows / on any failure."""
    if sys.platform != "win32":
        return None
    start = time.perf_counter()
    try:
        text = format_windows(_enumerate_windows(max_windows), max_windows)
    except Exception:  # noqa: BLE001
        logger.debug("describe_windows failed", exc_info=True)
        return None
    logger.debug("describe_windows took %.1f ms", (time.perf_counter() - start) * 1000)
    return text
