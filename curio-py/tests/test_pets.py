import random
from types import SimpleNamespace

import pytest

from curio.pets import BehaviorController, SpriteCatalog, SpritePlayer


def settings(**kw):
    d = dict(
        species="fox",
        profile="playful",
        reduced_motion=False,
        playful_idle=True,
        jump_frequency=1.0,
        jump_height=0.0,
        jump_speed=1.0,
        sleep_after_seconds=120.0,
    )
    d.update(kw)
    return SimpleNamespace(**d)


@pytest.mark.parametrize("species", ["fox", "cat", "red_panda", "ferret"])
def test_catalog(species):
    from PIL import Image

    cat = SpriteCatalog(species)
    im = Image.open(cat.sheet_path)
    for clip in cat.clips.values():
        assert len(clip.frames) == len(clip.durations)
        assert all(t > 0 for t in clip.durations)
        for r, c in clip.frames:
            assert 0 <= r < im.height // 32 and 0 <= c < im.width // 32
            assert im.crop((c * 32, r * 32, (c + 1) * 32, (r + 1) * 32)).getchannel("A").getbbox()


def test_player():
    p = SpritePlayer(SpriteCatalog("fox").clips)
    p.set_action("jump")
    assert p.advance(0.089) == (3, 0)
    assert p.advance(0.002) == (3, 1)
    assert p.advance(20) == (3, 10)
    assert p.completed
    assert p.advance(1) == (3, 10)
    p.set_action("missing")
    assert p.action == "idle"


def test_latest_destination_during_jump():
    p = BehaviorController(settings(), random.Random(2))
    p.position = (100.0, 100.0)
    p.update(p.profile.follow_delay + 0.01, (240.0, 100.0), (0, 0, 500, 500))
    p._start_optional("jump")
    p.update(0.033, (240.0, 100.0), (0, 0, 500, 500))
    x = p.position[0]
    assert x > 100 and p.action == "jump"
    p.update(0.033, (0.0, 100.0), (0, 0, 500, 500))
    assert p.position[0] < x and p.vertical_offset == 0
    p.update(1, p.position, (0, 0, 500, 500))
    assert p.action != "jump" and p._cooldown > 0


def test_interactions():
    p = BehaviorController(settings())
    p._start_optional("jump")

    def tick():
        p.update(0.01, (0, 0), (0, 0, 500, 500))

    p.set_state("listening")
    tick()
    assert p.action == "attentive"
    p.set_state("responding")
    tick()
    assert p.action == "thinking"
    p.text_started()
    tick()
    assert p.action == "responding"
    p.set_speaking(True)
    tick()
    assert p.action == "speaking"
    p.set_speaking(False)
    tick()
    assert p.action == "responding"
    p.react("security")
    tick()
    assert p.action == "reaction"
    p.update(1, (0, 0), (0, 0, 500, 500))
    assert p.action == "responding"


def test_point_and_cancel():
    p = BehaviorController(settings(reduced_motion=True))
    p.set_speaking(True)
    p.point_to((100.0, 100.0))
    assert p.update(0.02, (300.0, 300.0), (0, 0, 500, 500)) == (100.0, 100.0)
    p.update(0.9, (300.0, 300.0), (0, 0, 500, 500))
    p.update(0.02, (300.0, 300.0), (0, 0, 500, 500))
    assert not p.point_active and p.position == (300.0, 300.0)
    p.point_to((100, 100))
    p.cancel()
    assert not p.point_active


def test_sleep_reduced_motion_and_bounds():
    p = BehaviorController(settings(reduced_motion=True, sleep_after_seconds=1))
    p.update(2, (0, 0), (-100, -100, 500, 500))
    assert p.action == "sleep"
    p.update(0.1, (100, 0), (-100, -100, 500, 500))
    assert p.action not in {"sleep", "jump"}
    assert p.update(1, (-500, 900), (-100, -80, 400, 300)) == (-100, 300)


def test_profiles_independent_of_species():
    a = BehaviorController(settings(species="fox", profile="reserved"))
    b = BehaviorController(settings(species="cat", profile="reserved"))
    assert a.profile == b.profile


def test_auto_profiles_follow_species_defaults():
    from curio.pet_config import PetSettings

    a = BehaviorController(PetSettings(species="fox"))
    b = BehaviorController(PetSettings(species="cat"))
    assert a.profile.hop_probability > b.profile.hop_probability


