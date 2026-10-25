"""Build the first-turn request the way the app does for a question."""

from __future__ import annotations

import base64
from typing import Any

from curio.eval.case import EvalCase
from curio.prompts import build_system_prompt, is_howto_question, walkthrough_reminder


def build_request(case: EvalCase, point_coords: str) -> tuple[list[dict[str, Any]], str]:
    """Return ``(anthropic_format_messages, system_prompt)`` for ``case``.

    Mirrors CompanionManager._run_turn (companion_manager.py, "Build image
    content blocks" through build_system_prompt) and
    ConversationHistory.messages_for_request for a first turn with empty
    history: window block, then (label, image) pairs, then the question text
    with the walkthrough reminder for how-to questions. Not replicated:
    memory and learned-path context blocks and the app knowledge base (they
    depend on local state), so absolute numbers can differ slightly from the
    live app. A shared helper in the app would remove this duplication.
    """
    blocks: list[dict[str, Any]] = []
    if case.windows_text:
        blocks.append({"type": "text", "text": case.windows_text})
    for shot in case.screens:
        blocks.append({"type": "text", "text": shot.label})
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(shot.jpeg_bytes).decode("ascii"),
                },
            }
        )
    text = case.question
    if is_howto_question(text):
        text = f"{text}\n{walkthrough_reminder()}"
    messages = [{"role": "user", "content": [*blocks, {"type": "text", "text": text}]}]
    return messages, build_system_prompt(None, None, point_coords=point_coords)
