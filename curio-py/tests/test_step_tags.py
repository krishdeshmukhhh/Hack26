from curio.point_parser import (
    PointTag,
    StepTag,
    parse_point_tag,
    parse_step_tag,
    strip_tags_for_display,
)


def test_step_after_point() -> None:
    raw = "open the file menu first. [POINT:30,15:file menu] [STEP:1/3]"
    text, step = parse_step_tag(raw)
    assert step == StepTag(1, 3) and step.has_more
    spoken, point = parse_point_tag(text)
    assert spoken == "open the file menu first."
    assert point == PointTag(30, 15, "file menu")


def test_step_before_point() -> None:
    text, step = parse_step_tag("click export. [STEP:2/3] [POINT:500,80:export]")
    assert step == StepTag(2, 3)
    assert parse_point_tag(text) == ("click export.", PointTag(500, 80, "export"))


def test_last_step_and_no_step() -> None:
    assert not parse_step_tag("done! [POINT:none] [STEP:3/3]")[1].has_more
    assert parse_step_tag("html is markup. [POINT:none]") == ("html is markup. [POINT:none]", None)


def test_step_total_never_below_index() -> None:
    # The model underestimated the step count; treat the current step as the last.
    assert parse_step_tag("one more thing [STEP:4/3]")[1] == StepTag(4, 4)


def test_strip_tags_for_display() -> None:
    assert strip_tags_for_display("click save. [POINT:10,20:save] [STEP:1/2]") == "click save."
    assert strip_tags_for_display("click save. [POI") == "click save."
    assert strip_tags_for_display("click save. [POINT:10,2") == "click save."
    assert strip_tags_for_display("press [") == "press"
    assert strip_tags_for_display("use ctrl [shift] too") == "use ctrl [shift] too"


def test_howto_detection() -> None:
    from curio.prompts import is_howto_question

    for q in ["how do i change my wallpaper", "How can I export this?", "walk me through it",
              "show me how to add a layer", "help me set up a new event", "steps to rename a file",
              # Whisper dropped the "how":
              "Do I enable light mode on VS Code?", "can i turn off notifications",
              "i want to export this as a pdf", "where do i change the font size"]:
        assert is_howto_question(q), q
    for q in ["what is html", "what's the capital of france", "where is the save button",
              "why is this red", "however you like", "what's on my screen right now?",
              "do i have any unread emails", "can you see my desktop"]:
        assert not is_howto_question(q), q
