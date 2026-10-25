from __future__ import annotations

import io
from dataclasses import dataclass

import mss
from PIL import Image
from pynput.mouse import Controller as MouseController

_MAX_LONG_EDGE = 1280
_JPEG_QUALITY = 80


@dataclass
class ScreenshotImage:
    """A single captured monitor encoded as JPEG."""

    jpeg_bytes: bytes
    label: str
    is_cursor_screen: bool
    display_width_px: int
    display_height_px: int
    image_width_px: int
    image_height_px: int
    scale: float           # downscale ratio (e.g. 0.667 for 1920→1280). 1.0 if no downscale.
    monitor_left: int      # global X origin of this monitor
    monitor_top: int       # global Y origin of this monitor


def compose_screen_label(
    screen_index: int, total_screens: int, is_cursor_screen: bool
) -> str:
    """Return a human-readable label for a captured screen.

    When there is only one screen the label is simplified. When multiple
    screens are present, each label includes a 1-based position and whether
    the cursor is currently on that screen.
    """
    if total_screens == 1:
        return "user's screen (cursor is here)"

    position = screen_index + 1
    if is_cursor_screen:
        return f"screen {position} of {total_screens} \u2014 cursor is on this screen (primary focus)"
    return f"screen {position} of {total_screens} \u2014 secondary screen"


def _cursor_in_monitor(cx: int, cy: int, monitor: dict) -> bool:
    """Return True if cursor (cx, cy) is inside *monitor* bounds."""
    return (
        monitor["left"] <= cx < monitor["left"] + monitor["width"]
        and monitor["top"] <= cy < monitor["top"] + monitor["height"]
    )


def capture_all() -> list[ScreenshotImage]:
    """Capture every monitor, returning the cursor screen first.

    Each capture is downscaled so the long edge is at most 1280 px and
    encoded as JPEG quality 80.
    """
    cx, cy = MouseController().position

    with mss.mss() as sct:
        # monitors[0] is the virtual-screen aggregate; skip it.
        physical_monitors = sct.monitors[1:]

        # Tag each monitor with its original index and whether the cursor is on it.
        tagged: list[tuple[int, dict, bool]] = []
        for idx, mon in enumerate(physical_monitors):
            tagged.append((idx, mon, _cursor_in_monitor(cx, cy, mon)))

        # Sort: cursor screen first, then preserve original order.
        tagged.sort(key=lambda t: (not t[2], t[0]))

        results: list[ScreenshotImage] = []
        total = len(tagged)

        for screen_index, (_, mon, is_cursor) in enumerate(tagged):
            grab = sct.grab(mon)
            display_w, display_h = grab.width, grab.height

            img = Image.frombytes("RGB", (display_w, display_h), grab.rgb)

            # Downscale if the long edge exceeds the limit.
            long_edge = max(display_w, display_h)
            if long_edge > _MAX_LONG_EDGE:
                scale = _MAX_LONG_EDGE / long_edge
                new_w = int(display_w * scale)
                new_h = int(display_h * scale)
                img = img.resize((new_w, new_h), Image.LANCZOS)
            else:
                scale = 1.0

            image_w, image_h = img.size

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
            jpeg_bytes = buf.getvalue()

            # The system prompt tells the model to use these dimensions as the
            # POINT coordinate space, so they must be part of the label.
            label = (
                f"{compose_screen_label(screen_index, total, is_cursor)} "
                f"(image dimensions: {image_w}x{image_h} pixels)"
            )

            results.append(
                ScreenshotImage(
                    jpeg_bytes=jpeg_bytes,
                    label=label,
                    is_cursor_screen=is_cursor,
                    display_width_px=display_w,
                    display_height_px=display_h,
                    image_width_px=image_w,
                    image_height_px=image_h,
                    scale=scale,
                    monitor_left=mon["left"],
                    monitor_top=mon["top"],
                )
            )

    return results


# ---- cheap change-detection probe (used to decide when a click's effect settled) ----

PROBE_WIDTH_PX = 160
# A pixel counts as changed when its grayscale value moved by more than this.
PROBE_PIXEL_DELTA = 24
# Fraction of compared probe pixels that must change for the frames to differ.
PROBE_CHANGED_FRACTION = 0.004


@dataclass(frozen=True)
class ProbeFrame:
    """A tiny grayscale grab of one monitor, with an optional ignored rectangle."""

    width: int
    height: int
    pixels: bytes
    mask: tuple[int, int, int, int] | None = None  # x0, y0, x1, y1 in probe pixels

    def differs_from(self, other: ProbeFrame) -> bool:
        if (self.width, self.height) != (other.width, other.height):
            return True
        a, b, w = self.pixels, other.pixels, self.width
        x0, y0, x1, y1 = self.mask or (0, 0, 0, 0)
        compared = 0
        changed = 0
        for i in range(len(a)):
            if self.mask is not None and y0 <= i // w < y1 and x0 <= i % w < x1:
                continue
            compared += 1
            if abs(a[i] - b[i]) > PROBE_PIXEL_DELTA:
                changed += 1
        return compared > 0 and changed / compared > PROBE_CHANGED_FRACTION


def grab_probe(
    monitor_left: int,
    monitor_top: int,
    *,
    mask_center: tuple[int, int] | None = None,
    mask_radius_px: int = 0,
) -> ProbeFrame | None:
    """Grab the monitor at (left, top) as a 160 px wide grayscale frame.

    ``mask_center`` (global screen px) plus ``mask_radius_px`` blank out the
    area around the cursor, where our own companion and pill animate.
    """
    with mss.mss() as sct:
        mons = sct.monitors[1:]
        mon = next(
            (m for m in mons if m["left"] == monitor_left and m["top"] == monitor_top),
            mons[0] if mons else None,
        )
        if mon is None:
            return None
        grab = sct.grab(mon)
    img = Image.frombytes("RGB", (grab.width, grab.height), grab.rgb).convert("L")
    scale = PROBE_WIDTH_PX / grab.width
    small = img.resize((PROBE_WIDTH_PX, max(1, round(grab.height * scale))), Image.BOX)
    mask = None
    if mask_center is not None and mask_radius_px > 0:
        cx = (mask_center[0] - mon["left"]) * scale
        cy = (mask_center[1] - mon["top"]) * scale
        r = mask_radius_px * scale
        mask = (int(cx - r), int(cy - r), int(cx + r) + 1, int(cy + r) + 1)
    return ProbeFrame(small.width, small.height, small.tobytes(), mask)


def cursor_position() -> tuple[int, int]:
    x, y = MouseController().position
    return int(x), int(y)
