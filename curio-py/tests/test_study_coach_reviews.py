import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from curio.focus_contract import ReviewItem
from curio.study_coach import (
    EvidenceBasedCoach,
    SqliteReviewScheduler,
    generate_review_items,
    interleave,
    parse_review_items,
    similar,
)
from curio.study_coach.quiz import FALLBACK_ANSWER, QUIZ_SYSTEM_PROMPT
from curio.study_coach.scheduler import (
    DEFAULT_EASE,
    LAPSE_INTERVAL_DAYS,
    MIN_EASE,
    next_schedule,
)

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def item(concept, question=None, due=T0, **kwargs):
    return ReviewItem(
        concept=concept,
        question=question or f"what is {concept}?",
        answer=f"{concept} answer",
        due_at=due,
        **kwargs,
    )


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


# --- Scheduler -------------------------------------------------------------------


def test_intervals_grow_with_correct_answers():
    current, ease = item("vlookup"), DEFAULT_EASE
    intervals = []
    for _ in range(5):
        current, ease = next_schedule(current, True, ease, T0)
        intervals.append(current.interval_days)
    assert intervals[:2] == [1.0, 3.0]
    assert all(b > a for a, b in zip(intervals, intervals[1:], strict=False))
    assert current.repetitions == 5 and current.lapses == 0
    assert current.due_at == T0 + timedelta(days=intervals[-1])


def test_lapse_resets_interval_and_lowers_ease():
    current, ease = item("vlookup"), DEFAULT_EASE
    for _ in range(4):
        current, ease = next_schedule(current, True, ease, T0)
    before = ease
    current, ease = next_schedule(current, False, ease, T0)
    assert current.interval_days == LAPSE_INTERVAL_DAYS
    assert current.repetitions == 0 and current.lapses == 1
    assert ease == pytest.approx(before - 0.2)
    for _ in range(20):
        current, ease = next_schedule(current, False, ease, T0)
    assert ease == MIN_EASE
    # after a lapse the ladder restarts from the short interval
    current, ease = next_schedule(current, True, ease, T0)
    assert current.interval_days == 1.0


def test_scheduler_round_trip_and_persistence(tmp_path):
    path = tmp_path / "reviews.sqlite3"
    clock = Clock()

    async def scenario():
        async with SqliteReviewScheduler(path, clock=clock) as scheduler:
            first = item("vlookup", due=T0)
            await scheduler.add_review_items([first, item("layers", due=T0 + timedelta(days=2))])
            due = await scheduler.due_reviews(T0)
            assert [d.id for d in due] == [first.id]
            updated = await scheduler.record_review(due[0], True)
            assert updated.due_at == T0 + timedelta(days=1)
            assert await scheduler.due_reviews(T0) == ()
            clock.now = T0 + timedelta(days=1)
            second = await scheduler.record_review(updated, True)
            assert second.interval_days == 3.0
        async with SqliteReviewScheduler(path, clock=clock) as reopened:
            stored = {i.concept: i for i in await reopened.items()}
            assert stored["vlookup"].repetitions == 2
            assert stored["vlookup"].due_at == clock.now + timedelta(days=3)
            # third correct uses the stored ease, not the default
            clock.now = stored["vlookup"].due_at
            third = await reopened.record_review(stored["vlookup"], True)
            assert third.interval_days == pytest.approx(3.0 * (DEFAULT_EASE + 0.2))
            wrong = await reopened.record_review(third, False)
            assert wrong.lapses == 1 and wrong.interval_days == LAPSE_INTERVAL_DAYS

    asyncio.run(scenario())


