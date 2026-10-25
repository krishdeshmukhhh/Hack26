"""Task map tests use real SQLite files under tmp_path and an injected clock."""

import asyncio
from datetime import UTC, datetime, timedelta

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
)
from curio.task_map import (
    SqliteTaskMap,
    clean_steps,
    format_for_prompt,
    task_similarity,
    tasks_match,
)

APP = "excel"
TASK = "insert a pivot table"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, days: float) -> None:
        self.now += timedelta(days=days)


def event(index, label, outcome=StepOutcome.SUCCEEDED, x=0.1, y=0.2, task=TASK):
    return StepEvent(
        walkthrough_id="w",
        app=APP,
        task=task,
        step_index=index,
        instruction=f"click {label}",
        assistance=AssistanceLevel.POINTED,
        outcome=outcome,
        element=ElementRef(label=label, x=x, y=y, window_title="Book1 - Excel"),
        concepts=("pivot tables",),
    )


def summary(*labels, completed=True, task=TASK, extra=()):
    steps = tuple(extra) + tuple(event(i, label, task=task) for i, label in enumerate(labels, 1))
    return WalkthroughSummary(
        walkthrough_id="w", app=APP, task=task, steps=steps, completed=completed
    )


def run(tmp_path, scenario, clock=None):
    async def main():
        async with SqliteTaskMap(tmp_path / "map.sqlite3", clock=clock or Clock()) as task_map:
            return await scenario(task_map)

    return asyncio.run(main())


# --- recording ---------------------------------------------------------------


def test_incomplete_summary_is_ignored(tmp_path):
    async def scenario(m):
        assert await m.record(summary("insert", "pivottable", completed=False)) is None
        return await m.paths()

    assert run(tmp_path, scenario) == ()


def test_record_creates_path_and_persists(tmp_path):
    async def scenario(m):
        path = await m.record(summary("insert", "pivottable", "ok"))
        assert path is not None
        assert [s.element.label for s in path.steps] == ["insert", "pivottable", "ok"]
        assert path.source == PathSource.LOCAL and path.verified_count == 1

    run(tmp_path, scenario)

    async def reopen(m):
        return await m.find(APP, TASK)

    found = run(tmp_path, reopen)
    assert found is not None and found.steps[0].element.window_title == "Book1 - Excel"


def test_clean_steps_drops_retries_and_renumbers():
    events = (
        event(1, "insert"),
        event(2, "pivot chart", StepOutcome.RETRIED),
        event(2, "pivottable", StepOutcome.TIMED_OUT),
        event(2, "pivottable"),
        event(4, "ok"),  # the model skipped a number
        event(5, "cancel", StepOutcome.ABANDONED),
    )
    steps = clean_steps(events)
    assert [(s.index, s.element.label) for s in steps] == [
        (1, "insert"),
        (2, "pivottable"),
        (3, "ok"),
    ]


def test_clean_steps_keeps_last_success_for_an_index():
    steps = clean_steps((event(1, "insert", x=0.1), event(1, "insert", x=0.3)))
    assert len(steps) == 1 and steps[0].element.x == 0.3


def test_same_labels_increase_verified_count(tmp_path):
    async def scenario(m):
        first = await m.record(summary("insert", "pivottable"))
        reworded = summary("Insert", "PivotTable", task="how do i insert pivot tables")
        second = await m.record(reworded)
        assert second.id == first.id and second.verified_count == 2
        return await m.paths()

    assert len(run(tmp_path, scenario)) == 1


def test_different_labels_store_an_alternative(tmp_path):
    async def scenario(m):
        await m.record(summary("insert", "pivottable"))
        await m.record(summary("insert", "pivottable"))
        await m.record(summary("data", "summarize with pivottable"))
        paths = await m.paths(APP)
        assert len(paths) == 2
        return await m.find(APP, TASK)

    best = run(tmp_path, scenario)
    assert best.verified_count == 2 and best.steps[0].element.label == "insert"


def test_unrelated_task_is_a_separate_path(tmp_path):
    async def scenario(m):
        await m.record(summary("insert", "pivottable"))
        await m.record(summary("insert", "pivottable", task="insert a chart"))
        return await m.paths()

    assert {p.task for p in run(tmp_path, scenario)} == {"insert a pivot table", "insert a chart"}


def test_self_healing_new_path_overtakes_stale_one(tmp_path):
    clock = Clock()

    async def scenario(m):
        for _ in range(5):
            await m.record(summary("insert", "pivottable"))
        clock.advance(60)  # an app update moved the button into the data tab
        old = await m.find(APP, TASK)
        assert old.steps[0].element.label == "insert"

        await m.record(summary("data", "pivottable"))
        await m.record(summary("data", "pivottable"))
        still_old = await m.find(APP, TASK)
        assert still_old.steps[0].element.label == "insert"  # 4 recent vs 5 stale

        await m.record(summary("data", "pivottable"))
        healed = await m.find(APP, TASK)
        assert healed.steps[0].element.label == "data"  # 6 recent vs 5 stale
        assert healed.verified_count == 3

    run(tmp_path, scenario, clock)


