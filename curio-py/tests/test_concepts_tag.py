from curio.point_parser import (
    PointTag,
    StepTag,
    parse_concepts_tag,
    parse_point_tag,
    parse_step_tag,
    strip_tags_for_display,
)
from curio.prompts import build_system_prompt, walkthrough_reminder


def _parse(raw: str):
    text, step = parse_step_tag(raw)
    text, concepts = parse_concepts_tag(text)
    spoken, point = parse_point_tag(text)
    return spoken, point, step, concepts


def test_concepts_after_step() -> None:
    raw = "click insert. [POINT:120,40:insert tab] [STEP:1/3] [CONCEPTS:Pivot Tables, data]"
    assert _parse(raw) == (
        "click insert.", PointTag(120, 40, "insert tab"), StepTag(1, 3), ("pivot tables", "data")
    )


def test_concepts_before_point() -> None:
    # The model doesn't always keep the order; POINT must still parse at the end.
    raw = "click insert. [STEP:2/3] [CONCEPTS:charts] [POINT:500,80:chart]"
    assert _parse(raw) == ("click insert.", PointTag(500, 80, "chart"), StepTag(2, 3), ("charts",))


def test_concepts_normalised_deduped_and_capped() -> None:
    _, concepts = parse_concepts_tag("x [CONCEPTS: Layers!, layers , , masks, blend-modes, crop]")
    assert concepts == ("layers", "masks", "blend modes")


def test_no_concepts_tag() -> None:
    assert parse_concepts_tag("html is markup. [POINT:none]") == (
        "html is markup. [POINT:none]", ()
    )
    assert parse_concepts_tag("x [CONCEPTS:]") == ("x", ())


def test_concepts_stripped_for_display() -> None:
    assert strip_tags_for_display("click it. [STEP:1/2] [CONCEPTS:layers]") == "click it."
    # Half-streamed tags.
    for partial in ("click it. [CONCEP", "click it. [CONCEPTS", "click it. [CONCEPTS:lay"):
        assert strip_tags_for_display(partial) == "click it.", partial


def test_prompt_asks_for_concepts_on_walkthrough_steps() -> None:
    prompt = build_system_prompt()
    assert "[CONCEPTS:a, b]" in prompt
    assert "not \"insert tab\"" in prompt
    assert "[CONCEPTS:...]" in walkthrough_reminder()
    assert "[CONCEPTS:...]" in walkthrough_reminder(2)
