"""Config loader for Curio.

Reads config.toml from the OS-appropriate per-user config directory via
platformdirs. Validates required fields and detects the unconfigured placeholder
worker URL (so the panel can surface a clear first-run warning).
"""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from curio.memory_contract import MemorySettings
from curio.memory_settings import parse_memory_settings
from curio.pet_config import PetSettings

PLACEHOLDER_WORKER_URL = "https://curio-proxy.your-subdomain.workers.dev"

# v1 supports the two listen-only-hook-friendly bindings. caps_lock is
# deferred to v2 because it requires a suppressing hook to swallow the
# lock-toggle side effect, which contradicts our "never swallow keys" rule.
ALLOWED_HOTKEYS = {"ctrl+alt", "right_ctrl"}
ALLOWED_MODELS = {"claude-sonnet-4-6", "claude-opus-4-6"}
ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
ALLOWED_BACKENDS = {"cloud", "local"}
# "pixel": POINT coords are in the screenshot's pixel space (Claude, Qwen2.5-VL).
# "norm1000": POINT coords are on a 0-1000 grid (Qwen3-VL's native grounding format).
ALLOWED_POINT_COORDS = {"pixel", "norm1000"}
ALLOWED_WHISPER_DEVICES = {"cpu", "cuda"}
ALLOWED_TTS_ENGINES = {"kokoro", "system"}


class ConfigError(Exception):
    """Raised when the config file cannot be loaded or fails validation."""


@dataclass(frozen=True)
class LocalConfig:
    """Settings for ``backend = "local"``: self-hosted LLM, Whisper STT, system TTS."""

    llm_base_url: str
    llm_model: str
    llm_api_key: str
    point_coords: str
    whisper_model: str
    whisper_device: str
    tts_engine: str
    tts_voice: str
    # Sampling temperature for the local LLM; low keeps answers/POINT tags steady.
    llm_temperature: float = 0.2

    @classmethod
    def from_dict(cls, data: object) -> LocalConfig:
        if not isinstance(data, dict):
            raise ConfigError("[local] must be a table")

        def _str(key: str, default: str) -> str:
            value = data.get(key, default)
            if not isinstance(value, str):
                raise ConfigError(f"local.{key} must be a string")
            return value

        llm_base_url = _str("llm_base_url", "http://localhost:8000/v1")
        if not llm_base_url:
            raise ConfigError("local.llm_base_url is required when backend = \"local\"")
        llm_model = _str("llm_model", "Qwen/Qwen3-VL-32B-Instruct")
        if not llm_model:
            raise ConfigError("local.llm_model is required when backend = \"local\"")

        point_coords = _str("point_coords", "norm1000")
        if point_coords not in ALLOWED_POINT_COORDS:
            raise ConfigError(
                f"local.point_coords must be one of {sorted(ALLOWED_POINT_COORDS)}, "
                f"got {point_coords!r}"
            )
        whisper_device = _str("whisper_device", "cpu")
        if whisper_device not in ALLOWED_WHISPER_DEVICES:
            raise ConfigError(
                f"local.whisper_device must be one of {sorted(ALLOWED_WHISPER_DEVICES)}, "
                f"got {whisper_device!r}"
            )

        tts_engine = _str("tts_engine", "kokoro")
        if tts_engine not in ALLOWED_TTS_ENGINES:
            raise ConfigError(
                f"local.tts_engine must be one of {sorted(ALLOWED_TTS_ENGINES)}, "
                f"got {tts_engine!r}"
            )

        llm_temperature = data.get("llm_temperature", 0.2)
        if (
            isinstance(llm_temperature, bool)
            or not isinstance(llm_temperature, (int, float))
            or not 0.0 <= llm_temperature <= 2.0
        ):
            raise ConfigError(
                f"local.llm_temperature must be a number between 0 and 2, got {llm_temperature!r}"
            )

        return cls(
            llm_base_url=llm_base_url,
            llm_model=llm_model,
            llm_api_key=_str("llm_api_key", ""),
            point_coords=point_coords,
            whisper_model=_str("whisper_model", "base.en"),
            whisper_device=whisper_device,
            tts_engine=tts_engine,
            tts_voice=_str("tts_voice", ""),
            llm_temperature=float(llm_temperature),
        )


@dataclass(frozen=True)
class LearningSettings:
    """``[learning]``: walkthrough event log, task map, skill model and map sync."""

    enabled: bool = True
    # Push anonymous walkthrough summaries to the map server. Off by default.
    share_walkthroughs: bool = False
    # Map server base URL; empty disables syncing entirely.
    sync_url: str = ""

    @classmethod
    def from_dict(cls, data: object) -> LearningSettings:
        if not isinstance(data, dict):
            raise ConfigError("[learning] must be a table")
        defaults = cls()
        values: dict[str, object] = {}
        for key in ("enabled", "share_walkthroughs"):
            value = data.get(key, getattr(defaults, key))
            if not isinstance(value, bool):
                raise ConfigError(f"learning.{key} must be a boolean")
            values[key] = value
        sync_url = data.get("sync_url", defaults.sync_url)
        if not isinstance(sync_url, str):
            raise ConfigError("learning.sync_url must be a string")
        sync_url = sync_url.strip()
        if sync_url and not sync_url.startswith(("http://", "https://")):
            raise ConfigError("learning.sync_url must start with http:// or https://")
        values["sync_url"] = sync_url.rstrip("/")
        return cls(**values)


