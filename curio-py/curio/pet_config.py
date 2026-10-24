"""Validated pet preferences and targeted config-file persistence."""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

SPECIES = {"fox": "Fox", "cat": "Cat", "red-panda": "Red Panda", "ferret": "Ferret"}
DEFAULT_PROFILES = {
    "fox": "playful",
    "cat": "reserved",
    "red-panda": "relaxed",
    "ferret": "energetic",
}
PROFILES = {"auto", "playful", "reserved", "relaxed", "energetic"}


@dataclass(frozen=True)
class PetSettings:
    species: str = "fox"
    profile: str = "auto"
    reduced_motion: bool = False
    playful_idle: bool = True
    jump_frequency: float = 1.0
    jump_height: float = 0.0
    jump_speed: float = 1.0
    sleep_after_seconds: float = 45.0

    @property
    def profile_name(self) -> str:
        return DEFAULT_PROFILES[self.species] if self.profile == "auto" else self.profile

    @classmethod
    def from_dict(cls, data: object) -> PetSettings:
        if not isinstance(data, dict):
            raise ValueError("[pet] must be a table")
        defaults = cls()
        values = {}
        for key, allowed in (("species", SPECIES), ("profile", PROFILES)):
            value = data.get(key, getattr(defaults, key))
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f"pet.{key} must be one of {sorted(allowed)}")
            values[key] = value
        for key in ("reduced_motion", "playful_idle"):
            value = data.get(key, getattr(defaults, key))
            if not isinstance(value, bool):
                raise ValueError(f"pet.{key} must be a boolean")
            values[key] = value
        limits = {
            "jump_frequency": (0, 5),
            "jump_height": (0, 64),
            "jump_speed": (0.25, 4),
            "sleep_after_seconds": (10, 3600),
        }
        for key, (low, high) in limits.items():
            value = data.get(key, getattr(defaults, key))
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError(f"pet.{key} must be a finite number between {low} and {high}")
            values[key] = float(value)
        return cls(**values)


def save_pet_selection(path: Path, species: str) -> None:
    """Change only the species entry, retaining comments and unrelated settings.

    Parse before and after editing so unsupported TOML layouts fail without
    overwriting the user's file. Write via a same-directory temporary replacement.
    """
    if species not in SPECIES:
        raise ValueError(f"unknown pet species: {species}")
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    data = tomllib.loads(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    section = re.search(r"(?m)^[ \t]*\[pet\][ \t]*(?:#[^\r\n]*)?(?=\r?$)", text)
    if section:
        following = re.search(r"(?m)^[ \t]*\[", text[section.end() :])
        end = section.end() + following.start() if following else len(text)
        body = text[section.end() : end]
        entry = re.search(
            r"""(?m)^([ \t]*species[ \t]*=[ \t]*)(?:"[^"\r\n]*"|'[^'\r\n]*')""",
            body,
        )
        if entry:
            body = body[: entry.start()] + entry.group(1) + f'"{species}"' + body[entry.end() :]
        else:
            body = newline + f'species = "{species}"' + body
        updated = text[: section.end()] + body + text[end:]
    elif "pet" not in data:
        updated = text + ("" if text.endswith("\n") else newline)
        updated += newline + "[pet]" + newline + f'species = "{species}"' + newline
    else:
        raise ValueError(
            "Pet selection requires a [pet] table; edit Settings to change inline tables"
        )
    parsed = tomllib.loads(updated)
    expected = dict(data)
    expected["pet"] = dict(data.get("pet", {}), species=species)
    if parsed != expected:
        raise ValueError("Cannot safely update pet selection in this configuration layout")
    temporary = path.with_name(path.name + ".pet.tmp")
    try:
        temporary.write_bytes(updated.encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
