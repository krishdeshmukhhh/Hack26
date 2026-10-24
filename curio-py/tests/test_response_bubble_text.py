"""Tests for the speech bubble's pure text helpers (no window needed)."""

from curio.ui.response_bubble import friendly_error, wrap_tail


def _measure(text: str) -> int:
    return len(text)  # one unit per character


def test_wrap_tail_wraps_at_width() -> None:
    assert wrap_tail("aaa bbb ccc ddd", _measure, 7, 5) == ["aaa bbb", "ccc ddd"]


def test_wrap_tail_keeps_newest_lines_and_fits_ellipsis() -> None:
    lines = wrap_tail("one two three four five six seven eight", _measure, 10, 2)
    assert lines[-1] == "eight"
    assert lines[0].startswith("… ")
    assert all(_measure(line) <= 10 for line in lines)


def test_wrap_tail_empty() -> None:
    assert wrap_tail("", _measure, 10, 3) == []


def test_friendly_error_messages() -> None:
    assert "SSH tunnel" in friendly_error("cannot reach LLM server at http://localhost:8000/v1 (x)")
    assert "llm_api_key" in friendly_error("LLM server returned 401: Unauthorized")
    assert friendly_error("short problem") == "short problem"
    assert len(friendly_error("x" * 500)) == 158
