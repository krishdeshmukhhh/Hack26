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
    pet.update(0.03, (40, 0), (0, 0, 500, 500))
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
        pet.update(.1, (i, 0), (0, 0, 500, 500))
    assert pet._idle_time < 1
    assert pet.action != "sleep"
