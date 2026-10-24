"""VoiceState enum — the high-level phase the companion is currently in."""

from __future__ import annotations

from enum import StrEnum


class VoiceState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    RESPONDING = "responding"
    # Walkthrough: waiting at the current step's target for the user to do it.
    GUIDING = "guiding"
