import pytest

from curio.learning_contract import (
    AssistanceLevel,
    ElementRef,
    PathSource,
    PathStep,
    StepEvent,
    StepOutcome,
    TaskPath,
    WalkthroughSummary,
    app_key,
    concept_key,
    path_from_wire,
    path_to_wire,
    summary_to_wire,
    task_key,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Book1 - Excel", "excel"),
        ("notes.txt - Notepad", "notepad"),
        ("Settings", "settings"),
        ("Untitled — Figma", "figma"),
        ("", ""),
    ],
)
def test_app_key(title, expected):
    assert app_key(title) == expected


def test_task_key_strips_filler_and_punctuation():
    assert task_key("Hey Curio, how do I insert a Pivot Table?") == "insert a pivot table"
    assert task_key("insert a pivot table") == "insert a pivot table"


def test_concept_key():
    assert concept_key("  Pivot-Tables ") == "pivot tables"


def _summary():
    step = StepEvent(
        walkthrough_id="w1",
        app="excel",
        task="insert a pivot table",
        step_index=1,
        instruction="click insert",
        assistance=AssistanceLevel.POINTED,
        outcome=StepOutcome.SUCCEEDED,
        element=ElementRef(label="insert tab", x=0.1, y=0.05, window_title="Salaries.xlsx - Excel"),
        concepts=("ribbon",),
    )
    return WalkthroughSummary(
        walkthrough_id="w1", app="excel", task="insert a pivot table", steps=(step,), completed=True
    )


def test_summary_wire_is_anonymous():
    wire = summary_to_wire(_summary())
    text = repr(wire)
    assert "Salaries" not in text
    assert "w1" not in text
    assert wire["steps"][0]["element"] == {"label": "insert tab", "x": 0.1, "y": 0.05}


def test_path_round_trip_marks_shared():
    path = TaskPath(
        app="excel",
        task="insert a pivot table",
        steps=(PathStep(index=1, instruction="click insert", concepts=("ribbon",), difficulty=0.4),),
        verified_count=3,
    )
    back = path_from_wire(path_to_wire(path))
    assert back.source is PathSource.SHARED
    assert back.steps == path.steps
    assert back.verified_count == 3


def test_path_from_wire_rejects_unknown_version():
    with pytest.raises(ValueError):
        path_from_wire({"v": 99, "app": "x", "task": "y", "steps": []})