def test_missing_optional_clips_are_safe_and_no_catalog_load_needed():
    from curio.pets import Clip

    p = BehaviorController(settings(species="missing"), clips={"idle": Clip(((0, 0),), (0.1,))})
    p._start_optional("jump")
    p.update(50, (0, 0), (0, 0, 500, 500))
    assert p.action == "idle"
    p.set_state("listening")
    p.update(0.1, (0, 0), (0, 0, 500, 500))
    assert p.action == "idle"


@pytest.mark.parametrize("action", ["attentive", "alternative"])
def test_idle_gestures_yield_to_cursor_movement(action):
    pet = BehaviorController(settings(species="cat", jump_frequency=0))
    pet.update(0.01, (0, 0), (0, 0, 500, 500))
    pet._start_optional(action)
    pet.update(0.03, (100, 0), (0, 0, 500, 500))
    pet.update(pet.profile.follow_delay + 0.01, (100, 0), (0, 0, 500, 500))
    assert pet._optional is None
    assert pet.action == "walk"


@pytest.mark.parametrize("action", ["jump", "wake"])
def test_moving_does_not_cancel_jump_or_wake(action):
    pet = BehaviorController(settings(jump_frequency=0))
    pet.update(0.01, (0, 0), (0, 0, 500, 500))
    pet._start_optional(action)
    pet.update(0.03, (40, 0), (0, 0, 500, 500))
    assert pet.action == action


def test_idle_schedule_does_not_wake_sleeping_pet():
    pet = BehaviorController(settings(sleep_after_seconds=10), random.Random(4))
    pet.update(11, (0, 0), (0, 0, 500, 500))
    pet.update(1, (0, 0), (0, 0, 500, 500))
    assert pet.action == "sleep"
    for _ in range(200):
        pet.update(1, (0, 0), (0, 0, 500, 500))
        assert pet.action == "sleep"


def test_new_idle_session_resamples_without_old_elapsed_time():
    pet = BehaviorController(settings(), random.Random(4))
    pet.update(0.01, (0, 0), (0, 0, 500, 500))
    pet._idle_time = 90
    pet._next_idle = 120
    pet.update(0.03, (40, 0), (0, 0, 500, 500))
    assert pet._idle_time == 0
    low, high = pet.profile.idle_interval
    assert low <= pet._next_idle <= high
    pet._start_optional("attentive")
    pet.update(1, pet.position, (0, 0, 500, 500))
    assert low <= pet._next_idle <= high


def test_slow_cursor_movement_counts_as_activity():
    pet = BehaviorController(settings(sleep_after_seconds=10))
    for i in range(200):
        pet.update(0.1, (i, 0), (0, 0, 500, 500))
    assert pet._idle_time < 1
    assert pet.action != "sleep"


def test_lingers_then_visibly_walks_to_latest_cursor():
    pet = BehaviorController(settings(jump_frequency=0))
    bounds = (0, 0, 1000, 1000)
    pet.update(0.1, (200, 0), bounds)
    assert pet.position == (0, 0)
    assert pet.action == "idle"
    pet.update(0.2, (240, 0), bounds)
    assert pet.position == (0, 0)
    pet.update(0.2, (300, 0), bounds)
    assert 0 < pet.position[0] < 60
    assert pet.action in {"walk", "run"}
    pet.update(0.1, (0, 300), bounds)
    assert pet.position[1] > 0


def test_idle_sleep_has_settle_then_sleep_and_cursor_wakes():
    pet = BehaviorController(settings(sleep_after_seconds=5), random.Random(2))
    pet.update(5.1, (0, 0), (0, 0, 500, 500))
    assert pet.action == "settle"
    pet.update(1, (0, 0), (0, 0, 500, 500))
    assert pet.action == "sleep"
    pet.update(0.03, (100, 0), (0, 0, 500, 500))
    assert pet.action == "wake"


def test_pointing_ignores_follow_delay():
    pet = BehaviorController(settings(jump_frequency=0))
    pet.point_to((300, 0))
    pet.update(0.1, (0, 0), (0, 0, 500, 500))
    assert pet.position[0] > 0
    assert pet.action in {"walk", "run"}


def test_interaction_never_starts_random_jumps():
    pet = BehaviorController(settings(jump_frequency=5), random.Random(2))
    pet.set_state("processing")
    for i in range(100):
        pet.update(0.1, (250 + i, 0), (0, 0, 1000, 1000))
        assert pet.action != "jump"


