"""Deterministic skill model checks: injected clock, tmp_path SQLite, no Qt."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from curio.learning_contract import (
    AssistanceLevel,
    SkillModel,
    StepEvent,
    StepOutcome,
    WalkthroughSummary,
)
from curio.skills import BktParams, ConceptGraph, SqliteSkillModel, assistance_for
from curio.skills.model import bkt_update, decayed, difficulty_factor

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
P = BktParams()


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class Difficulty:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def step_difficulty(self, app, task, step_index):
        self.calls.append((app, task, step_index))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def step(concepts, outcome=StepOutcome.SUCCEEDED, assistance=AssistanceLevel.NONE, index=1,
         app="excel", task="insert a pivot table", **kwargs):
    return StepEvent(
        walkthrough_id="w1", app=app, task=task, step_index=index,
        instruction=f"Step {index}", assistance=assistance, outcome=outcome,
        concepts=tuple(concepts), **kwargs,
    )


def summary(*steps, app="excel", task="insert a pivot table"):
    return WalkthroughSummary(
        walkthrough_id="w1", app=app, task=task, steps=tuple(steps), completed=True,
    )


@pytest.fixture
def graph():
    return ConceptGraph.load()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def model(tmp_path, graph, clock):
    return SqliteSkillModel(tmp_path / "skills.sqlite3", graph=graph, clock=clock)


def run(coro):
    return asyncio.run(coro)


async def mastery_of(model, concept, app="excel"):
    return (await model.mastery(app, [concept]))[concept]


def test_implements_protocol(model):
    for name in ("observe", "snapshot", "recommend_assistance", "prompt_context", "reset"):
        assert callable(getattr(model, name)), name
        assert hasattr(SkillModel, name)


def test_bkt_success_and_failure_math():
    up = bkt_update(0.2, True, 1.0, P)
    # posterior 0.18 / (0.18 + 0.16) then learn 15% of the remainder
    assert up == pytest.approx(0.18 / 0.34 + (1 - 0.18 / 0.34) * 0.15)
    down = bkt_update(0.6, False, 1.0, P)
    assert down < 0.6
    # one unassisted failure from the prior is enough to recommend doing it for them
    assert assistance_for(bkt_update(0.2, False, 1.0, P)) == AssistanceLevel.DID_IT
    assert bkt_update(0.4, True, 0.0, P) == 0.4


def test_observe_success_raises_and_failure_lowers(model):
    async def scenario():
        await model.observe(summary(step(["pivot tables"])))
        first = await mastery_of(model, "pivot tables")
        assert first == pytest.approx(bkt_update(0.2, True, 1.0, P))
        await model.observe(summary(step(["pivot tables"], StepOutcome.RETRIED, index=2)))
        assert await mastery_of(model, "pivot tables") < first
        await model.observe(summary(step(["pivot tables"], StepOutcome.TIMED_OUT, index=3)))
        [state] = await model.snapshot()
        assert state.concept == "pivot tables"
        assert state.attempts == 3
        assert state.apps == ("excel",)

    run(scenario())


def test_abandoned_and_did_it_are_ignored(model):
    async def scenario():
        await model.observe(summary(
            step(["pivot tables"], StepOutcome.ABANDONED),
            step(["charts"], assistance=AssistanceLevel.DID_IT, index=2),
            step([], index=3),
        ))
        assert await model.snapshot() == ()

    run(scenario())


def test_assistance_weighting_orders_gains(tmp_path, graph, clock):
    async def gain(level, name):
        m = SqliteSkillModel(tmp_path / f"{name}.sqlite3", graph=graph, clock=clock)
        await m.observe(summary(step(["charts"], assistance=level)))
        return await mastery_of(m, "charts")

    async def scenario():
        none = await gain(AssistanceLevel.NONE, "none")
        hinted = await gain(AssistanceLevel.HINTED, "hinted")
        pointed = await gain(AssistanceLevel.POINTED, "pointed")
        assert none > hinted > pointed > P.p_init
        assert hinted == pytest.approx(bkt_update(0.2, True, 0.7, P))
        assert pointed == pytest.approx(bkt_update(0.2, True, 0.35, P))

    run(scenario())


def test_difficulty_weighting(tmp_path, graph, clock):
    assert difficulty_factor(None, True) == 1.0
    assert difficulty_factor(1.0, True) == pytest.approx(1.5)
    assert difficulty_factor(1.0, False) == pytest.approx(0.5)
    assert difficulty_factor(0.0, True) == pytest.approx(0.5)

    async def after(d, outcome, name):
        provider = Difficulty(d)
        m = SqliteSkillModel(
            tmp_path / f"{name}.sqlite3", graph=graph, clock=clock, difficulty=provider
        )
        await m.observe(summary(step(["charts"], outcome, index=4)))
        assert provider.calls == [("excel", "insert a pivot table", 4)]
        return await mastery_of(m, "charts")

    async def scenario():
        hard_win = await after(0.9, StepOutcome.SUCCEEDED, "hw")
        easy_win = await after(0.1, StepOutcome.SUCCEEDED, "ew")
        hard_fail = await after(0.9, StepOutcome.RETRIED, "hf")
        easy_fail = await after(0.1, StepOutcome.RETRIED, "ef")
        assert hard_win > easy_win
        assert hard_fail > easy_fail  # failing a hard step costs less
        broken = await after(RuntimeError("offline"), StepOutcome.SUCCEEDED, "broken")
        assert broken == pytest.approx(bkt_update(0.2, True, 1.0, P))

    run(scenario())


def test_evidence_records_why(model):
    async def scenario():
        await model.observe(summary(
            step(["pivot tables"], assistance=AssistanceLevel.POINTED),
            step(["pivot tables"], assistance=AssistanceLevel.HINTED, index=2),
        ))
        evidence = await model.evidence("pivot tables")
        assert [e.step_index for e in evidence] == [2, 1]  # newest first
        assert evidence[1].mastery_before == pytest.approx(P.p_init)
        assert evidence[0].mastery_before == pytest.approx(evidence[1].mastery_after)
        assert evidence[1].weight == pytest.approx(0.35)
        assert evidence[0].task == "insert a pivot table"

    run(scenario())


def test_observing_same_steps_twice_is_idempotent(model):
    async def scenario():
        s = summary(step(["pivot tables"]))
        await model.observe(s)
        once = await model.snapshot()
        await model.observe(s)
        assert await model.snapshot() == once

    run(scenario())


def test_decay_toward_prior_on_read(model, clock):
    assert decayed(0.8, T0, T0 + timedelta(days=14)) == pytest.approx(0.2 + 0.6 * 0.5)
    assert decayed(0.8, None, T0) == 0.8

    async def scenario():
        for i in range(4):
            await model.observe(summary(step(["pivot tables"], index=i + 1)))
        fresh = await mastery_of(model, "pivot tables")
        clock.advance(days=14)
        half = await mastery_of(model, "pivot tables")
        assert half == pytest.approx(P.p_init + (fresh - P.p_init) / 2)
        [state] = await model.snapshot()
        assert state.mastery == pytest.approx(half)
        assert state.last_practiced == T0
        # practicing again starts from the decayed value
        await model.observe(summary(step(["pivot tables"], index=9)))
        assert await mastery_of(model, "pivot tables") == pytest.approx(
            bkt_update(half, True, 1.0, P)
        )

    run(scenario())


def test_canonical_names_and_cross_app_transfer(model):
    async def scenario():
        for i in range(5):
            await model.observe(summary(step(["layers"], index=i + 1, app="photoshop"),
                                        app="Adobe Photoshop 2024", task="add a layer"))
        known = await mastery_of(model, "layers", "photoshop")
        assert known > 0.9
        figma = await model.mastery("figma", ["frames"])
        assert set(figma) == {"layers"}
        assert P.p_init < figma["layers"] < known
        assert figma["layers"] == pytest.approx(P.p_init + 0.75 * (known - P.p_init))
        context = await model.prompt_context("figma", ["frames"])
        assert context == (
            "The user knows layers well from photoshop; in figma the same idea is frames."
        )
        [state] = await model.snapshot()
        assert state.apps == ("photoshop",)

    run(scenario())


def test_related_concepts_borrow_at_partial_strength(model):
    async def scenario():
        for i in range(5):
            await model.observe(summary(step(["vlookup"], index=i + 1)))
        known = await mastery_of(model, "vlookup")
        borrowed = await mastery_of(model, "xlookup")
        assert borrowed == pytest.approx(P.p_init + 0.8 * (known - P.p_init))
        assert await mastery_of(model, "keyframes") == pytest.approx(P.p_init)
        context = await model.prompt_context("excel", ["xlookup"])
        assert context == "The user knows vlookup well, which is closely related to xlookup."
        # first real evidence starts from the borrowed value
        await model.observe(summary(step(["xlookup"], index=9)))
        [e] = await model.evidence("xlookup")
        assert e.mastery_before == pytest.approx(borrowed)

    run(scenario())


def test_advice_bands():
    assert assistance_for(0.1) == AssistanceLevel.DID_IT
    assert assistance_for(0.15) == AssistanceLevel.POINTED
    assert assistance_for(0.44) == AssistanceLevel.POINTED
    assert assistance_for(0.45) == AssistanceLevel.HINTED
    assert assistance_for(0.79) == AssistanceLevel.HINTED
    assert assistance_for(0.8) == AssistanceLevel.NONE


def test_recommend_uses_weakest_concept(model):
    async def scenario():
        assert await model.recommend_assistance("excel", []) == AssistanceLevel.POINTED
        assert await model.recommend_assistance("excel", ["charts"]) == AssistanceLevel.POINTED
        for i in range(5):
            await model.observe(summary(step(["charts"], index=i + 1)))
        assert await model.recommend_assistance("excel", ["charts"]) == AssistanceLevel.NONE
        for i in range(3):
            await model.observe(summary(step(["sort and filter"], StepOutcome.RETRIED,
                                             index=10 + i)))
        assert await model.recommend_assistance(
            "excel", ["charts", "sort and filter"]
        ) == AssistanceLevel.DID_IT

    run(scenario())


def test_prompt_context_comfortable_and_learning(model):
    async def scenario():
        assert await model.prompt_context("excel", ["charts"]) is None
        assert await model.prompt_context("excel", []) is None
        for i in range(5):
            await model.observe(summary(step(["charts"], index=i + 1)))
        await model.observe(summary(step(["pivot tables"], StepOutcome.RETRIED, index=9)))
        text = await model.prompt_context("excel", ["charts", "pivot tables", "vlookup"])
        assert text == (
            "The user is already comfortable with charts in excel; keep it brief. "
            "The user is still learning pivot tables in excel; explain each step."
        )

    run(scenario())


def test_reset_concept_reset_all_and_listeners(model):
    async def scenario():
        calls = []
        unsubscribe = model.subscribe(lambda: calls.append(True))
        await model.observe(summary(step(["charts", "pivot tables"])))
        assert len(calls) == 1
        assert await model.reset_concept("charts")
        assert not await model.reset_concept("charts")
        assert [s.concept for s in await model.snapshot()] == ["pivot tables"]
        assert await model.evidence("charts") == ()
        await model.reset()
        assert await model.snapshot() == ()
        assert await model.evidence("pivot tables") == ()
        unsubscribe()
        await model.observe(summary(step(["charts"], index=2)))
        assert len(calls) == 4

    run(scenario())


def test_export_data_is_json(model, tmp_path):
    async def scenario():
        await model.observe(summary(step(["charts"], assistance=AssistanceLevel.HINTED)))
        data = await model.export_data()
        text = json.dumps(data)
        assert data["format"] == "curio-skills"
        assert data["skills"][0]["apps"] == ["excel"]
        assert data["evidence"][0]["assistance"] == "hinted"
        assert data["params"]["assistance_weights"]["pointed"] == 0.35
        assert "mastery_now" in text

    run(scenario())


def test_persists_across_instances(tmp_path, graph, clock):
    async def scenario():
        path = tmp_path / "nested" / "skills.sqlite3"
        await SqliteSkillModel(path, graph=graph, clock=clock).observe(
            summary(step(["charts"]))
        )
        again = SqliteSkillModel(path, graph=graph, clock=clock)
        [state] = await again.snapshot()
        assert state.concept == "charts" and state.attempts == 1

    run(scenario())
