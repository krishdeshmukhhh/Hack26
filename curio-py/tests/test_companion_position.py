import pytest
from curio.ui.companion_position import CompanionPlacement, compute_position, should_update


SCREEN_1080P = (0, 0, 1920, 1080)
COMPANION = (80, 40)


class TestComputePositionNormal:
    def test_below_right(self):
        p = compute_position(500, 500, SCREEN_1080P, COMPANION)
        assert p == CompanionPlacement(x=520, y=520, flipped_x=False, flipped_y=False)


class TestComputePositionEdgeFlip:
    def test_right_edge_flip(self):
        p = compute_position(1860, 500, SCREEN_1080P, COMPANION)
        assert p.x == 1760  # 1860 - 20 - 80
        assert p.flipped_x is True
        assert p.flipped_y is False

    def test_bottom_edge_flip(self):
        p = compute_position(500, 1020, SCREEN_1080P, COMPANION)
        assert p.y == 960  # 1020 - 20 - 40
        assert p.flipped_x is False
        assert p.flipped_y is True

    def test_corner_flip_both_axes(self):
        p = compute_position(1860, 1020, SCREEN_1080P, COMPANION)
        assert p == CompanionPlacement(x=1760, y=960, flipped_x=True, flipped_y=True)


class TestComputePositionMultiMonitor:
    def test_second_monitor(self):
        screen2 = (1920, 0, 1920, 1080)
        p = compute_position(2420, 300, screen2, COMPANION)
        assert p == CompanionPlacement(x=2440, y=320, flipped_x=False, flipped_y=False)


class TestComputePositionBoundary:
    def test_exactly_at_edge_margin_boundary(self):
        # cursor at 1840, screen_right=1920, distance=80 which equals edge_margin
        # 80 < 80 is False, so should NOT flip
        p = compute_position(1840, 500, SCREEN_1080P, COMPANION)
        assert p.flipped_x is False

    def test_one_pixel_past_boundary(self):
        # cursor at 1841, distance=79 < 80, should flip
        p = compute_position(1841, 500, SCREEN_1080P, COMPANION)
        assert p.flipped_x is True


class TestShouldUpdate:
    def test_move_greater_than_dead_zone(self):
        assert should_update(100, 100, 105, 100) is True

    def test_move_within_dead_zone(self):
        assert should_update(100, 100, 102, 101) is False

    def test_diagonal_just_outside(self):
        # distance = sqrt(9+9) = ~4.24 > 3
        assert should_update(100, 100, 103, 103) is True

    def test_no_movement(self):
        assert should_update(100, 100, 100, 100) is False

    def test_exactly_at_dead_zone(self):
        # distance == 3, not > 3, so False
        assert should_update(100, 100, 103, 100) is False