def save_share_walkthroughs(path: Path, enabled: bool) -> None:
    """Change only ``[learning] share_walkthroughs``, keeping comments and other settings.

    Same approach as ``save_pet_selection``: edit the text, check that the
    parsed result changed only that key, then replace the file atomically.
    """
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    data = tomllib.loads(text)
    value = "true" if enabled else "false"
    newline = "\r\n" if "\r\n" in text else "\n"
    section = re.search(r"(?m)^[ \t]*\[learning\][ \t]*(?:#[^\r\n]*)?(?=\r?$)", text)
    if section:
        following = re.search(r"(?m)^[ \t]*\[", text[section.end() :])
        end = section.end() + following.start() if following else len(text)
        body = text[section.end() : end]
        entry = re.search(r"(?m)^([ \t]*share_walkthroughs[ \t]*=[ \t]*)(?:true|false)", body)
        if entry:
            body = body[: entry.start()] + entry.group(1) + value + body[entry.end() :]
        else:
            body = newline + f"share_walkthroughs = {value}" + body
        updated = text[: section.end()] + body + text[end:]
    elif "learning" not in data:
        updated = text + ("" if text.endswith("\n") else newline)
        updated += newline + "[learning]" + newline + f"share_walkthroughs = {value}" + newline
    else:
        raise ConfigError(
            "Sharing toggle requires a [learning] table; edit Settings to change inline tables"
        )
    parsed = tomllib.loads(updated)
    expected = dict(data)
    expected["learning"] = dict(data.get("learning", {}), share_walkthroughs=enabled)
    if parsed != expected:
        raise ConfigError("Cannot safely update the sharing setting in this configuration layout")
    temporary = path.with_name(path.name + ".learning.tmp")
    try:
        temporary.write_bytes(updated.encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Config:
    worker_url: str
    hotkey: str
    default_model: str
    log_level: str
    knowledge_dir: Path | None
    backend: str = "cloud"
    local: LocalConfig | None = None
    pet: PetSettings = field(default_factory=PetSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    learning: LearningSettings = field(default_factory=LearningSettings)

    @property
    def point_coords(self) -> str:
        return self.local.point_coords if self.local is not None else "pixel"

    @classmethod
    def from_path(cls, path: Path) -> Config:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ConfigError(f"cannot read config file at {path}: {exc}") from exc
        try:
            data = tomllib.loads(raw.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise ConfigError(f"cannot parse TOML at {path}: {exc}") from exc

        backend = data.get("backend", "cloud")
        if backend not in ALLOWED_BACKENDS:
            raise ConfigError(
                f"backend must be one of {sorted(ALLOWED_BACKENDS)}, got {backend!r}"
            )

        # The Worker is only needed for the cloud backend.
        worker_url = data.get("worker_url", "")
        local = None
        if backend == "cloud":
            if not isinstance(worker_url, str) or not worker_url:
                raise ConfigError("worker_url is required and must be a non-empty string")
            if worker_url == PLACEHOLDER_WORKER_URL:
                raise ConfigError(
                    f"worker_url is still the placeholder value. Edit {path} and set it to "
                    "your deployed Cloudflare Worker URL, or set backend = \"local\"."
                )
        else:
            local = LocalConfig.from_dict(data.get("local", {}))

        hotkey = data.get("hotkey", "ctrl+alt")
        if hotkey not in ALLOWED_HOTKEYS:
            raise ConfigError(
                f"hotkey must be one of {sorted(ALLOWED_HOTKEYS)}, got {hotkey!r}"
            )

        default_model = data.get("default_model", "claude-sonnet-4-6")
        if local is not None:
            default_model = local.llm_model
        elif default_model not in ALLOWED_MODELS:
            raise ConfigError(
                f"default_model must be one of {sorted(ALLOWED_MODELS)}, got {default_model!r}"
            )

        log_level = data.get("log_level", "INFO")
        if log_level not in ALLOWED_LOG_LEVELS:
            raise ConfigError(
                f"log_level must be one of {sorted(ALLOWED_LOG_LEVELS)}, got {log_level!r}"
            )

        knowledge_dir_raw = data.get("knowledge_dir")
        if isinstance(knowledge_dir_raw, str) and knowledge_dir_raw.strip():
            knowledge_dir = Path(knowledge_dir_raw)
        else:
            # Default: %APPDATA%/Curio/knowledge/
            # Use the same config dir parent (path.parent = %APPDATA%/Curio/)
            knowledge_dir = path.parent / "knowledge"

        # None if directory doesn't exist — no error
        if not knowledge_dir.is_dir():
            knowledge_dir = None

        try:
            pet = PetSettings.from_dict(data.get("pet", {}))
            memory = parse_memory_settings(data.get("memory", {}))
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        learning = LearningSettings.from_dict(data.get("learning", {}))

        return cls(
            worker_url=worker_url if isinstance(worker_url, str) else "",
            hotkey=hotkey,
            default_model=default_model,
            log_level=log_level,
            knowledge_dir=knowledge_dir,
            backend=backend,
            local=local,
            pet=pet,
            memory=memory,
            learning=learning,
        )

    @staticmethod
    def ensure_exists(target_path: Path, example_path: Path) -> bool:
        """Copy example to target if target does not exist. Returns True if created."""
        if target_path.exists():
            return False
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example_path, target_path)
        return True