def test_hop_waits_for_pursuit_and_does_not_change_destination_tracking():
    hopping = BehaviorController(settings(jump_frequency=5), random.Random(1))
    walking = BehaviorController(settings(jump_frequency=0), random.Random(1))
    bounds = (0, 0, 1000, 1000)
    for pet in (hopping, walking):
        pet.update(0.1, (250, 0), bounds)
        assert pet.position == (0, 0)
        assert pet.action == "idle"
        pet.update(0.4, (300, 0), bounds)
    assert hopping.action == "jump"
    assert walking.action in {"walk", "run"}
    assert hopping.position == walking.position
    for target in ((100, 200), (200, 300), (400, 100)):
        hopping.update(0.1, target, bounds)
        walking.update(0.1, target, bounds)
        assert hopping.position == walking.position
    hopping.update(1, hopping.position, bounds)
    assert hopping._cooldown > 0
    assert hopping.action != "jump"


def test_long_pursuit_can_play_actual_fox_jump_clip():
    pet = BehaviorController(settings(jump_frequency=5), random.Random(2))
    pet.update(0.1, (2000, 0), (0, 0, 3000, 1000))
    pet.update(0.4, (2000, 0), (0, 0, 3000, 1000))
    assert pet.action == "jump"
    assert pet.clips["jump"].frames == tuple((3, c) for c in range(11))
    assert pet.vertical_offset == 0


def test_long_chase_retries_missed_hop_and_respects_cooldown():
    rolls = iter((0.99, 0.0))
    rng = SimpleNamespace(
        uniform=lambda low, high: low,
        random=lambda: next(rolls),
        choices=lambda actions, **kwargs: [actions[0]],
    )
    pet = BehaviorController(settings(playful_idle=False), rng)
    bounds = (0, 0, 4000, 1000)
    pet.update(0.1, (3000, 0), bounds)
    pet.update(0.4, (3000, 0), bounds)
    assert pet.action != "jump"  # First opportunity missed.
    for _ in range(15):
        pet.update(0.1, (3000, 0), bounds)
        if pet.action == "jump":
            break
    assert pet.action == "jump"
    pet.update(1, (3000, 0), bounds)
    assert pet._cooldown > 0
    for _ in range(10):
        pet.update(0.1, (3000, 0), bounds)
        assert pet.action != "jump"


@pytest.mark.parametrize("species", ["fox", "cat", "red-panda", "ferret"])
def test_every_pet_hops_once_on_arrival(species):
    from curio.pet_config import PetSettings

    pet = BehaviorController(PetSettings(species=species, playful_idle=False), random.Random(2))
    pet._cooldown = 100  # No traversal hop: arrival is its own reaction.
    saw_movement = False
    for _ in range(170):
        pet.update(1 / 30, (700, 0), (0, 0, 3000, 1000))
        saw_movement |= pet._motion.moving
        if saw_movement and not pet._motion.moving:
            break
    assert saw_movement
    assert pet.action == "jump"
    assert "jump" in pet.clips
    for _ in range(100):
        pet.update(1 / 30, (700, 0), (0, 0, 3000, 1000))
    assert pet.action == "idle"


@pytest.mark.parametrize("species,row", [("fox", 3), ("cat", 8), ("red-panda", 3), ("ferret", 5)])
def test_every_pet_uses_its_own_traversal_jump(species, row):
    from curio.pet_config import PetSettings

    pet = BehaviorController(PetSettings(species=species, jump_frequency=5), random.Random(2))
    pet.update(0.1, (1500, 0), (0, 0, 3000, 1000))
    pet.update(0.7, (1500, 0), (0, 0, 3000, 1000))
    assert pet.action == "jump"
    assert all(r == row for r, _ in pet.clips["jump"].frames)


@pytest.mark.parametrize("mode", ["disabled", "reduced", "processing", "pointing"])
def test_arrival_hop_respects_interaction_and_motion_preferences(mode):
    from curio.pet_config import PetSettings

    pet = BehaviorController(
        PetSettings(
            playful_idle=False,
            jump_frequency=0 if mode == "disabled" else 1,
            reduced_motion=mode == "reduced",
        ),
        random.Random(2),
    )
    pet._cooldown = 100
    if mode == "processing":
        pet.set_state("processing")
    if mode == "pointing":
        pet.point_to((700, 0))
    for _ in range(150):
        pet.update(1 / 30, (700, 0), (0, 0, 3000, 1000))
        assert pet.action != "jump"
