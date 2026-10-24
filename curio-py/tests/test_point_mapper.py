"""Tests for POINT tag coordinate mapping from image space to screen pixels."""

from __future__ import annotations

import pytest

from curio.point_parser import PointTag
from curio.point_mapper import map_point_to_screen
from curio.screen_capture import ScreenshotImage


def _make_shot(scale: float, left: int, top: int) -> ScreenshotImage:
    """Create a minimal ScreenshotImage for mapping tests."""
    return ScreenshotImage(
        jpeg_bytes=b"",
        label="test",
        is_cursor_screen=True,
        display_width_px=1920,
        display_height_px=1080,
        image_width_px=1280,
        image_height_px=720,
        scale=scale,
        monitor_left=left,
        monitor_top=top,
    )


class TestMapPointToScreen:
    """map_point_to_screen converts image-space coordinates to real screen pixels."""

    def test_single_monitor_scaled(self) -> None:
        tag = PointTag(640, 360, "btn")
        shot = _make_shot(scale=0.667, left=0, top=0)
        assert map_point_to_screen(tag, [shot]) == (959, 539)

    def test_no_downscale(self) -> None:
        tag = PointTag(100, 200, "x")
        shot = _make_shot(scale=1.0, left=0, top=0)
        assert map_point_to_screen(tag, [shot]) == (100, 200)

    def test_multi_monitor_offset(self) -> None:
        tag = PointTag(100, 100, "term")
        shot = _make_shot(scale=0.5, left=1920, top=0)
        assert map_point_to_screen(tag, [shot]) == (2120, 200)

    def test_screen_number_selects_correct_shot(self) -> None:
        tag = PointTag(50, 50, "x", screen=2)
        shot1 = _make_shot(scale=1.0, left=0, top=0)
        shot2 = _make_shot(scale=1.0, left=1920, top=0)
        assert map_point_to_screen(tag, [shot1, shot2]) == (1970, 50)

    def test_out_of_range_screen_falls_back_to_first(self) -> None:
        tag = PointTag(50, 50, "x", screen=3)
        shot1 = _make_shot(scale=1.0, left=0, top=0)
        shot2 = _make_shot(scale=1.0, left=1920, top=0)
        assert map_point_to_screen(tag, [shot1, shot2]) == (50, 50)

    def test_no_screen_specified_uses_first(self) -> None:
        tag = PointTag(50, 50, "x", screen=None)
        shot1 = _make_shot(scale=1.0, left=0, top=0)
        shot2 = _make_shot(scale=1.0, left=1920, top=0)
        assert map_point_to_screen(tag, [shot1, shot2]) == (50, 50)

    def test_empty_screenshot_list_returns_none(self) -> None:
        tag = PointTag(50, 50, "x")
        assert map_point_to_screen(tag, []) is None
