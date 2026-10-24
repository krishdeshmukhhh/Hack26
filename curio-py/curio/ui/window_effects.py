"""Win32 tweaks shared by Curio's floating overlay windows."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtWidgets import QWidget


def make_overlay_window(widget: QWidget) -> None:
    """Make a top-level widget click-through and free of Windows 11 chrome.

    Removes DWM borders, shadows, rounded corners and background, and makes
    the window ignore the mouse. Windows resets some of this when a window
    is shown, so call it from ``showEvent``.
    """
    if sys.platform != "win32":
        return

    hwnd = int(widget.winId())
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    # Force WS_EX_LAYERED + WS_EX_TRANSPARENT for per-pixel alpha
    GWL_EXSTYLE = -20  # noqa: N806
    WS_EX_LAYERED = 0x00080000  # noqa: N806
    WS_EX_TRANSPARENT = 0x00000020  # noqa: N806
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
    )

    # Disable DWM non-client rendering (removes Win11 border/shadow)
    DWMWA_NCRENDERING_POLICY = 2  # noqa: N806
    policy = ctypes.c_int(1)  # DWMNCRP_DISABLED
    dwmapi.DwmSetWindowAttribute(
        hwnd, DWMWA_NCRENDERING_POLICY,
        ctypes.byref(policy), ctypes.sizeof(policy),
    )

    # Remove DWM shadow
    DWMWA_ALLOW_NCPAINT = 4  # noqa: N806
    no_paint = ctypes.c_int(0)
    dwmapi.DwmSetWindowAttribute(
        hwnd, DWMWA_ALLOW_NCPAINT,
        ctypes.byref(no_paint), ctypes.sizeof(no_paint),
    )

    # Disable Win11 rounded corners
    DWMWA_WINDOW_CORNER_PREFERENCE = 33  # noqa: N806
    DWMWCP_DONOTROUND = ctypes.c_int(1)  # noqa: N806
    dwmapi.DwmSetWindowAttribute(
        hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(DWMWCP_DONOTROUND), ctypes.sizeof(DWMWCP_DONOTROUND),
    )

    # Extend DWM frame into entire client area (enables full alpha blending)
    class MARGINS(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("left", ctypes.c_int), ("right", ctypes.c_int),
            ("top", ctypes.c_int), ("bottom", ctypes.c_int),
        ]

    margins = MARGINS(-1, -1, -1, -1)
    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
