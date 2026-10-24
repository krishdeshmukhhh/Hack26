"""Map POINT tag coordinates from screenshot image space to real screen pixels."""

from __future__ import annotations

from curio.point_parser import PointTag
from curio.screen_capture import ScreenshotImage


def map_point_to_screen(
    tag: PointTag,
    screenshots: list[ScreenshotImage],
    point_coords: str = "pixel",
) -> tuple[int, int] | None:
    """Map POINT tag coordinates to absolute screen pixels.

    Args:
        tag: Parsed POINT tag with x, y in screenshot image space.
        screenshots: Captured screenshots with scale and monitor offset metadata.
        point_coords: "pixel" if x, y are screenshot pixels, "norm1000" if they
            are on a 0-1000 grid spanning the screenshot.

    Returns:
        (real_x, real_y) in global screen coordinates, or None if no screenshots.
    """
    if not screenshots:
        return None

    # Select target screenshot (1-indexed screen number)
    if tag.screen is not None and 1 <= tag.screen <= len(screenshots):
        shot = screenshots[tag.screen - 1]
    else:
        shot = screenshots[0]  # cursor's screen (first in list)

    if point_coords == "norm1000":
        real_x = shot.monitor_left + int(min(tag.x, 1000) / 1000 * shot.display_width_px)
        real_y = shot.monitor_top + int(min(tag.y, 1000) / 1000 * shot.display_height_px)
    else:
        real_x = shot.monitor_left + int(tag.x / shot.scale)
        real_y = shot.monitor_top + int(tag.y / shot.scale)
    return (real_x, real_y)
