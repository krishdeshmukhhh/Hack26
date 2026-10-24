from pathlib import Path

import pytest

from curio.config import PLACEHOLDER_WORKER_URL, Config, ConfigError


def test_load_valid_config(tmp_path: Path) -> None:
    toml_text = """
    worker_url = "https://my-worker.example.workers.dev"
    hotkey = "ctrl+alt"
    default_model = "claude-sonnet-4-6"
    log_level = "INFO"
    """
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml_text)
    cfg = Config.from_path(config_path)
    assert cfg.worker_url == "https://my-worker.example.workers.dev"
    assert cfg.hotkey == "ctrl+alt"
    assert cfg.default_model == "claude-sonnet-4-6"
    assert cfg.log_level == "INFO"


def test_load_rejects_placeholder_worker_url(tmp_path: Path) -> None:
    toml_text = f"""
    worker_url = "{PLACEHOLDER_WORKER_URL}"
    hotkey = "ctrl+alt"
    default_model = "claude-sonnet-4-6"
    log_level = "INFO"
    """
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml_text)
    with pytest.raises(ConfigError, match="worker_url"):
        Config.from_path(config_path)


def test_load_rejects_invalid_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("this is not valid toml {{{")
    with pytest.raises(ConfigError, match="parse"):
        Config.from_path(config_path)


def test_load_rejects_missing_required_field(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('hotkey = "ctrl+alt"\n')  # missing worker_url
    with pytest.raises(ConfigError, match="worker_url"):
        Config.from_path(config_path)


def test_load_rejects_invalid_hotkey(tmp_path: Path) -> None:
    toml_text = """
    worker_url = "https://my-worker.example.workers.dev"
    hotkey = "banana"
    default_model = "claude-sonnet-4-6"
    log_level = "INFO"
    """
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml_text)
    with pytest.raises(ConfigError, match="hotkey"):
        Config.from_path(config_path)


def test_load_rejects_invalid_model(tmp_path: Path) -> None:
    toml_text = """
    worker_url = "https://my-worker.example.workers.dev"
    hotkey = "ctrl+alt"
    default_model = "gpt-4"
    log_level = "INFO"
    """
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml_text)
    with pytest.raises(ConfigError, match="default_model"):
        Config.from_path(config_path)


def test_ensure_exists_creates_from_example(tmp_path: Path) -> None:
    example_path = tmp_path / "config.example.toml"
    example_path.write_text('worker_url = "placeholder"\n')
    target_path = tmp_path / "nested" / "config.toml"
    Config.ensure_exists(target_path, example_path)
    assert target_path.exists()
    assert target_path.read_text() == example_path.read_text()


def test_ensure_exists_noop_when_already_present(tmp_path: Path) -> None:
    example_path = tmp_path / "config.example.toml"
    example_path.write_text('worker_url = "placeholder"\n')
    target_path = tmp_path / "config.toml"
    target_path.write_text('worker_url = "real"\n')
    Config.ensure_exists(target_path, example_path)
    assert target_path.read_text() == 'worker_url = "real"\n'
