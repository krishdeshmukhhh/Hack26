"""Sprite catalog, elapsed-time player and Qt-independent desktop pet behavior."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from curio.pet_motion import PursuitMotion


@dataclass(frozen=True)
class Clip:
    frames: tuple[tuple[int, int], ...]
    durations: tuple[float, ...]
    loop: bool = True
    external_arc: bool = False

    @property
    def duration(self) -> float:
        return sum(self.durations)


JUMP_DURATIONS = {
    "fox": (90, 80, 70, 70, 80, 70, 70, 80, 80, 90, 100),
    "cat": (100, 90, 100, 100, 90, 100, 120),
    "red_panda": (100, 90, 100, 90, 80, 90, 100, 110),
    "ferret": (90, 80, 90, 90, 80, 90, 100, 110),
}


class SpriteCatalog:
    """Read approved frame metadata; validate rectangles and alpha once at load."""

    def __init__(self, species: str = "fox") -> None:
        species = species.lower().replace(" ", "_").replace("-", "_")
        root = Path(__file__).parent / "assets" / "pets"
        data = json.loads((root / "clips.json").read_text(encoding="utf-8"))
        if species not in data:
            raise ValueError(f"Unknown pet: {species}")
        self.sheet_path = root / f"{species}.png"
        self.clips: dict[str, Clip] = {}
        from PIL import Image

        with Image.open(self.sheet_path) as image:
            image = image.convert("RGBA")
            for action, sequence in data[species].items():
                row, columns = sequence.split(":")
                first, last = map(int, columns.split("-"))
                step = 1 if last >= first else -1
                frames = tuple((int(row) - 1, c - 1) for c in range(first, last + step, step))
                for r, c in frames:
                    if not (0 <= c * 32 < image.width and 0 <= r * 32 < image.height):
                        raise ValueError(f"Out-of-bounds sprite: {action}")
                    tile = image.crop((c * 32, r * 32, (c + 1) * 32, (r + 1) * 32))
                    if tile.getchannel("A").getbbox() is None:
                        raise ValueError(f"Empty sprite: {action}")
                slow = action in {"idle", "thinking", "sleep"}
                durations = (
                    tuple(t / 1000 for t in JUMP_DURATIONS[species])
                    if action == "jump"
                    else (0.18 if slow else 0.1,) * len(frames)
                )
                loop = action not in {"jump", "reaction", "settle", "wake", "alternative"}
                self.clips[action] = Clip(frames, durations, loop)
        if "run" not in self.clips:
            walk = self.clips["walk"]
            self.clips["run"] = Clip(walk.frames, tuple(t * 0.7 for t in walk.durations))


class SpritePlayer:
    """Advance frames using actual elapsed time, holding one-shot landing frames."""

    def __init__(self, clips: dict[str, Clip]) -> None:
        if "idle" not in clips:
            raise ValueError("An idle clip is required")
        for clip in clips.values():
            if not clip.frames or len(clip.frames) != len(clip.durations):
                raise ValueError("Invalid sprite timing")
            if any(not math.isfinite(t) or t <= 0 for t in clip.durations):
                raise ValueError("Frame durations must be finite and positive")
        self.clips = clips
        self.action = "idle"
        self.elapsed = 0.0
        self.completed = False

    def set_action(self, name: str) -> None:
        name = name if name in self.clips else "idle"
        if name != self.action:
            self.action = name
            self.elapsed = 0.0
            self.completed = False

    def advance(self, dt: float) -> tuple[int, int]:
        clip = self.clips[self.action]
        self.elapsed += max(0.0, dt)
        self.completed = not clip.loop and self.elapsed >= clip.duration
        elapsed = self.elapsed % clip.duration if clip.loop else self.elapsed
        for frame, duration in zip(clip.frames, clip.durations, strict=True):
            if elapsed < duration:
                return frame
            elapsed -= duration
        return clip.frames[-1]


@dataclass(frozen=True)
class BehaviorProfile:
    idle_interval: tuple[float, float]
    hop_probability: float
    cooldown: float
    follow_delay: float
    move_speed: float


PROFILES = {
    "playful": BehaviorProfile((6.0, 12.0), 0.55, 4.0, 0.4, 190.0),
    "reserved": BehaviorProfile((12.0, 22.0), 0.40, 5.0, 0.6, 155.0),
    "relaxed": BehaviorProfile((9.0, 18.0), 0.45, 5.0, 0.65, 135.0),
    "energetic": BehaviorProfile((4.0, 9.0), 0.60, 3.0, 0.25, 230.0),
}


class BehaviorController:
    """Arbitrate actions without coupling cursor convergence to sprite playback.

    Bounds are legal window-origin extents (left, top, right, bottom), already
    reduced by widget size. The caller chooses a real monitor, never a union of
    screens. ``position`` may be reset when switching displays or showing.
    """

    def __init__(
        self, settings: Any, rng: random.Random | None = None, clips: dict[str, Clip] | None = None
    ) -> None:
        self.settings = settings
        self.rng = rng or random.Random()
        profile_name = getattr(settings, "profile_name", settings.profile)
        self.profile = PROFILES.get(profile_name, PROFILES["playful"])
        self.clips = SpriteCatalog(settings.species).clips if clips is None else clips
        self.position = (0.0, 0.0)
        self._motion = PursuitMotion()
        self.action = "idle"
        self.facing_left = False
        self.vertical_offset = 0.0
        self.state = "idle"
        self.speaking = False
        self.streaming = False
        self._optional: str | None = None
        self._optional_elapsed = 0.0
        self._cooldown = 0.0
        self._idle_time = 0.0
        self._stationary = 0.0
        self._next_idle = self.rng.uniform(*self.profile.idle_interval)
        self._last_optional: str | None = None
        self._last_destination: tuple[float, float] | None = None
        self._traversal_checked = False
        self._hop_distance = 0.0
        self._reaction_remaining = 0.0
        self._point: tuple[float, float] | None = None
        self._point_hold = 0.0
        self._settled = False
        self._arrival_cooldown = 0.0

    def reconfigure(self, settings: Any, clips: dict[str, Clip]) -> None:
        """Change appearance/profile without losing streaming or target lifecycle."""
        self.settings = settings
        self.clips = clips
        self.profile = PROFILES.get(settings.profile_name, PROFILES["playful"])
        self._clear_optional()
        self._next_idle = self.rng.uniform(*self.profile.idle_interval)

    @property
    def point_active(self) -> bool:
        return self._point is not None

    def _clear_optional(self) -> None:
        self._optional = None
        self._optional_elapsed = 0.0
        self.vertical_offset = 0.0

    def set_state(self, state: str) -> None:
        state = str(state)
        if state == self.state:
            return
        self.state = state
        self._idle_time = 0.0
        self._next_idle = self.rng.uniform(*self.profile.idle_interval)
        if state != "idle":
            self._clear_optional()
        if state == "listening":
            self.streaming = False
            self.speaking = False
            self._point = None
            self._reaction_remaining = 0.0
        elif state == "idle":
            self.streaming = False
            self.speaking = False

    def text_started(self) -> None:
        self.streaming = True
        self._clear_optional()

    def set_speaking(self, speaking: bool) -> None:
        self.speaking = speaking
        if speaking:
            self._clear_optional()

    def react(self, kind: str = "error") -> None:
        self._clear_optional()
        self._reaction_remaining = 0.8

    def cancel(self) -> None:
        self._clear_optional()
        self._point = None
        self._point_hold = 0.0
        self.streaming = False
        self.speaking = False
        self._reaction_remaining = 0.0
        self.set_state("idle")

    def point_to(self, target: tuple[float, float]) -> None:
        self._clear_optional()
        self._point = target
        self._point_hold = 0.0

    def _start_optional(self, action: str) -> None:
        if action not in self.clips:
            return
        self._optional = action
        self._optional_elapsed = 0.0
        self._last_optional = action
        self.action = action

    def update(
        self, dt: float, destination: tuple[float, float], bounds: tuple[float, float, float, float]
    ) -> tuple[float, float]:
        dt = max(0.0, dt)
        reduced = self.settings.reduced_motion
        self._cooldown = max(0.0, self._cooldown - dt)
        self._arrival_cooldown = max(0.0, self._arrival_cooldown - dt)
        self._reaction_remaining = max(0.0, self._reaction_remaining - dt)
        cursor_changed = (
            self._last_destination is not None
            and math.dist(destination, self._last_destination) > 0.01
        )
        self._last_destination = destination
        was_asleep = self.action in {"sleep", "settle"}
        active = self.state != "idle" or self.speaking or self.point_active
        if cursor_changed or active:
            if cursor_changed or self._idle_time > 0:
                self._next_idle = self.rng.uniform(*self.profile.idle_interval)
            self._idle_time = 0.0
            self._settled = False
        else:
            self._idle_time += dt
            if not self._optional:
                self._next_idle = max(0.0, self._next_idle - dt)
        if cursor_changed and was_asleep and not active and not reduced:
            self._start_optional("wake")

        target = self._point if self._point is not None else destination
        left, top, right, bottom = bounds
        target = (max(left, min(right, target[0])), max(top, min(bottom, target[1])))
        x, y = self.position
        distance = math.dist((x, y), target)
        if abs(target[0] - x) > 2:
            self.facing_left = target[0] < x
        # Pursuit has its own reaction delay and speed; animation never drives it.
        # Keep the public position assignable for monitor transfer and first show.
        self._motion.position = self.position
        self.position = self._motion.update(
            dt,
            target,
            bounds,
            immediate=self.point_active,
            reduced=reduced,
            delay=self.profile.follow_delay,
            speed=self.profile.move_speed,
            arrival_radius=0.5 if self.point_active else 16.0,
        )
        moving = self._motion.moving
        if moving and self._optional in {"attentive", "alternative", "settle"}:
            self._clear_optional()
        if self._point is not None and math.dist(self.position, target) < 2:
            self._point_hold += dt
            moving = False
            if self._point_hold >= 0.8:
                self._point = None

        if self._optional:
            multiplier = self.settings.jump_speed if self._optional == "jump" else 1.0
            self._optional_elapsed += dt * multiplier
            clip = self.clips[self._optional]
            if self._optional_elapsed >= clip.duration:
                self._clear_optional()
                self._cooldown = self.profile.cooldown
                self._next_idle = self.rng.uniform(*self.profile.idle_interval)

        can_play = (
            not active
            and not reduced
            and self._reaction_remaining <= 0
            and self._idle_time < self.settings.sleep_after_seconds
        )
        if (
            self._motion.just_arrived
            and can_play
            and not self._optional
            and self.settings.jump_frequency > 0
            and self._arrival_cooldown <= 0
            and "jump" in self.clips
        ):
            self._start_optional("jump")
            self._arrival_cooldown = max(4.0, self.profile.cooldown)
        if (
            not active
            and not moving
            and not self._optional
            and not self._settled
            and self._idle_time >= self.settings.sleep_after_seconds
        ):
            self._settled = True
            if not reduced:
                self._start_optional("settle")
        if not moving:
            self._traversal_checked = False
            self._hop_distance = 0.0
        else:
            self._hop_distance += math.dist((x, y), self.position)
            if self._hop_distance >= 160:
                self._traversal_checked = False
                self._hop_distance = 0.0
        if moving and not self._traversal_checked and distance >= 100:
            self._traversal_checked = True
            probability = min(1.0, self.profile.hop_probability * self.settings.jump_frequency)
            if (
                can_play
                and not self._optional
                and self._cooldown <= 0
                and self.rng.random() < probability
            ):
                self._start_optional("jump")
        if (
            can_play
            and not self._optional
            and self.settings.playful_idle
            and not moving
            and self._idle_time >= 5.0
            and self._next_idle <= 0.0
            and self._cooldown <= 0
        ):
            candidates = [
                a
                for a in ("jump", "alternative", "attentive")
                if a in self.clips
                and a != self._last_optional
                and (a != "jump" or self.settings.jump_frequency > 0)
            ]
            if candidates:
                weights = [self.settings.jump_frequency if a == "jump" else 1.0 for a in candidates]
                self._start_optional(self.rng.choices(candidates, weights=weights, k=1)[0])

        if self._reaction_remaining > 0:
            action = "reaction"
        elif self.state == "listening":
            action = "attentive"
        elif moving:
            action = self._optional or ("run" if distance > 180 else "walk")
        elif self.speaking:
            action = "speaking"
        elif self.state == "processing" or (self.state == "responding" and not self.streaming):
            action = "thinking"
        elif self.state == "responding" and self.streaming:
            action = "responding"
        elif self._optional:
            action = self._optional
        elif self._idle_time >= self.settings.sleep_after_seconds:
            action = "sleep"
        else:
            action = "idle"
        self.action = action if action in self.clips else "idle"
        # Current sheets bake their vertical movement into the original cells.
        self.vertical_offset = 0.0
        return self.position
