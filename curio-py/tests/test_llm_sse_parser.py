from pathlib import Path

from curio.clients.llm_client import parse_anthropic_sse_stream

FIXTURES = Path(__file__).parent / "fixtures"


def test_basic_stream_yields_text_deltas() -> None:
    raw = (FIXTURES / "anthropic_sse_basic.txt").read_bytes()
    deltas = list(parse_anthropic_sse_stream(raw))
    joined = "".join(deltas)
    assert len(joined) > 0
    assert deltas[0] != ""


def test_unknown_block_types_are_ignored_not_crashed() -> None:
    raw = (FIXTURES / "anthropic_sse_unknown_block.txt").read_bytes()
    deltas = list(parse_anthropic_sse_stream(raw))
    # Unknown blocks must not raise — they are silently skipped.
    # The known text block inside the fixture should still produce deltas.
    joined = "".join(deltas)
    assert "hello" in joined.lower() or len(joined) > 0


def test_empty_stream_yields_nothing() -> None:
    assert list(parse_anthropic_sse_stream(b"")) == []
