import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from curio.focus_contract import InterventionKind
from curio.focus_policy import AdaptiveFocusPolicy, PolicySettings, validate_rephrase
from curio.focus_policy.policy import CHOICES, RATIONALE
from curio.focus_policy.wording import (
    METACOGNITIVE_TEMPLATES,
    NEW_STYLE_NOTICE,
    PLAN_ONLY_TEMPLATES,
    TEMPLATES,
    MessageBook,
    all_templates,
    controlling_phrases,
)

FIELDS = {
    "goal": "the excel assignment",
    "cue": "i open youtube",
    "response": "i'll say back to it",
    "where": "step three",
    "next": "add the row fields",
}


@pytest.mark.parametrize("template", all_templates())
def test_no_template_uses_controlling_language(template):
    assert controlling_phrases(template) == []
    assert controlling_phrases(template.format(**FIELDS)) == []


@pytest.mark.parametrize(
    "text",
    [
        "Stop watching videos.",
        "You must get back to it",
        "you should close that",
        "you need to focus",
        "You have to finish",
        "Don't open youtube",
        "don’t do that",
        "do not switch apps",
        "get back to work",
        "you're wasting time",
        "distracted again?",
        "quit procrastinating",
        "be more productive",
        "no more youtube",
        "close it right now",
    ],
)
def test_controlling_phrases_are_caught(text):
    assert controlling_phrases(text)


@pytest.mark.parametrize("text", ["want to stretch?", "a stopwatch", "we could try again later"])
def test_harmless_words_pass(text):
    assert controlling_phrases(text) == []


def test_every_spoken_kind_has_several_variants():
    for kind in (
        InterventionKind.CHECK_IN,
        InterventionKind.PLAN_REMINDER,
        InterventionKind.RESUME,
        InterventionKind.BREAK_START,
        InterventionKind.BREAK_END,
        InterventionKind.REFLECTION,
    ):
        assert len(TEMPLATES[kind]) >= 2, kind
    for variants in (*PLAN_ONLY_TEMPLATES.values(), *METACOGNITIVE_TEMPLATES.values()):
        assert len(variants) >= 2


def test_check_ins_and_reminders_are_questions():
    for kind in (InterventionKind.CHECK_IN, InterventionKind.PLAN_REMINDER):
        for template in TEMPLATES[kind]:
            assert "?" in template


def test_check_ins_use_the_learners_goal():
    assert all("{goal}" in template for template in TEMPLATES[InterventionKind.CHECK_IN])
    assert all(
        "{cue}" in t and "{response}" in t for t in TEMPLATES[InterventionKind.PLAN_REMINDER]
    )


def test_breaks_are_framed_as_energy_not_output():
    for template in TEMPLATES[InterventionKind.BREAK_START]:
        assert "productiv" not in template and "output" not in template


def test_every_kind_the_policy_emits_has_choices_and_rationale():
    for kind in CHOICES:
        assert CHOICES[kind]
        assert RATIONALE[kind]


def test_message_book_rotates_per_kind():
    book = MessageBook()
    texts = [book.render(InterventionKind.REFLECTION, FIELDS) for _ in range(3)]
    assert texts[0] != texts[1]
    assert texts[2] == texts[0]
    assert all(not text.startswith(NEW_STYLE_NOTICE) for text in texts)  # not announced


# --- model output validation --------------------------------------------------------


def test_valid_rephrasing_is_cleaned():
    assert (
        validate_rephrase('  "still on the excel assignment?\n want a break?" ', original="x?")
        == "still on the excel assignment? want a break?"
    )


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "Stop watching youtube.",
        "You must get back to the excel assignment?",
        "**still on it?**",
        "still on it? see https://example.com",
        "still on it? " + "really " * 40,
        "x" * 200 + "?",
        "Get back to the excel assignment.",  # lost the question
    ],
)
def test_bad_rephrasings_are_rejected(reply):
    assert validate_rephrase(reply, original="still on the excel assignment?") is None


T0 = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)


def make_plan():
    from curio.focus_contract import FocusPlan

    return FocusPlan(goal="the excel assignment", duration=timedelta(minutes=50), started_at=T0)


def run_rephrase(model, **settings):
    policy = AdaptiveFocusPolicy(clock=lambda: T0, model=model, settings=PolicySettings(**settings))
    original = policy.start_session(make_plan())
    return original, asyncio.run(policy.rephrase(original))


def test_good_model_output_replaces_the_template():
    calls = []

    async def model(system, text):
        calls.append((system, text))
        return "so, for the excel assignment, where would you like to begin?"

    original, rephrased = run_rephrase(model)
    assert rephrased.message == "so, for the excel assignment, where would you like to begin?"
    assert rephrased.id == original.id and rephrased.choices == original.choices
    assert calls[0][1] == original.message
    assert "never give" in calls[0][0]


def test_controlling_model_output_falls_back_to_the_template():
    async def model(system, text):
        return "You must start with the formulas now?"

    original, rephrased = run_rephrase(model)
    assert rephrased is original


def test_failing_or_slow_model_falls_back():
    async def broken(system, text):
        raise RuntimeError("offline")

    async def slow(system, text):
        await asyncio.sleep(1)
        return "what first?"

    assert run_rephrase(broken)[1].message == run_rephrase(broken)[0].message
    original, rephrased = run_rephrase(slow, rephrase_timeout_seconds=0.01)
    assert rephrased is original


def test_no_model_means_templates_only():
    original, rephrased = run_rephrase(None)
    assert rephrased is original


def test_new_style_notice_survives_rephrasing():
    from curio.focus_contract import Intervention

    async def model(system, text):
        assert NEW_STYLE_NOTICE not in text
        return "how's it going with the assignment, want to keep at it?"

    policy = AdaptiveFocusPolicy(clock=lambda: T0, model=model)
    intervention = Intervention(
        kind=InterventionKind.CHECK_IN, message=NEW_STYLE_NOTICE + "still on it?"
    )
    rephrased = asyncio.run(policy.rephrase(intervention))
    assert rephrased.message.startswith(NEW_STYLE_NOTICE)
