"""Tests for the pointer pill's text helpers (no window needed)."""

from curio.ui.pointer_bubble import POINTER_PHRASES, friendly_error, random_pointer_phrase


def test_pointer_phrases_match_macos() -> None:
    assert POINTER_PHRASES == (
        "right here!", "this one!", "over here!", "click this!", "here it is!", "found it!",
    )
    assert random_pointer_phrase() in POINTER_PHRASES


def test_friendly_error_messages() -> None:
    assert "SSH tunnel" in friendly_error("cannot reach LLM server at http://localhost:8000/v1 (x)")
    assert "llm_api_key" in friendly_error("LLM server returned 401: Unauthorized")
    assert "config" in friendly_error("config problem: hotkey must be one of ...")
    assert friendly_error("short problem") == "short problem"
    assert len(friendly_error("x" * 500)) == 58
