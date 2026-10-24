"""VoiceState enum — the high-level phase the companion is currently in."""

from __future__ import annotations

from enum import StrEnum


class VoiceState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    RESPONDING = "responding"
