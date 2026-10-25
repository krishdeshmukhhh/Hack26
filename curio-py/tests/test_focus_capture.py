"""Focused capture tests use only the documented physical region fields."""

import io
from dataclasses import dataclass

import pytest
from PIL import Image

from curio.focus_capture import focus_screenshots
from curio.point_mapper import map_point_to_screen
from curio.point_parser import PointTag
from curio.screen_capture import ScreenshotImage


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int


def shot(size=(120, 80), display=(120, 80), origin=(0, 0), color="red"):
    image = Image.new("RGB", size, color)
    # A distinctive central patch, away from JPEG boundaries.
    image.paste("blue", (size[0] // 4, size[1] // 4,
                         3 * size[0] // 4, 3 * size[1] // 4))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=95)
    return ScreenshotImage(buf.getvalue(), "source", False, *display, *size,
                           size[0] / display[0], *origin)


def test_no_selection_returns_original_list_without_decoding():
    screenshots = [shot()]
    screenshots[0].jpeg_bytes = b"not decoded"
    assert focus_screenshots(screenshots, None) is screenshots


@pytest.mark.parametrize("region", [Region(500, 500, 20, 20), Region(120, 0, 10, 10),
                                   Region(0, 0, 0, 10), Region(0, 0, 10, -1)])
def test_missing_display_or_empty_intersection_falls_back(region):
    screenshots = [shot()]
    assert focus_screenshots(screenshots, region) is screenshots
    assert focus_screenshots([], region) == []


def test_crop_contents_metadata_and_label():
    source = shot()
    result = focus_screenshots([source], Region(30, 20, 60, 40))
    assert len(result) == 1
    crop = result[0]
    with Image.open(io.BytesIO(crop.jpeg_bytes)) as image:
        assert image.size == (60, 40)
        r, g, b = image.getpixel((30, 20))
        assert b > 220 and r < 30 and g < 30
    assert (crop.monitor_left, crop.monitor_top) == (30, 20)
    assert (crop.display_width_px, crop.display_height_px) == (60, 40)
    assert crop.scale == 1
    assert "selected focus area" in crop.label
    assert "60x40" in crop.label
    assert crop.is_cursor_screen is source.is_cursor_screen
    assert source.label == "source"


def test_each_call_uses_fresh_contents():
    region = Region(0, 0, 20, 20)
    first = focus_screenshots([shot(color="red")], region)[0]
    second = focus_screenshots([shot(color="green")], region)[0]
    assert first.jpeg_bytes != second.jpeg_bytes


def test_negative_origin_secondary_display_and_clipping():
    screenshots = [shot(), shot(origin=(-120, -80))]
    result = focus_screenshots(screenshots, Region(-130, -90, 40, 40))
    crop = result[0]
    assert len(result) == 1
    assert (crop.monitor_left, crop.monitor_top) == (-120, -80)
    assert (crop.display_width_px, crop.display_height_px) == (30, 30)
    assert map_point_to_screen(PointTag(10, 10, ""), result) == (-110, -70)
    assert map_point_to_screen(PointTag(500, 500, ""), result, "norm1000") == (-105, -65)


def test_scaled_crop_pixels_and_point_modes():
    source = shot(size=(60, 40), display=(120, 80), origin=(-120, -80))
    result = focus_screenshots([source], Region(-90, -60, 60, 40))
    crop = result[0]
    assert (crop.image_width_px, crop.image_height_px) == (30, 20)
    assert crop.scale == 0.5
    with Image.open(io.BytesIO(crop.jpeg_bytes)) as image:
        r, g, b = image.getpixel((15, 10))
        assert b > 220 and r < 30 and g < 30
    assert map_point_to_screen(PointTag(15, 10, ""), result) == (-60, -40)
    assert map_point_to_screen(PointTag(500, 500, ""), result, "norm1000") == (-60, -40)


def test_rounding_uses_actual_encoded_dimensions_and_uniform_mapping():
    source = shot(size=(60, 39), display=(121, 80), origin=(-121, -80))
    source.scale = 0.5  # Nominal capture scale differs from both actual axis ratios.
    result = focus_screenshots([source], Region(-100, -60, 61, 41))
    crop = result[0]
    assert crop.scale == pytest.approx(39 / 80)
    assert (crop.image_width_px, crop.image_height_px) == (30, 20)
    assert map_point_to_screen(PointTag(20, 10, ""), result) == (-59, -40)
    assert map_point_to_screen(PointTag(1000, 1000, ""), result, "norm1000") == (-39, -19)


def test_clip_right_and_bottom_edges():
    result = focus_screenshots([shot(origin=(-120, -80))], Region(-20, -10, 80, 80))
    crop = result[0]
    assert (crop.monitor_left, crop.monitor_top) == (-20, -10)
    assert (crop.display_width_px, crop.display_height_px) == (20, 10)
    with Image.open(io.BytesIO(crop.jpeg_bytes)) as image:
        assert image.size == (20, 10)
        r, g, b = image.getpixel((10, 5))
        assert r > 220 and g < 30 and b < 30


def test_rounded_source_crop_uses_decoded_pixels_instead_of_nominal_scale():
    source = shot(size=(60, 39), display=(121, 80))
    source.scale = 0.9
    # Incorrect advertised encoded dimensions must not determine the crop pixels.
    source.image_width_px = 120
    source.image_height_px = 80
    result = focus_screenshots([source], Region(40, 30, 30, 20))
    crop = result[0]
    with Image.open(io.BytesIO(crop.jpeg_bytes)) as image:
        assert image.size == (15, 10)
        r, g, b = image.getpixel((7, 5))
        assert b > 220 and r < 30 and g < 30
