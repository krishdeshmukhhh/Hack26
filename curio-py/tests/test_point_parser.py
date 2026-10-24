import pytest
from curio.point_parser import PointTag, parse_point_tag


def test_basic_point_with_label():
    text, tag = parse_point_tag("Click the search bar [POINT:100,200:search bar]")
    assert tag == PointTag(x=100, y=200, label="search bar")
    assert tag.screen is None
    assert text == "Click the search bar"


def test_point_with_label_and_screen():
    text, tag = parse_point_tag("Open terminal [POINT:400,300:terminal:screen2]")
    assert tag == PointTag(x=400, y=300, label="terminal", screen=2)
    assert text == "Open terminal"


def test_point_none_strips_tag():
    text, tag = parse_point_tag("I'm not pointing at anything [POINT:none]")
    assert tag is None
    assert text == "I'm not pointing at anything"


def test_no_point_tag_returns_full_text():
    original = "Just a normal response with no tag"
    text, tag = parse_point_tag(original)
    assert tag is None
    assert text == original


def test_label_with_spaces():
    text, tag = parse_point_tag("Adjust here [POINT:50,60:color grading panel]")
    assert tag == PointTag(x=50, y=60, label="color grading panel")


def test_trailing_whitespace_still_parsed():
    text, tag = parse_point_tag("Look here [POINT:1,2:x]   \n")
    assert tag == PointTag(x=1, y=2, label="x")
    assert text == "Look here"


def test_negative_mid_response_not_parsed():
    original = "click [POINT:1,2:x] then do X"
    text, tag = parse_point_tag(original)
    assert tag is None
    assert text == original


def test_negative_point_none_not_at_end():
    original = "[POINT:none] extra"
    text, tag = parse_point_tag(original)
    assert tag is None
    assert text == original


def test_multiple_point_tags_only_last_parsed():
    text, tag = parse_point_tag(
        "First [POINT:10,20:first] then second [POINT:30,40:second]"
    )
    assert tag == PointTag(x=30, y=40, label="second")
    assert text == "First [POINT:10,20:first] then second"
