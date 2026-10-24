import tomllib
from pathlib import Path

import pytest

from curio.config import Config, ConfigError
from curio.pet_config import PetSettings, save_pet_selection


def test_defaults_and_independent_profiles():
    assert PetSettings().profile_name == "playful"
    assert PetSettings(species="cat").profile_name == "reserved"
    assert PetSettings(species="cat", profile="energetic").profile_name == "energetic"


@pytest.mark.parametrize(
    "data",
    [
        {"species": "dog"},
        {"profile": "wild"},
        {"reduced_motion": "false"},
        {"jump_speed": 0},
        {"jump_frequency": -1},
        {"jump_height": float("nan")},
        {"jump_height": float("inf")},
        {"sleep_after_seconds": 0},
        {"jump_speed": True},
        {"playful_idle": 1},
        {"species": []},
    ],
)
def test_invalid_settings(data):
    with pytest.raises(ValueError):
        PetSettings.from_dict(data)


def test_config_reads_pet_and_wraps_validation(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('backend = "local"\n[pet]\nspecies = "ferret"\n')
    assert Config.from_path(path).pet.species == "ferret"
    path.write_text('backend = "local"\n[pet]\njump_speed = 0\n')
    with pytest.raises(ConfigError, match="jump_speed"):
        Config.from_path(path)


def test_save_preserves_unrelated_content_and_inline_comment(tmp_path: Path):
    path = tmp_path / "config.toml"
    original = (
        '# config\nbackend = "local"\n[pet]\n'
        'species = "fox" # my pet\nprofile = "relaxed"\n'
        '[local]\nllm_api_key = "private"\n'
    )
    path.write_text(original)
    save_pet_selection(path, "red-panda")
    assert path.read_text() == original.replace('species = "fox"', 'species = "red-panda"')
    assert tomllib.loads(path.read_text())["pet"]["species"] == "red-panda"


@pytest.mark.parametrize(
    "original",
    [
        'backend = "local"',
        'backend = "local"\n[pet]\nprofile = "auto"\n',
        'backend = "local"\n[pet] # pets\nprofile = "auto"\n[local]\n',
    ],
)
def test_save_adds_only_missing_selection(tmp_path: Path, original: str):
    path = tmp_path / "config.toml"
    path.write_text(original)
    save_pet_selection(path, "cat")
    assert tomllib.loads(path.read_text())["pet"]["species"] == "cat"
    save_pet_selection(path, "ferret")
    assert path.read_text().count("species =") == 1
    assert tomllib.loads(path.read_text())["pet"]["species"] == "ferret"


def test_invalid_selection_never_changes_file(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('backend = "local"\n')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_pet_selection(path, 'cat"\nmalicious = true')
    assert path.read_bytes() == before


def test_preserves_windows_line_endings(tmp_path: Path):
    path = tmp_path / "config.toml"
    original = b'backend = "local"\r\n[pet]\r\nprofile = "auto"\r\n'
    path.write_bytes(original)
    save_pet_selection(path, "cat")
    updated = path.read_bytes()
    assert updated.replace(b"\r\n", b"").find(b"\n") == -1
    assert tomllib.loads(updated.decode())["pet"]["species"] == "cat"


def test_inline_table_is_rejected_without_modification(tmp_path: Path):
    path = tmp_path / "config.toml"
    original = b'backend = "local"\npet = {species = "fox"}\n'
    path.write_bytes(original)
    with pytest.raises(ValueError, match="inline"):
        save_pet_selection(path, "cat")
    assert path.read_bytes() == original


def test_sleep_default_is_short_enough_to_notice_but_explicit_value_survives():
    assert PetSettings().sleep_after_seconds == 45
    assert PetSettings.from_dict({"sleep_after_seconds": 120}).sleep_after_seconds == 120
