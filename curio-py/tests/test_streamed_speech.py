"""Sentence-chunked speech while the LLM streams: chunker and manager wiring."""

from __future__ import annotations

import asyncio

from curio.speech_chunker import SpeechChunker, speakable_prefix
from curio.state import VoiceState
from tests.test_walkthrough import (
    FakeLLM,
    _ask,
    _manager,
    _settle,
    qt_app,  # noqa: F401  (fixture)
)

REPLY = (
    "Click the File menu in the top left. Then choose Export from the list. "
    "[POINT:40,120:file menu] [STEP:1/2] [CONCEPTS:export]"
)


def _stream(chunker: SpeechChunker, pieces: list[str]) -> list[str]:
    out: list[str] = []
    for piece in pieces:
        out.extend(chunker.feed(piece))
    return out


def test_speakable_prefix_holds_back_open_tag() -> None:
    assert speakable_prefix("Hello there. [POI") == "Hello there. "
    assert speakable_prefix("Hello there. [POINT:1,2:lab") == "Hello there. "
    assert speakable_prefix("Hello. [POINT:none]") == "Hello."
    assert speakable_prefix("Hello. [STEP:1/2] More") == "Hello. More"


def test_first_sentence_spoken_before_stream_ends() -> None:
    chunker = SpeechChunker()
    chunks = _stream(chunker, ["Click the File menu ", "in the top left. The", "n choose"])
    assert chunks == ["Click the File menu in the top left."]


def test_tags_split_across_chunks_are_never_spoken() -> None:
    chunker = SpeechChunker()
    pieces = list(REPLY)  # one character at a time: worst case for split tags
    spoken = _stream(chunker, pieces) + chunker.finish()
    joined = " ".join(spoken)
    assert "[" not in joined and "POINT" not in joined and "STEP" not in joined
    assert joined == (
        "Click the File menu in the top left. Then choose Export from the list."
    )


def test_short_first_sentence_waits_for_more() -> None:
    chunker = SpeechChunker()
    assert _stream(chunker, ["Sure. "]) == []
    assert _stream(chunker, ["Click the File menu at the top. "]) == [
        "Sure. Click the File menu at the top."
    ]


def test_finish_without_deltas_uses_full_text() -> None:
    assert SpeechChunker().finish("Open settings now. [POINT:none]") == ["Open settings now."]


def test_finish_only_tags_is_silent() -> None:
    chunker = SpeechChunker()
    chunker.feed("[POINT:none]")
    assert chunker.finish() == []


class StreamingTTS:
    """FakeTTS that also supports speak_stream, recording chunk arrival order."""

    def __init__(self, base) -> None:
        self._base = base
        self.chunks: list[str] = []
        self.stopped = 0
        self.cancelled = False
        self.error = base.error
        self.playback_started = base.playback_started
        self.playback_finished = base.playback_finished

    async def speak(self, text: str) -> None:
        self.chunks.append(f"WHOLE:{text}")

    async def speak_stream(self, chunks) -> None:
        try:
            async for chunk in chunks:
                self.chunks.append(chunk)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    def stop(self) -> None:
        self.stopped += 1


class DeltaLLM(FakeLLM):
    """Emits the reply in tiny deltas, pausing so the test can observe mid-stream."""

    def __init__(self, replies, step=4, gate: asyncio.Event | None = None) -> None:
        super().__init__(replies)
        self.step = step
        self.gate = gate

    async def send(self, messages, system, model, max_tokens=1024) -> str:
        reply = await super().send(messages, system, model, max_tokens)
        for i in range(0, len(reply), self.step):
            self.delta.emit(reply[i : i + self.step])
            await asyncio.sleep(0)
            if self.gate is not None and i > len(reply) // 2:
                await self.gate.wait()
        return reply


def _streaming_manager(monkeypatch, llm_factory):
    manager, parts = _manager([REPLY], monkeypatch)
    tts = StreamingTTS(parts["tts"])
    llm = llm_factory(parts["llm"].replies)
    manager._tts = tts
    manager._llm = llm
    llm.delta.connect(manager._on_llm_delta)
    parts["tts"], parts["llm"] = tts, llm
    return manager, parts


