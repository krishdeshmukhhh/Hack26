from curio.eval.case import Expected
from curio.eval.request import build_request
from curio.eval.scoring import (
    overall,
    parse_reply,
    point_in_box,
    score_reply,
    score_to_dict,
    summarize_case,
)
from curio.screen_capture import ScreenshotImage


def _shot() -> ScreenshotImage:
    return ScreenshotImage(
        jpeg_bytes=b"jpg", label="user's screen (image dimensions: 1280x720 pixels)",
        is_cursor_screen=True, display_width_px=1920, display_height_px=1080,
        image_width_px=1280, image_height_px=720, scale=1280 / 1920,
        monitor_left=0, monitor_top=0,
    )


GOOD = "first minimize this window. [POINT:930,20:minimize button] [STEP:1/4] [CONCEPTS:windows]"


def test_parse_reply_norm1000_maps_to_image_pixels():
    parsed = parse_reply(GOOD, [_shot()], "norm1000")
    assert parsed.step == 1 and parsed.total_steps == 4
    assert parsed.has_point_tag
    assert parsed.point[0] == 1
    assert abs(parsed.point[1] - 930 * 1280 / 1000) <= 2
    assert abs(parsed.point[2] - 20 * 720 / 1000) <= 2
    assert "[" not in parsed.spoken


def test_parse_reply_pixel_passthrough():
    parsed = parse_reply("go. [POINT:100,50:x] [STEP:1/2]", [_shot()], "pixel")
    assert parsed.point == (1, 100, 50)


def test_point_none_is_well_formed_without_point():
    parsed = parse_reply("it is done. [POINT:none]", [_shot()], "pixel")
    assert parsed.has_point_tag and parsed.point is None


def test_missing_tags_not_well_formed():
    parsed = parse_reply("just talk", [_shot()], "pixel")
    assert not score_reply(parsed, Expected()).well_formed
    assert not score_reply(parsed, Expected()).passed


def test_howto_requires_step_but_not_otherwise():
    parsed = parse_reply("hi [POINT:none]", [_shot()], "pixel")
    assert not score_reply(parsed, Expected(), howto=True).well_formed
    assert score_reply(parsed, Expected(), howto=False).well_formed


def test_keywords_any_of_and_forbidden_case_insensitive():
    parsed = parse_reply(GOOD, [_shot()], "norm1000")
    assert score_reply(parsed, Expected(first_step_keywords=("MINIMIZE", "close"))).keyword_pass
    assert not score_reply(parsed, Expected(first_step_keywords=("maximize",))).keyword_pass
    assert not score_reply(
        parsed, Expected(first_step_keywords=("minimize",), forbidden_keywords=("Window",))
    ).keyword_pass
    assert score_reply(parsed, Expected()).keyword_pass is None


def test_point_box_and_screen():
    parsed = parse_reply(GOOD, [_shot()], "norm1000")
    inside = {"screen": 1, "x0": 1150, "y0": 0, "x1": 1230, "y1": 40}
    outside = {"screen": 1, "x0": 0, "y0": 0, "x1": 100, "y1": 100}
    wrong_screen = {**inside, "screen": 2}
    assert score_reply(parsed, Expected(point_box=inside)).point_pass is True
    assert score_reply(parsed, Expected(point_box=outside)).point_pass is False
    assert point_in_box(parsed.point, wrong_screen) is False
    assert point_in_box(None, inside) is False


def test_min_steps():
    parsed = parse_reply(GOOD, [_shot()], "norm1000")
    assert score_reply(parsed, Expected(min_steps=4)).steps_pass is True
    assert score_reply(parsed, Expected(min_steps=5)).steps_pass is False
    assert not score_reply(parsed, Expected(min_steps=5)).passed


def test_summarize_and_overall():
    ok = score_to_dict(score_reply(parse_reply(GOOD, [_shot()], "norm1000"), Expected()))
    bad = score_to_dict(score_reply(parse_reply("x", [_shot()], "norm1000"), Expected()))
    runs = [
        {"score": ok, "ttft_s": 1.0, "total_s": 2.0},
        {"score": bad, "ttft_s": 3.0, "total_s": 4.0},
        {"error": "boom"},
    ]
    s = summarize_case(runs)
    assert s["runs"] == 3 and s["errors"] == 1
    assert abs(s["pass_rate"] - 1 / 3) < 1e-9
    assert s["median_ttft_s"] == 2.0 and s["median_total_s"] == 3.0
    o = overall({"a": s, "b": summarize_case([{"score": ok, "ttft_s": 1, "total_s": 1}])})
    assert o["runs"] == 4 and o["pass_rate"] == 0.5


def test_build_request_order_and_reminder():
    from curio.eval.case import EvalCase

    case = EvalCase("c", "how do I change my desktop background?", "WINDOWS", "t", [_shot()])
    messages, system = build_request(case, "norm1000")
    content = messages[0]["content"]
    assert [b["type"] for b in content] == ["text", "text", "image", "text"]
    assert content[0]["text"] == "WINDOWS"
    assert content[1]["text"] == _shot().label
    assert "[STEP:1/N]" in content[-1]["text"]
    assert "0 to 1000" in system

    plain = EvalCase("c", "what is this?", None, "t", [_shot()])
    content = build_request(plain, "pixel")[0][0]["content"]
    assert [b["type"] for b in content] == ["text", "image", "text"]
    assert content[-1]["text"] == "what is this?"
