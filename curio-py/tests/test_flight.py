"""Tests for the companion's flight geometry."""

import math

import pytest

from curio.ui.flight import (
    REST_ROTATION_DEGREES,
    arc_control_point,
    flight_duration_seconds,
    flight_frame,
    follow_center,
    landing_point,
)

SCREEN = (0, 0, 1920, 1200)


def test_duration_scales_with_distance_and_is_clamped() -> None:
    assert flight_duration_seconds((0, 0), (10, 0)) == 0.6
    assert flight_duration_seconds((0, 0), (800, 0)) == 1.0
    assert flight_duration_seconds((0, 0), (5000, 0)) == 1.4


def test_arc_bows_upward_and_is_capped() -> None:
    assert arc_control_point((0, 100), (200, 100)) == (100, 60)  # 20% of 200
    assert arc_control_point((0, 500), (1600, 500)) == (800, 420)  # capped at 80


def test_flight_starts_and_ends_exactly() -> None:
    start, end = (100.0, 900.0), (1500.0, 200.0)
    (x0, y0), _, s0 = flight_frame(start, end, 0.0)
    (x1, y1), _, s1 = flight_frame(start, end, 1.0)
    assert (x0, y0) == pytest.approx(start)
    assert (x1, y1) == pytest.approx(end)
    assert s0 == pytest.approx(1.0) and s1 == pytest.approx(1.0)


def test_flight_swells_at_midpoint_and_rises_above_straight_line() -> None:
    start, end = (0.0, 500.0), (1000.0, 500.0)
    (x, y), rotation, scale = flight_frame(start, end, 0.5)
    assert scale == pytest.approx(1.3)
    assert y < 500  # arc goes up
    assert rotation == pytest.approx(90.0)  # flying right at the apex


def test_rotation_faces_travel_direction() -> None:
    # Heading down-left near the end: tip (up at 0°) turned past 180°.
    _, rotation, _ = flight_frame((500.0, 0.0), (0.0, 500.0), 0.9)
    assert 180 < rotation < 270


def test_zero_length_flight_keeps_rest_rotation() -> None:
    _, rotation, _ = flight_frame((10.0, 10.0), (10.0, 10.0), 0.5)
    assert rotation == REST_ROTATION_DEGREES


def test_follow_center_offsets_and_flips_at_edges() -> None:
    assert follow_center((500, 500), SCREEN) == (535, 525)
    assert follow_center((1910, 500), SCREEN) == (1875, 525)
    assert follow_center((500, 1195), SCREEN) == (535, 1170)


def test_landing_point_offsets_and_clamps() -> None:
    assert landing_point((700, 400), SCREEN) == (708, 412)
    assert landing_point((1915, 1195), SCREEN) == (1900, 1180)
    assert landing_point((-50, 5), SCREEN) == (20, 20)


def test_frames_move_monotonically_toward_target() -> None:
    start, end = (0.0, 0.0), (1000.0, 0.0)
    xs = [flight_frame(start, end, i / 20)[0][0] for i in range(21)]
    assert all(b >= a for a, b in zip(xs, xs[1:], strict=False))
    assert math.isclose(xs[-1], 1000.0)