def test_scheduler_dedups_and_management(tmp_path):
    async def scenario():
        async with SqliteReviewScheduler(tmp_path / "r.sqlite3") as scheduler:
            a = item("VLOOKUP", "Where is  VLOOKUP?")
            await scheduler.add_review_items([a, item("vlookup", "where is vlookup?")])
            await scheduler.add_review_items([item("x", "   "), item("", "q")])
            items = await scheduler.items()
            assert len(items) == 1 and items[0].concept == "vlookup"
            await scheduler.add_review_items([item("layers")])
            await scheduler.delete(a.id)
            assert [i.concept for i in await scheduler.items()] == ["layers"]
            await scheduler.clear()
            assert await scheduler.items() == ()
            assert await scheduler.due_reviews(T0, 0) == ()

    asyncio.run(scenario())


def test_record_review_of_unknown_item_inserts_it():
    async def scenario():
        async with SqliteReviewScheduler(":memory:", clock=Clock()) as scheduler:
            updated = await scheduler.record_review(item("masks"), False)
            assert updated.lapses == 1
            assert [i.id for i in await scheduler.items()] == [updated.id]

    asyncio.run(scenario())


def test_closed_scheduler_and_naive_timestamps():
    async def scenario():
        scheduler = SqliteReviewScheduler(":memory:")
        with pytest.raises(ValueError):
            await scheduler.due_reviews(datetime(2026, 1, 1))
        await scheduler.close()
        with pytest.raises(RuntimeError):
            await scheduler.items()

    asyncio.run(scenario())


def test_coach_default_scheduler_is_in_memory():
    async def scenario():
        coach = EvidenceBasedCoach()
        await coach.add_review_items([item("vlookup")])
        due = await coach.due_reviews(T0)
        assert [d.concept for d in due] == ["vlookup"]

    asyncio.run(scenario())


# --- Interleaving ----------------------------------------------------------------


def test_similarity():
    assert similar("VLOOKUP", "INDEX/MATCH")
    assert similar("absolute references", "relative reference")
    assert similar("layers", "masks")
    assert similar("pivot table", "table styles")  # shared word
    assert not similar("vlookup", "layers")
    assert not similar("vlookup", "vlookup")
    assert not similar("the chart", "the layer")  # stop words don't count


def test_interleave_avoids_consecutive_same_concept_and_prefers_confusable():
    ordered = [
        item("vlookup", "q1"),
        item("vlookup", "q2"),
        item("layers", "q3"),
        item("index match", "q4"),
        item("vlookup", "q5"),
    ]
    result = [i.question for i in interleave(ordered)]
    assert result == ["q1", "q4", "q2", "q3", "q5"]
    concepts = [i.concept for i in interleave(ordered)]
    assert all(a != b for a, b in zip(concepts, concepts[1:], strict=False))


def test_interleave_falls_back_when_only_one_concept_left():
    result = interleave([item("a", "1"), item("a", "2"), item("b", "3")])
    assert [i.question for i in result] == ["1", "3", "2"]
    assert interleave([]) == []


def test_due_reviews_interleaves_and_limits():
    async def scenario():
        async with SqliteReviewScheduler(":memory:") as scheduler:
            await scheduler.add_review_items(
                [
                    item("vlookup", "q1", due=T0 - timedelta(days=3)),
                    item("vlookup", "q2", due=T0 - timedelta(days=2)),
                    item("index match", "q3", due=T0 - timedelta(days=1)),
                    item("layers", "q4", due=T0 - timedelta(hours=1)),
                    item("masks", "q5", due=T0 + timedelta(days=1)),  # not due
                ]
            )
            due = await scheduler.due_reviews(T0, limit=3)
            assert [d.question for d in due] == ["q1", "q3", "q2"]

    asyncio.run(scenario())


# --- Quiz generation -------------------------------------------------------------


def run(coro):
    return asyncio.run(coro)


def fake_model(reply, seen=None):
    async def call(system, user):
        if seen is not None:
            seen.append((system, user))
        return reply

    return call


