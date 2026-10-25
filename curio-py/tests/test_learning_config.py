import tomllib
from pathlib import Path

import pytest

from curio.config import Config, ConfigError, LearningSettings, save_share_walkthroughs

BASE = 'worker_url = "https://my-worker.example.workers.dev"\n'


def _load(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(BASE + text)
    return Config.from_path(path)


def test_learning_defaults(tmp_path: Path) -> None:
    assert _load(tmp_path, "").learning == LearningSettings(
        enabled=True, share_walkthroughs=False, sync_url=""
    )


def test_learning_section(tmp_path: Path) -> None:
    cfg = _load(tmp_path, (
        "[learning]\nenabled = false\nshare_walkthroughs = true\n"
        'sync_url = " https://map.example.com/ "\n'
    ))
    assert cfg.learning == LearningSettings(
        enabled=False, share_walkthroughs=True, sync_url="https://map.example.com"
    )


@pytest.mark.parametrize("body, match", [
    ("enabled = 1", "learning.enabled"),
    ('share_walkthroughs = "yes"', "learning.share_walkthroughs"),
    ("sync_url = 5", "learning.sync_url"),
    ('sync_url = "ftp://map"', "http"),
])
def test_learning_validation(tmp_path: Path, body: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, f"[learning]\n{body}\n")


def test_example_config_documents_learning() -> None:
    example = Path(__file__).resolve().parent.parent / "config.example.toml"
    text = example.read_text(encoding="utf-8")
    # The example has a placeholder worker URL, so parse just the table.
    assert LearningSettings.from_dict(tomllib.loads(text)["learning"]) == LearningSettings()


def test_save_share_walkthroughs_edits_existing_entry(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = (
        BASE + "\n[learning]  # walkthrough learning\nenabled = true\n"
        "share_walkthroughs = false   # tray toggle\n\n[pet]\nspecies = \"cat\"\n"
    )
    path.write_text(original)
    save_share_walkthroughs(path, True)
    text = path.read_text()
    assert text == original.replace("share_walkthroughs = false", "share_walkthroughs = true")
    assert Config.from_path(path).learning.share_walkthroughs
    save_share_walkthroughs(path, False)
    assert path.read_text() == original


def test_save_share_walkthroughs_adds_entry_or_table(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(BASE + "[learning]\nenabled = true\n")
    save_share_walkthroughs(path, True)
    assert Config.from_path(path).learning == LearningSettings(share_walkthroughs=True)

    path.write_text(BASE + '[pet]\nspecies = "cat"')
    save_share_walkthroughs(path, True)
    cfg = Config.from_path(path)
    assert cfg.learning.share_walkthroughs and cfg.pet.species == "cat"


def test_save_share_walkthroughs_refuses_inline_table(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = BASE + "learning = { enabled = true }\n"
    path.write_text(original)
    with pytest.raises(ConfigError):
        save_share_walkthroughs(path, True)
    assert path.read_text() == original
