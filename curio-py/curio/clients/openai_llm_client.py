"""OpenAI-compatible streaming chat client for self-hosted models.

Drop-in replacement for ``LLMClient`` (same ``send`` signature and signals)
that talks to any server exposing ``/v1/chat/completions`` with SSE
streaming — vLLM, SGLang, llama.cpp server, LM Studio, and so on.

The rest of the app builds requests in Anthropic Messages format, so this
module converts them:

* ``system`` becomes a leading ``{"role": "system"}`` message.
* Anthropic ``image`` blocks (base64 source) become OpenAI ``image_url``
  blocks carrying a ``data:`` URI.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


def to_openai_messages(messages: list[dict[str, Any]], system: str) -> list[dict[str, Any]]:
    """Convert Anthropic-format ``messages`` + ``system`` to OpenAI chat format."""
    converted: list[dict[str, Any]] = []
    if system:
        converted.append({"role": "system", "content": system})

    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            converted.append({"role": message["role"], "content": content})
            continue

        parts: list[dict[str, Any]] = []
        for block in content:
            if block.get("type") == "text":
                parts.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "image":
                source = block["source"]
                data_uri = f"data:{source['media_type']};base64,{source['data']}"
                parts.append({"type": "image_url", "image_url": {"url": data_uri}})
        converted.append({"role": message["role"], "content": parts})

    return converted


def parse_openai_sse_lines(raw: bytes) -> Iterator[str]:
    """Yield content deltas from complete OpenAI-style SSE ``data:`` lines.

    Ignores ``[DONE]``, keep-alive comments, malformed JSON, and chunks with
    no text content (role-only deltas, usage chunks, reasoning tokens).
    """
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = payload.get("choices") or []
        if not choices:
            continue
        text = (choices[0].get("delta") or {}).get("content")
        if text:
            yield text


class OpenAICompatLLMClient(QObject):
    """Streaming client for an OpenAI-compatible ``/chat/completions`` endpoint.

    Signals:
        delta(str): Emitted for each text fragment as it streams in.
        done(str):  Emitted once with the full accumulated response text.
        error(str): Emitted when any exception occurs during the request.
    """

    delta = Signal(str)
    done = Signal(str)
    error = Signal(str)

    def __init__(
        self, base_url: str, api_key: str = "", *, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def send(
        self,
        messages: list[dict],
        system: str,
        model: str,
        max_tokens: int = 1024,
    ) -> str:
        """POST a streaming chat completion and return the full response text."""
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": to_openai_messages(messages, system),
        }
        headers = {"authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        full_text = ""
        buf = b""

        try:
            # Generous read timeout: a cold model on a shared node can take a
            # while to produce its first token.
            timeout = httpx.Timeout(120.0, connect=10.0)
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream("POST", url, json=body, headers=headers) as response,
            ):
                if response.is_error:
                    detail = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"LLM server returned {response.status_code}: {detail}")

                async for chunk in response.aiter_bytes():
                    buf += chunk
                    # Only parse complete lines; keep the partial tail.
                    complete, sep, buf = buf.rpartition(b"\n")
                    if not sep:
                        continue
                    for text_fragment in parse_openai_sse_lines(complete):
                        self.delta.emit(text_fragment)
                        full_text += text_fragment

            if buf.strip():
                for text_fragment in parse_openai_sse_lines(buf):
                    self.delta.emit(text_fragment)
                    full_text += text_fragment

            self.done.emit(full_text)
            return full_text

        except asyncio.CancelledError:
            logger.debug("OpenAICompatLLMClient.send() cancelled")
            raise

        except httpx.ConnectError as exc:
            msg = (
                f"cannot reach LLM server at {self._base_url} — is the VPN up and the "
                f"SSH tunnel running? ({exc})"
            )
            self.error.emit(msg)
            raise RuntimeError(msg) from exc

        except Exception as exc:
            self.error.emit(str(exc))
            raise
