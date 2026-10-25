"""Turns a streaming LLM reply into speakable sentence chunks.

The reply carries control tags ([POINT:...], [STEP:k/n], [CONCEPTS:...]) that
must never be spoken. They arrive at the end, possibly split across stream
chunks, so anything from an unmatched ``[`` onwards is held back until the tag
completes (and is then stripped) or the stream ends.
"""

from __future__ import annotations

import re

from curio.clients.kokoro_tts_client import split_sentences
from curio.point_parser import _ANY_TAG_RE, strip_tags_for_display

# Don't start speech on a fragment shorter than this; tiny first chunks sound
# choppy ("Sure.").
MIN_FIRST_CHUNK_CHARS = 24

# A sentence terminator (optionally followed by a closing quote/bracket) that
# is already followed by whitespace, so "3.5" or a trailing "ok." mid-token
# isn't treated as a finished sentence.
_BOUNDARY_RE = re.compile(r"[.!?]['\"\)]?(?=\s)")


def speakable_prefix(streamed: str) -> str:
    """The part of the streamed reply that is safe to speak so far."""
    text = _ANY_TAG_RE.sub("", streamed)
    open_at = text.rfind("[")
    if open_at != -1 and "]" not in text[open_at:]:
        text = text[:open_at]
    return text


class SpeechChunker:
    """Feed streamed text in, get finished sentence chunks out, in order."""

    def __init__(self) -> None:
        self._streamed = ""
        self._consumed = 0  # chars of speakable_prefix() already handed out

    def feed(self, delta: str) -> list[str]:
        """Add streamed text; return chunks that are complete and ready to speak."""
        self._streamed += delta
        pending = speakable_prefix(self._streamed)[self._consumed:]
        ends = [m.end() for m in _BOUNDARY_RE.finditer(pending)]
        if not ends:
            return []
        ready = pending[: ends[-1]].strip()
        if len(ready) < MIN_FIRST_CHUNK_CHARS:
            return []
        self._consumed += ends[-1]
        return split_sentences(ready)

    def finish(self, full_text: str = "") -> list[str]:
        """The stream ended: return whatever text is left (tags stripped).

        ``full_text`` is used when the client never streamed any deltas.
        """
        if not self._streamed:
            self._streamed = full_text
        rest = strip_tags_for_display(self._streamed)
        # strip_tags_for_display trims, so compare against a trimmed prefix.
        done = speakable_prefix(self._streamed)[: self._consumed].strip()
        rest = (rest[len(done):] if rest.startswith(done) else "").strip()
        self._consumed = len(self._streamed)
        return [rest] if rest else []