def test_streamed_turn_speaks_sentences_in_order(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts = _streaming_manager(monkeypatch, DeltaLLM)

    async def run() -> None:
        _ask(manager, "how do i export")
        await _settle(manager)

    asyncio.run(run())
    assert parts["tts"].chunks == [
        "Click the File menu in the top left.",
        "Then choose Export from the list.",
    ]
    assert parts["overlays"].flights  # POINT still honoured
    assert parts["annotations"][-1][0] == "file menu"


def test_cancel_mid_stream_stops_queued_audio(qt_app, monkeypatch) -> None:  # noqa: F811
    gate = asyncio.Event()
    manager, parts = _streaming_manager(
        monkeypatch, lambda replies: DeltaLLM(replies, gate=gate)
    )

    async def run() -> None:
        _ask(manager, "how do i export")
        for _ in range(200):
            await asyncio.sleep(0.01)
            if parts["tts"].chunks:
                break
        assert parts["tts"].chunks  # speech began while the LLM is still blocked
        assert not manager._speak_task.done()
        manager._on_hotkey_cancelled()
        gate.set()
        await asyncio.sleep(0.1)

    asyncio.run(run())
    assert parts["tts"].stopped >= 1
    assert parts["tts"].cancelled
    assert manager._speech is None
    assert parts["overlays"].flights == []


def _patched_streaming(monkeypatch, speak_stream, llm_factory=DeltaLLM):
    """Manager whose original FakeTTS (so sender() matches) streams via ``speak_stream``."""
    manager, parts = _manager([REPLY], monkeypatch)
    tts = parts["tts"]
    tts.speak_stream = lambda chunks: speak_stream(tts, chunks)
    llm = llm_factory(parts["llm"].replies)
    manager._llm = llm
    llm.delta.connect(manager._on_llm_delta)
    parts["llm"] = llm
    parts["errors"] = []
    manager.error.connect(parts["errors"].append)
    return manager, parts


def test_tts_error_mid_stream_ends_turn(qt_app, monkeypatch) -> None:  # noqa: F811
    async def failing(tts, chunks) -> None:
        async for _ in chunks:
            tts.error.emit("kokoro boom")
            return

    gate = asyncio.Event()
    manager, parts = _patched_streaming(
        monkeypatch, failing, lambda replies: DeltaLLM(replies, gate=gate)
    )

    async def run() -> None:
        _ask(manager, "how do i export")
        await asyncio.sleep(0.3)
        gate.set()
        await asyncio.sleep(0.1)

    asyncio.run(run())
    assert parts["errors"] == ["kokoro boom"]
    assert manager._state == VoiceState.IDLE
    assert manager._speech is None


def test_speech_ending_before_reply_still_leaves_responding(qt_app, monkeypatch) -> None:  # noqa: F811
    async def quits_early(tts, chunks) -> None:
        async for _ in chunks:
            return

    manager, parts = _patched_streaming(monkeypatch, quits_early)

    async def run() -> None:
        _ask(manager, "how do i export")
        await _settle(manager)
        await asyncio.sleep(0.1)

    asyncio.run(run())
    # The reply carries a STEP tag, so the walkthrough waits for the click.
    assert manager._state == VoiceState.GUIDING


def test_exception_after_llm_closes_the_speech(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts = _streaming_manager(monkeypatch, DeltaLLM)

    def boom(*_args) -> None:
        raise RuntimeError("walkthrough failed")

    monkeypatch.setattr(manager, "_update_walkthrough", boom)

    async def run() -> None:
        _ask(manager, "how do i export")
        await _settle(manager)
        await asyncio.sleep(0.1)

    asyncio.run(run())
    assert manager._speak_task.done()
    assert parts["tts"].cancelled
    assert manager._speech is None
    assert manager._state == VoiceState.IDLE
