"""Presenter: ambient vs spoken kinds, choices, expiry and pet reactions (section H)."""

from datetime import timedelta

import pytest

from curio.focus_contract import (
    FocusSignal,
    Intervention,
    InterventionKind,
    InterventionResponse,
    SignalKind,
)
from curio.focus_session.presenter import (
    ChoiceBubble,
    FocusPresenter,
    PetWidgetActions,
    match_spoken_choice,
    response_for_choice,
)
from curio.focus_session.rationale import SECTION_SUMMARIES

CHOICES = ("back to it", "take a break", "not a distraction")


class FakeSchedule:
    def __init__(self):
        self.pending = []

    def __call__(self, seconds, callback):
        entry = [seconds, callback, True]
        self.pending.append(entry)

        def cancel():
            entry[2] = False

        return cancel

    def fire(self):
        for entry in list(self.pending):
            if entry[2]:
                entry[2] = False
                entry[1]()


class FakePet:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name in {"look_at_learner", "happy", "nap", "stretch", "wake"}:
            return lambda: self.calls.append(name)
        raise AttributeError(name)


def _setup():
    spoken, responses = [], []
    schedule, pet = FakeSchedule(), FakePet()
    presenter = FocusPresenter(speak=spoken.append, pet=pet, schedule=schedule)
    presenter.bind(lambda i, r: responses.append((i, r)))
    return presenter, spoken, responses, schedule, pet


def _card(kind=InterventionKind.CHECK_IN, choices=CHOICES, **kw):
    return Intervention(kind=kind, message="still on the assignment?", choices=choices,
                        rationale="C", **kw)


def test_ambient_cue_is_animation_only():
    presenter, spoken, responses, schedule, pet = _setup()
    presenter.show(_card(InterventionKind.AMBIENT_CUE, choices=()))
    assert pet.calls == ["look_at_learner"] and spoken == []
    assert not presenter.bubble.isVisible() and presenter.current is None
    assert schedule.pending == [] and responses == []


def test_spoken_card_shows_choices_and_why_then_records_click():
    presenter, spoken, responses, schedule, _ = _setup()
    card = _card(expires_after=timedelta(seconds=45))
    presenter.show(card)
    assert spoken == [card.message]
    bubble = presenter.bubble
    assert bubble.isVisible()
    assert [b.text() for b in bubble.buttons] == list(CHOICES)
    assert schedule.pending[0][0] == 45
    assert not bubble.why.isVisible()
    bubble.toggle_why()
    assert bubble.why.isVisible() and bubble.why.text() == SECTION_SUMMARIES["C"]
    bubble.buttons[2].click()
    assert responses == [(card, InterventionResponse.FALSE_ALARM)]
    assert not bubble.isVisible() and presenter.current is None
    schedule.fire()  # cancelled timer must not record a second response
    assert len(responses) == 1


def test_expiry_records_ignored():
    presenter, _, responses, schedule, _ = _setup()
    card = _card()
    presenter.show(card)
    schedule.fire()
    assert responses == [(card, InterventionResponse.IGNORED)]
    assert not presenter.bubble.isVisible()


def test_replaced_card_is_ignored_and_stale_timer_is_harmless():
    presenter, _, responses, schedule, _ = _setup()
    first, second = _card(), _card(InterventionKind.PLAN_REMINDER)
    presenter.show(first)
    presenter.show(second)
    assert responses == [(first, InterventionResponse.IGNORED)]
    assert presenter.current is second
    schedule.fire()
    assert responses[-1] == (second, InterventionResponse.IGNORED)


def test_spoken_reply_selects_choice():
    presenter, _, responses, _, _ = _setup()
    presenter.show(_card())
    assert not presenter.handle_spoken("what is a pivot table")
    assert presenter.handle_spoken("uh, back to it I guess")
    assert responses[-1][1] == InterventionResponse.ACCEPTED
    assert not presenter.handle_spoken("back to it")  # nothing open now


def test_break_nap_stretch_and_happy_return():
    presenter, _, _, _, pet = _setup()
    presenter.show(_card(InterventionKind.BREAK_START, choices=("start break", "keep going")))
    presenter.choose("start break")
    assert pet.calls == ["nap"]
    presenter.signal(FocusSignal(kind=SignalKind.BREAK_OVER))
    presenter.show(_card(InterventionKind.BREAK_END, choices=("ready",)))
    presenter.signal(FocusSignal(kind=SignalKind.RETURNED))
    assert pet.calls == ["nap", "stretch", "stretch", "happy"]


def test_card_without_choices_gets_okay_and_clear_records_nothing():
    presenter, _, responses, _, pet = _setup()
    presenter.show(_card(InterventionKind.REFLECTION, choices=()))
    assert [b.text() for b in presenter.bubble.buttons] == ["okay"]
    presenter.clear()
    assert responses == [] and not presenter.bubble.isVisible()
    assert pet.calls[-1] == "wake"


@pytest.mark.parametrize(
    ("choice", "response"),
    [
        ("back to it", InterventionResponse.ACCEPTED),
        ("take a real break", InterventionResponse.ACCEPTED),
        ("start break", InterventionResponse.ACCEPTED),
        ("not a distraction", InterventionResponse.FALSE_ALARM),
        ("that wasn't a distraction", InterventionResponse.FALSE_ALARM),
        ("snooze 10 min", InterventionResponse.SNOOZED),
        ("not now", InterventionResponse.SNOOZED),
        ("keep going", InterventionResponse.DISMISSED),
    ],
)
def test_response_for_choice(choice, response):
    assert response_for_choice(choice) == response


def test_match_spoken_choice_prefers_longest_exact_phrase():
    assert match_spoken_choice("it's not a distraction", CHOICES) == "not a distraction"
    assert match_spoken_choice("break please", CHOICES) == "take a break"
    assert match_spoken_choice("", CHOICES) is None


def test_pet_widget_actions_degrade_without_clips():
    class Widget:
        catalog = None
        controller = None

    actions = PetWidgetActions(Widget())
    for name in ("look_at_learner", "happy", "nap", "stretch", "wake"):
        getattr(actions, name)()

    played = []

    class Controller:
        def _start_optional(self, action):
            played.append(action)

    class Pet:
        catalog = object()
        controller = Controller()

    actions = PetWidgetActions(Pet())
    actions.look_at_learner()
    actions.nap()
    assert actions._nap.isActive()
    actions.happy()
    assert not actions._nap.isActive()
    assert played == ["attentive", "settle", "jump"]


def test_choice_bubble_smoke():
    bubble = ChoiceBubble()
    bubble.show_intervention(_card(), None)
    bubble.show_intervention(_card(choices=("ready",)), None)
    assert [b.text() for b in bubble.buttons] == ["ready"]
    chosen = []
    bubble.chosen.connect(chosen.append)
    bubble.buttons[0].click()
    assert chosen == ["ready"]
    bubble.close()
