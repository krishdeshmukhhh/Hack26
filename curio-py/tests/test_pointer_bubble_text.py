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


def test_step_caption_hides_reached_totals() -> None:
    from curio.ui.pointer_bubble import step_caption

    assert step_caption("click this!", None) == "click this!"
    assert step_caption("click this!", (1, 3)) == "click this! (1/3)"
    # The model said 1/1 or 2/2 but the walkthrough may continue.
    assert step_caption("click this!", (1, 1)) == "click this! (step 1)"
    assert step_caption("click this!", (4, 3)) == "click this! (step 4)"
