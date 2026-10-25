"""In-memory conversation history for the Claude client.

Keeps a capped list of (user_transcript, assistant_text) tuples. Composes
Claude message arrays where prior turns are text-only and only the current
turn carries JPEG images, which controls token cost.
"""

from __future__ import annotations

from collections import deque
from typing import Any

# Keep the last 10 exchanges.
MAX_TURNS = 10


class ConversationHistory:
    def __init__(self) -> None:
        self._turns: deque[tuple[str, str]] = deque(maxlen=MAX_TURNS)

    def append(self, user_text: str, assistant_text: str) -> None:
        self._turns.append((user_text, assistant_text))

    def turn_count(self) -> int:
        return len(self._turns)

    def clear(self) -> None:
        self._turns.clear()

    def messages_for_request(
        self,
        current_user_text: str,
        current_images: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        # Prior turns: text-only, to keep token/cost footprint sane.
        for user_text, assistant_text in self._turns:
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": assistant_text})
        # Current turn: text + images as content blocks.
        if current_images:
            content = [*current_images, {"type": "text", "text": current_user_text}]
        else:
            content = current_user_text
        messages.append({"role": "user", "content": content})
        return messages
