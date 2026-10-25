"""Prepare a fresh captured image of the user's physical desktop selection."""

from __future__ import annotations

import io
import math
from typing import TYPE_CHECKING

from PIL import Image

from curio.screen_capture import ScreenshotImage

if TYPE_CHECKING:
    from curio.focus_selection import FocusRegion


def focus_screenshots(
    screenshots: list[ScreenshotImage], region: FocusRegion | None
) -> list[ScreenshotImage]:
    """Return one focused image, or the original list when no display intersects.

    This consumes the current request's captures, never a cached selection image.
    Physical bounds describe the clipped selection; encoded pixels use a uniform
    scale so the existing pixel and norm1000 point mapper can use this metadata.
    Cropping cannot recover detail lost by the original capture's downscaling.
    """
    if region is None or region.width <= 0 or region.height <= 0:
        return screenshots

    for shot in screenshots:
        left = max(region.left, shot.monitor_left)
        top = max(region.top, shot.monitor_top)
        right = min(region.left + region.width, shot.monitor_left + shot.display_width_px)
        bottom = min(region.top + region.height, shot.monitor_top + shot.display_height_px)
        if left >= right or top >= bottom:
            continue

        width, height = right - left, bottom - top
        with Image.open(io.BytesIO(shot.jpeg_bytes)) as source:
            # capture_all rounds each resized axis down independently. Its nominal
            # scale is therefore insufficient to locate the source pixels exactly.
            x_ratio = source.width / shot.display_width_px
            y_ratio = source.height / shot.display_height_px
            scale = min(x_ratio, y_ratio)
            image_width = math.ceil(width * scale)
            image_height = math.ceil(height * scale)
            # Sample at a uniform physical spacing rather than stretching the
            # rounded crop dimensions independently on X and Y. The final encoded
            # pixel may cover a fractional physical pixel at the selection edge.
            cropped = source.convert("RGB").transform(
                (image_width, image_height),
                Image.Transform.AFFINE,
                (
                    x_ratio / scale, 0, (left - shot.monitor_left) * x_ratio,
                    0, y_ratio / scale, (top - shot.monitor_top) * y_ratio,
                ),
                resample=Image.Resampling.BICUBIC,
            )
            buf = io.BytesIO()
            cropped.save(buf, format="JPEG", quality=80)

        return [ScreenshotImage(
            jpeg_bytes=buf.getvalue(),
            label=(
                "user's selected focus area "
                f"(image dimensions: {image_width}x{image_height} pixels)"
            ),
            is_cursor_screen=shot.is_cursor_screen,
            display_width_px=width,
            display_height_px=height,
            image_width_px=image_width,
            image_height_px=image_height,
            scale=scale,
            monitor_left=left,
            monitor_top=top,
        )]

    return screenshots
