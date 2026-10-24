"""Anthropic SSE stream parser and streaming HTTP client.

This module provides two layers:

1. A pure parser — ``parse_anthropic_sse_stream`` — that decodes Anthropic
   streaming API SSE bytes into text-delta strings.  Zero Qt / async / network
   dependencies; unit-tested in isolation.
2. ``LLMClient`` — a ``QObject`` that POSTs to a Cloudflare Worker proxy at
   ``/chat`` using ``httpx.AsyncClient`` with streaming enabled, accumulates
   SSE chunks, feeds complete event blocks through the parser, and emits
   ``delta`` / ``done`` / ``error`` Qt signals.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Iterator

import httpx
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


def parse_anthropic_sse_stream(raw: bytes) -> Iterator[str]:
    """Parse an Anthropic SSE byte stream and yield text delta strings.

    Splits the raw bytes on double-newline SSE event boundaries, extracts
    ``event:`` and ``data:`` fields, and yields the ``text`` value from
    ``content_block_delta`` events whose delta type is ``text_delta``.

    Unknown ``content_block_start`` types are silently skipped — any subsequent
    ``content_block_delta`` events for that block are also skipped, preventing
    crashes when the API introduces new block types.

    Events ``message_start``, ``message_delta``, ``message_stop``,
    ``content_block_stop``, and ``ping`` are ignored.

    Args:
        raw: Raw SSE bytes from an Anthropic streaming response.

    Yields:
        Text fragments extracted from ``text_delta`` deltas.
    """
    if not raw:
        return

    text = raw.decode("utf-8", errors="replace")

    # Split on blank lines to get individual SSE events.
    chunks = text.split("\n\n")

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        event_type: str | None = None
        data_line: str | None = None

        for line in chunk.splitlines():
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_line = line[len("data:"):].strip()

        if event_type is None or data_line is None:
            continue

        if event_type != "content_block_delta":
            continue

        try:
            payload = json.loads(data_line)
        except json.JSONDecodeError:
            continue

        delta = payload.get("delta", {})
        if delta.get("type") == "text_delta":
            text_fragment = delta.get("text", "")
            if text_fragment:
                yield text_fragment


class LLMClient(QObject):
    """Streaming HTTP client for the Anthropic Messages API via a worker proxy.

    Emits Qt signals as text deltas arrive so the UI can update in real-time.
    The worker at ``/chat`` forwards the request to
    ``https://api.anthropic.com/v1/messages`` and injects the API key
    server-side.

    Signals:
        delta(str): Emitted for each text fragment as it streams in.
        done(str):  Emitted once with the full accumulated response text.
        error(str): Emitted when any exception occurs during the request.
    """

    delta = Signal(str)
    done = Signal(str)
    error = Signal(str)

    def __init__(self, worker_url: str, *, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker_url = worker_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def send(
        self,
        messages: list[dict],
        system: str,
        model: str,
        max_tokens: int = 1024,
    ) -> str:
        """POST a streaming chat completion and return the full response text.

        Args:
            messages: Anthropic Messages API ``messages`` array.
            system:   System prompt string.
            model:    Model identifier (e.g. ``"claude-sonnet-4-20250514"``).
            max_tokens: Maximum tokens to generate.

        Returns:
            The fully accumulated response text.

        Raises:
            httpx.HTTPStatusError: If the worker returns a non-2xx status.
            asyncio.CancelledError: If the caller cancels the task.
        """
        url = f"{self._worker_url}/chat"
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
            "system": system,
            "messages": messages,
        }

        full_text = ""
        buf = b""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", url, json=body) as response:
                    response.raise_for_status()

                    async for chunk in response.aiter_bytes():
                        buf += chunk

                        # Split on double-newline SSE boundaries.  Keep any
                        # incomplete trailing fragment in *buf* for the next
                        # iteration.
                        while b"\n\n" in buf:
                            event_block, buf = buf.split(b"\n\n", 1)
                            # Re-add the delimiter so the parser sees a
                            # well-formed SSE event block.
                            for text_fragment in parse_anthropic_sse_stream(
                                event_block + b"\n\n"
                            ):
                                self.delta.emit(text_fragment)
                                full_text += text_fragment

            # Flush any remaining bytes in the buffer (final event may lack a
            # trailing blank line).
            if buf.strip():
                for text_fragment in parse_anthropic_sse_stream(buf):
                    self.delta.emit(text_fragment)
                    full_text += text_fragment

            self.done.emit(full_text)
            return full_text

        except asyncio.CancelledError:
            logger.debug("LLMClient.send() cancelled")
            raise

        except Exception as exc:
            self.error.emit(str(exc))
            raise
