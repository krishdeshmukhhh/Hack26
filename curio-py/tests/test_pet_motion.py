import math

import pytest

from curio.pet_motion import PursuitMotion

BOUNDS = (-500, -300, 1000, 800)


def test_waits_then_moves_without_cursor_restarting_delay():
    motion = PursuitMotion()
    for i in range(4):
        assert motion.update(0.1, (200 + i * 20, 0), BOUNDS) == (0, 0)
        assert not motion.moving
    position = motion.update(0.1, (400, 0), BOUNDS)
    assert 0 < position[0] <= 18
    assert motion.moving


def test_destination_changes_immediately_during_pursuit():
    motion = PursuitMotion()
    motion.update(0.6, (300, 0), BOUNDS)
    old_x = motion.position[0]
    motion.update(0.1, (-300, 0), BOUNDS)
    assert motion.position[0] < old_x
    assert motion.moving


def test_speed_is_bounded_and_arrival_stops():
    motion = PursuitMotion()
    previous = motion.position
    for _ in range(100):
        position = motion.update(0.05, (220, 0), BOUNDS)
        assert math.dist(previous, position) <= 180 * 0.05 + 1e-8
        previous = position
    assert math.dist(motion.position, (220, 0)) <= 16 + 1e-8
    assert not motion.moving


def test_arrival_hysteresis_prevents_tiny_cursor_movements_dragging_pet():
    motion = PursuitMotion()
    for _ in range(100):
        motion.update(0.05, (220, 0), BOUNDS)
    old = motion.position
    for _ in range(20):
        motion.update(0.1, (225, 0), BOUNDS)
    assert motion.position == old
    motion.update(0.6, (300, 0), BOUNDS)
    assert motion.position[0] > old[0]


def test_point_bypasses_delay_but_keeps_speed_limit():
    motion = PursuitMotion()
    motion.update(0.1, (100, 0), BOUNDS, immediate=True, arrival_radius=1)
    assert 0 < motion.position[0] <= 18
    for _ in range(100):
        motion.update(0.05, (100, 0), BOUNDS, immediate=True, arrival_radius=1)
    assert math.dist(motion.position, (100, 0)) <= 1 + 1e-8


def test_reduced_motion_places_directly_and_clamps_negative_bounds():
    motion = PursuitMotion()
    assert motion.update(0.01, (-900, -500), BOUNDS, reduced=True) == (-500, -300)
    assert not motion.moving


def test_monitor_transfer_never_interpolates_across_gap():
    motion = PursuitMotion()
    motion.position = (-200, 0)
    assert motion.update(0.01, (1400, 200), (1100, 0, 1900, 800)) == (1400, 200)
    assert not motion.moving


def test_returning_to_pet_during_delay_cancels_chase():
    motion = PursuitMotion()
    motion.update(0.3, (200, 0), BOUNDS)
    motion.update(0.2, (5, 0), BOUNDS)
    assert motion.position == (0, 0)
    assert not motion.moving
    assert motion.update(0.2, (200, 0), BOUNDS) == (0, 0)


@pytest.mark.parametrize("dt", [0, -0.1])
def test_nonpositive_elapsed_time_does_not_move(dt):
    motion = PursuitMotion()
    assert motion.update(dt, (300, 0), BOUNDS, immediate=True) == (0, 0)


def test_distant_target_accelerates_and_slows_near_arrival():
    motion = PursuitMotion()
    bounds = (0, 0, 4000, 1000)
    steps = []
    for _ in range(15):
        before = motion.position
        motion.update(0.1, (2000, 0), bounds, delay=0)
        steps.append(math.dist(before, motion.position))
    assert steps[5] > steps[0]
    assert max(steps) > 180 * 0.1 * 2
    assert max(steps) <= 180 * 10 * 0.1 + 1e-8
    for _ in range(100):
        motion.update(0.1, (2000, 0), bounds)
    assert 0 <= 2000 - motion.position[0] <= 16.000001
    assert not motion.moving


def test_acceleration_never_overshoots_when_cursor_returns():
    motion = PursuitMotion()
    for _ in range(15):
        motion.update(0.1, (3000, 0), (0, 0, 4000, 1000), delay=0)
    target = (motion.position[0] + 25, 0)
    motion.update(0.1, target, (0, 0, 4000, 1000))
    assert motion.position[0] <= target[0]


@pytest.mark.parametrize("distance", [500, 2000, 8000, 20000])
@pytest.mark.parametrize("speed", [135, 155, 190, 230])
def test_pursuit_arrives_within_five_seconds(distance, speed):
    motion = PursuitMotion()
    for _ in range(150):
        motion.update(1 / 30, (distance, 0), (0, 0, 25000, 1000), speed=speed, delay=0.65)
    assert math.dist(motion.position, (distance, 0)) <= 16.000001
    assert not motion.moving