# --- finding -----------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "how do i insert a pivot table",
        "insert pivot tables",
        "add a pivot table",
        "insert a pivot table in excel",
        "can you insert pivot table please",
    ],
)
def test_find_matches_near_misses(tmp_path, query):
    async def scenario(m):
        await m.record(summary("insert", "pivottable"))
        return await m.find(APP, query)

    assert run(tmp_path, scenario) is not None


@pytest.mark.parametrize(
    "query",
    ["insert a chart", "insert a pivot chart", "delete a pivot table", "sort a column"],
)
def test_find_rejects_different_tasks(tmp_path, query):
    async def scenario(m):
        await m.record(summary("insert", "pivottable"))
        return await m.find(APP, query)

    assert run(tmp_path, scenario) is None


def test_find_is_scoped_to_app(tmp_path):
    async def scenario(m):
        await m.record(summary("insert", "pivottable"))
        return await m.find("word", TASK)

    assert run(tmp_path, scenario) is None


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("make a new folder", "create folder"),
        ("turn on dark mode", "enable dark mode"),
        ("switch off notifications", "disable notifications"),
    ],
)
def test_synonyms_match(a, b):
    assert tasks_match(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("enable dark mode", "disable dark mode"),
        ("turn on dark mode", "turn off dark mode"),
        ("show the ruler", "hide the ruler"),
        ("open a file", "save a file"),
    ],
)
def test_opposites_and_different_verbs_dont_match(a, b):
    assert not tasks_match(a, b)


def test_similarity_drops_the_app_name():
    assert task_similarity("insert pivot table in excel", "insert pivot table", "excel") == 1.0


# --- merge -------------------------------------------------------------------


def shared_path(*labels, verified=4, difficulty=0.5, task=TASK):
    return TaskPath(
        app=APP,
        task=task,
        source=PathSource.SHARED,
        verified_count=verified,
        steps=tuple(
            PathStep(
                index=i,
                instruction=f"click {label}",
                element=ElementRef(label=label, x=0.5, y=0.5),
                difficulty=difficulty,
            )
            for i, label in enumerate(labels, 1)
        ),
    )


def test_merge_is_idempotent(tmp_path):
    async def scenario(m):
        pull = [shared_path("insert", "pivottable"), shared_path("data", "pivottable", verified=2)]
        assert await m.merge(pull) == 2
        assert await m.merge(pull) == 0
        # path_from_wire mints fresh ids on every pull; identity is content-based.
        fresh = [shared_path("insert", "pivottable"), shared_path("data", "pivottable", verified=2)]
        assert await m.merge(fresh) == 0
        assert await m.merge([shared_path("insert", "pivottable", verified=9)]) == 1
        return await m.paths()

    paths = run(tmp_path, scenario)
    assert len(paths) == 2 and all(p.source == PathSource.SHARED for p in paths)
    assert max(p.verified_count for p in paths) == 9


def test_merge_keeps_difficulty_and_shared_path_is_found(tmp_path):
    async def scenario(m):
        await m.merge([shared_path("insert", "pivottable", difficulty=0.7)])
        return await m.find(APP, "how do i insert a pivot table")

    found = run(tmp_path, scenario)
    assert found.source == PathSource.SHARED
    assert [s.difficulty for s in found.steps] == [0.7, 0.7]


def test_local_preferred_when_comparable(tmp_path):
    async def scenario(m):
        await m.record(summary("insert", "pivottable"))  # strength 2 recent, x1.5 = 3
        await m.merge([shared_path("data", "pivottable", verified=3)])
        return await m.find(APP, TASK)

    found = run(tmp_path, scenario)
    assert found.source == PathSource.LOCAL


def test_stronger_shared_path_wins(tmp_path):
    async def scenario(m):
        await m.record(summary("insert", "pivottable"))
        await m.merge([shared_path("data", "pivottable", verified=20)])
        return await m.find(APP, TASK)

    found = run(tmp_path, scenario)
    assert found.source == PathSource.SHARED and found.steps[0].element.label == "data"


def test_local_path_borrows_difficulty_from_identical_shared_path(tmp_path):
    async def scenario(m):
        await m.record(summary("insert", "pivottable"))
        await m.merge([shared_path("insert", "pivottable", verified=2, difficulty=0.6)])
        return await m.find(APP, TASK)

    found = run(tmp_path, scenario)
    assert found.source == PathSource.LOCAL
    assert [s.difficulty for s in found.steps] == [0.6, 0.6]