def test_model_questions_are_parsed():
    reply = json.dumps(
        [
            {
                "concept": "VLOOKUP",
                "question": "What does the last VLOOKUP argument do?",
                "answer": "FALSE asks for an exact match.",
            },
            {
                "concept": "pivot table",
                "question": "Where do you insert a pivot table?",
                "answer": "Insert tab, then PivotTable.",
            },
        ]
    )
    seen = []
    items = run(
        generate_review_items(
            ["vlookup", "pivot table"],
            ["click Insert then PivotTable"],
            fake_model(f"```json\n{reply}\n```", seen),
            app="excel",
            now=T0,
        )
    )
    assert [i.concept for i in items] == ["vlookup", "pivot table"]
    assert items[0].answer == "FALSE asks for an exact match."
    assert all(i.due_at == T0 for i in items)
    system, user = seen[0]
    assert system == QUIZ_SYSTEM_PROMPT
    assert "vlookup, pivot table" in user and "excel" in user and "PivotTable" in user


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "sorry, I can't",
        "{not json",
        "[1, 2, 3]",
        '{"question": "x"}',
        '[{"question": 5, "answer": "a"}]',
        '[{"question": "", "answer": "a"}]',
        '[{"question": "Is VLOOKUP a function?", "answer": "yes"}]',
        '[{"question": "Which of the following is a lookup?", "answer": "VLOOKUP"}]',
        '[{"question": "What is it? (a) x (b) y", "answer": "x"}]',
        "[" * 5000 + "]" * 5000,
        None,
    ],
)
def test_malformed_model_output_falls_back_to_templates(reply):
    items = run(generate_review_items(["vlookup"], (), fake_model(reply), app="excel", now=T0))
    assert len(items) >= 2
    assert items[0].question == "Where do you find vlookup in excel?"
    assert items[0].answer == FALLBACK_ANSWER


def test_one_valid_model_question_is_topped_up_with_templates():
    reply = '[{"concept": "nope", "question": "What does VLOOKUP return?", "answer": "a value"}]'
    items = run(generate_review_items(["layers", "vlookup"], (), fake_model(reply), now=T0))
    assert len(items) == 3
    assert items[0].concept == "vlookup"  # unknown concept guessed from the question
    assert items[1].question == "Where do you find layers?"


def test_model_errors_and_timeouts_fall_back():
    async def broken(system, user):
        raise RuntimeError("offline")

    async def slow(system, user):
        await asyncio.sleep(5)
        return "[]"

    for call in (broken, slow):
        items = run(generate_review_items(["masks"], (), call, now=T0, timeout=0.05))
        assert [i.concept for i in items] == ["masks", "masks", "masks"]


def test_extra_and_duplicate_model_questions_are_trimmed():
    entry = {"concept": "masks", "question": "What does a mask hide?", "answer": "Pixels."}
    others = [
        {"concept": "masks", "question": f"What is mask use number {n}?", "answer": "x"}
        for n in range(5)
    ]
    parsed = parse_review_items(json.dumps([entry, entry, *others]), ["masks"], T0)
    assert len(parsed) == 6
    items = run(generate_review_items(["masks"], (), fake_model(json.dumps([entry, *others]))))
    assert len(items) == 3


def test_templates_without_model_use_notes_as_answers():
    notes = ["Click the Insert tab, then PivotTable.", "Type =VLOOKUP(A2, B:C, 2, FALSE)."]
    items = run(generate_review_items(["pivot table", "vlookup"], notes, None, app="Excel", now=T0))
    assert [i.question for i in items] == [
        "Where do you find pivot table in Excel?",
        "Where do you find vlookup in Excel?",
        "What is pivot table for, and when would you use it?",
    ]
    assert items[0].answer == "Click the Insert tab, then PivotTable."
    assert items[1].answer == "Type =VLOOKUP(A2, B:C, 2, FALSE)."
    assert all(i.due_at == T0 for i in items)


def test_single_concept_templates_and_count_bounds():
    one = run(generate_review_items(["layers"], "", None, count=1))
    assert len(one) == 2  # never fewer than two
    assert [i.question for i in one] == [
        "Where do you find layers?",
        "What is layers for, and when would you use it?",
    ]
    assert run(generate_review_items([], "notes", None)) == ()
    assert run(generate_review_items(["  "], "notes", None)) == ()
