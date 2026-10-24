"""Parse and safely persist the shared [memory] configuration table."""

import json
import re
import tomllib
from pathlib import Path

from curio.memory_contract import AutomaticLearningPolicy, MemorySettings, StorageMode


def parse_memory_settings(data: object) -> MemorySettings:
    if not isinstance(data, dict):
        raise ValueError("memory must be a table")
    enabled = data.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("memory.enabled must be boolean")
    days = data.get("default_expiration_days")
    if days is not None and (type(days) is not int or days <= 0):
        raise ValueError("memory.default_expiration_days must be a positive integer")
    path = data.get("storage_path")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        raise ValueError("memory.storage_path must be nonempty text")
    return MemorySettings(
        enabled=enabled,
        storage_mode=StorageMode(data.get("storage_mode", "local")),
        storage_path=Path(path) if path is not None else None,
        automatic_learning=AutomaticLearningPolicy(data.get("automatic_learning", "off")),
        default_expiration_days=days,
    )


def save_memory_settings(path: Path, settings: MemorySettings) -> None:
    text = path.read_text(encoding="utf-8")
    original = tomllib.loads(text)
    values = dict(original.get("memory", {}))
    values.update(
        enabled=settings.enabled,
        storage_mode=settings.storage_mode.value,
        automatic_learning=settings.automatic_learning.value,
    )
    for name, value in (
        ("storage_path", settings.storage_path),
        ("default_expiration_days", settings.default_expiration_days),
    ):
        values.pop(name, None)
        if value is not None:
            values[name] = str(value) if name == "storage_path" else value
    parse_memory_settings(values)
    lines = ["[memory]"]
    for key, value in values.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise ValueError("Unsupported memory configuration key")
        lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    section = re.search(r"(?m)^\s*\[memory\][ \t]*(?:#[^\n]*)?$", text)
    if section:
        following = re.search(r"(?m)^[ \t]*\[", text[section.end() :])
        end = section.end() + following.start() if following else len(text)
        updated = text[: section.start()] + "\n".join(lines) + "\n\n" + text[end:]
    elif "memory" not in original:
        updated = text.rstrip() + "\n\n" + "\n".join(lines) + "\n"
    else:
        raise ValueError("Use a [memory] table instead of inline memory settings")
    if tomllib.loads(updated) != dict(original, memory=values):
        raise ValueError("Cannot safely update memory configuration")
    temporary = path.with_name(path.name + ".memory.tmp")
    try:
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