def test_merge_drops_window_titles(tmp_path):
    path = shared_path("insert")
    leaky = TaskPath(
        app=APP,
        task=TASK,
        source=PathSource.SHARED,
        steps=(
            PathStep(
                index=1,
                instruction="click insert",
                element=ElementRef(label="insert", x=0.1, y=0.1, window_title="secret.xlsx"),
            ),
        ),
    )

    async def scenario(m):
        await m.merge([path, leaky])
        return await m.paths()

    assert all(s.element.window_title == "" for p in run(tmp_path, scenario) for s in p.steps)


# --- prompt formatting -------------------------------------------------------


def _prompt_path(difficulty=None):
    return TaskPath(
        app=APP,
        task=TASK,
        verified_count=3,
        steps=(
            PathStep(
                index=1,
                instruction="Click the Insert tab.",
                element=ElementRef(label="Insert tab", x=0.12, y=0.045),
            ),
            PathStep(
                index=2,
                instruction="Click PivotTable",
                element=ElementRef(label="PivotTable", x=0.5, y=0.25),
                difficulty=difficulty,
            ),
            PathStep(index=3, instruction="Press OK"),
        ),
    )


def test_format_norm1000():
    text = format_for_prompt(_prompt_path(), "norm1000", None)
    assert text == text.lower()
    assert "model-reported completion 3 times on this computer" in text
    assert "completion is not independently verified" in text
    assert "1. click the insert tab. target: insert tab at 120,45" in text
    assert "2. click pivottable. target: pivottable at 500,250" in text
    assert "3. press ok" in text
    assert "stuck" not in text


def test_format_pixel_uses_image_size():
    text = format_for_prompt(_prompt_path(), "pixel", (1280, 800))
    assert "insert tab at 154,36" in text
    assert "pivottable at 640,200" in text


def test_format_pixel_without_size_omits_positions():
    text = format_for_prompt(_prompt_path(), "pixel", None)
    assert "target: insert tab\n" in text and " at " not in text.split(":", 1)[1]


def test_format_marks_hard_steps():
    text = format_for_prompt(_prompt_path(difficulty=0.6), "norm1000", None)
    lines = text.splitlines()
    assert "recorded stuck-event rate: 60%" in lines[2]
    assert "not a unique-user or validated failure rate" in lines[2]
    assert "stuck" not in lines[1]


def test_format_shared_and_unknown_coords():
    path = shared_path("insert", verified=1)
    assert "model-reported completion once from shared records" in format_for_prompt(
        path, "norm1000", None
    )
    with pytest.raises(ValueError):
        format_for_prompt(path, "inches", None)


# --- local difficulty --------------------------------------------------------


def test_local_difficulty_from_history(tmp_path):
    retry = event(2, "pivot chart", StepOutcome.RETRIED)

    async def scenario(m):
        d = m.local_difficulty
        assert d.step_difficulty(APP, TASK, 1) is None
        await m.record(summary("insert", "pivottable", extra=[retry]))
        await m.record(summary("insert", "pivottable"))
        # An abandoned walkthrough still counts: that's where people get stuck.
        await m.record(
            WalkthroughSummary(
                walkthrough_id="w",
                app=APP,
                task=TASK,
                completed=False,
                steps=(event(1, "insert"), event(2, "x", StepOutcome.TIMED_OUT)),
            )
        )
        return d

    d = run(tmp_path, scenario)
    assert d.step_difficulty(APP, TASK, 1) == 0.0
    assert d.step_difficulty(APP, TASK, 2) == pytest.approx(2 / 4)
    assert d.step_difficulty(APP, "how do i insert pivot tables", 2) == pytest.approx(0.5)
    assert d.step_difficulty(APP, TASK, 9) is None
    assert d.step_difficulty(APP, "insert a chart", 1) is None


def test_local_difficulty_loads_on_startup(tmp_path):
    async def seed(m):
        await m.record(summary("insert", extra=[event(1, "insert", StepOutcome.RETRIED)]))

    run(tmp_path, seed)

    async def reopen(m):
        assert m.local_difficulty.step_difficulty(APP, TASK, 1) is None  # not loaded yet
        await m.refresh_difficulty()
        return m.local_difficulty.step_difficulty(APP, TASK, 1)

    assert run(tmp_path, reopen) == pytest.approx(0.5)


def test_closed_map_rejects_calls(tmp_path):
    async def main():
        m = SqliteTaskMap(tmp_path / "m.sqlite3")
        await m.close()
        with pytest.raises(RuntimeError):
            await m.find(APP, TASK)

    asyncio.run(main())
