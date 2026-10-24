import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from curio.learning import AdaptiveBounds, LearningPolicy, RuleBasedLearningEngine
from curio.memory_contract import (
    ApprovalStatus,
    AutomaticLearningPolicy,
    ExplicitFeedback,
    MemoryRecord,
    MemorySettings,
    MemorySource,
    MemoryType,
)

ON = MemorySettings(enabled=True, automatic_learning=AutomaticLearningPolicy.PROPOSE)


def run(awaitable):
    return asyncio.run(awaitable)


def feedback(text):
    return ExplicitFeedback(text=text)


def pref(content="short", source=MemorySource.EXPLICIT_FEEDBACK):
    return MemoryRecord(
        type=MemoryType.PREFERENCE,
        content=content,
        source=source,
        preference_key="response.verbosity",
        approval_status=ApprovalStatus.APPROVED,
    )


@pytest.mark.parametrize(
    "text,key,value",
    [
        ("I prefer shorter explanations.", "response.verbosity", "short"),
        ("Stop interrupting me so often.", "interaction.frequency", "low"),
    ],
)
def test_explicit_preferences(text, key, value):
    records = run(RuleBasedLearningEngine().process_explicit_feedback(feedback(text), settings=ON))
    assert len(records) == 1
    assert (records[0].preference_key, records[0].content) == (key, value)
    assert records[0].approval_status == ApprovalStatus.PENDING
    assert records[0].confidence >= 0.9


def test_remember_project():
    (record,) = run(
        RuleBasedLearningEngine().process_explicit_feedback(
            feedback("Remember that I'm working on Curio."), settings=ON
        )
    )
    assert record.type == MemoryType.PROJECT
    assert "Curio" in record.content


@pytest.mark.parametrize(
    "text",
    [
        "Shorter please",
        "Maybe fewer details?",
        "For now I prefer shorter explanations",
        "This time, remember that I like short answers",
    ],
)
def test_ambiguous_and_temporary(text):
    assert (
        run(RuleBasedLearningEngine().process_explicit_feedback(feedback(text), settings=ON)) == ()
    )


def test_duplicates_contradictions_and_priorities():
    engine = RuleBasedLearningEngine()
    old = pref()
    assert run(engine.resolve_contradictions(old, [old], settings=ON)) is None
    candidate = pref("long", MemorySource.AUTOMATIC)
    assert run(engine.resolve_contradictions(candidate, [old], settings=ON)) is None
    resolution = run(
        engine.update_preferences(
            "response.verbosity", "long", feedback=feedback("longer"), existing=[old], settings=ON
        )
    )
    assert resolution.superseded_ids == (old.id,)
    assert resolution.proposed_memory.approval_status == ApprovalStatus.PENDING


def test_settings_override_feedback():
    engine = RuleBasedLearningEngine(explicit_preferences={"response.verbosity": "long"})
    assert (
        run(
            engine.process_explicit_feedback(feedback("I prefer shorter explanations"), settings=ON)
        )
        == ()
    )
    assert engine.adaptive_values([pref()]).verbosity == 1.0


def test_repetition_confidence_and_retry_deduplication():
    engine = RuleBasedLearningEngine()

    async def propose(turn):
        return await engine.propose_memories("shorter please", "", settings=ON, source_id=turn)

    assert run(propose("1")) == ()
    assert run(propose("1")) == ()
    assert run(propose("2")) == ()
    (record,) = run(propose("3"))
    assert record.source == MemorySource.AUTOMATIC
    assert record.confidence >= 0.8
    assert run(propose("4")) == ()


def test_forgetting_requires_target_and_never_deletes():
    engine = RuleBasedLearningEngine()
    old = pref()
    assert engine.propose_forgetting(feedback("Forget that preference"), [old], settings=ON) == ()
    request = replace(feedback("Forget that preference"), memory_id=old.id)
    assert engine.propose_forgetting(request, [old], settings=ON) == (old.id,)
    assert old.approval_status == ApprovalStatus.APPROVED


def test_disabled_and_automatic_off():
    engine = RuleBasedLearningEngine()
    off = MemorySettings()
    assert (
        run(engine.process_explicit_feedback(feedback("I prefer short answers"), settings=off))
        == ()
    )
    assert run(engine.propose_memories("shorter please", "", settings=off, source_id="1")) == ()
    assert run(engine.resolve_contradictions(pref(), [], settings=off)) is None
    assert engine.propose_forgetting(feedback("forget everything"), [pref()], settings=off) == ()
    assert (
        run(engine.propose_memories("shorter please", "", settings=MemorySettings(enabled=True)))
        == ()
    )


def test_bounded_adaptation_and_relevance():
    engine = RuleBasedLearningEngine(bounds=AdaptiveBounds(verbosity_min=0.3, verbosity_max=0.7))
    assert engine.adaptive_values([pref()]).verbosity == 0.3
    record = pref()
    assert engine.rank_relevance("short explanations", [record]) == (record,)
    assert (
        engine.rank_relevance(
            "short explanations", [replace(record, approval_status=ApprovalStatus.REJECTED)]
        )
        == ()
    )
    assert engine.rank_relevance("unrelated", [record]) == ()


def test_policy_validation_and_threshold():
    with pytest.raises(ValueError):
        LearningPolicy(confidence_threshold=1.1)
    with pytest.raises(ValueError):
        AdaptiveBounds(verbosity_min=0.9, verbosity_max=0.2)
    engine = RuleBasedLearningEngine(policy=LearningPolicy(confidence_threshold=1.0))
    assert (
        run(
            engine.process_explicit_feedback(feedback("I prefer shorter explanations"), settings=ON)
        )
        == ()
    )


def test_snapshot_deduplication():
    async def snapshot():
        return [pref()]

    engine = RuleBasedLearningEngine(snapshot_provider=snapshot)
    assert (
        run(
            engine.process_explicit_feedback(feedback("I prefer shorter explanations"), settings=ON)
        )
        == ()
    )


def test_different_preference_keys_are_independent():
    candidate = replace(pref(), preference_key="another.preference")
    result = run(RuleBasedLearningEngine().resolve_contradictions(candidate, [pref()], settings=ON))
    assert result is not None
    assert result.superseded_ids == ()


def test_corrections_and_obvious_negation():
    engine = RuleBasedLearningEngine()
    old = pref()
    resolution = run(engine.resolve_contradictions(pref("long"), [old], settings=ON))
    assert resolution.superseded_ids == (old.id,)
    assert old.content == "short"
    fact = MemoryRecord(
        type=MemoryType.FACT,
        content="I use Windows",
        source=MemorySource.USER,
        approval_status=ApprovalStatus.APPROVED,
    )
    corrected = replace(fact, id="new", content="I do not use Windows")
    # Detect only direct negation, not semantic guesses.
    direct = replace(fact, id="new", content="I not use Windows")
    result = run(engine.resolve_contradictions(direct, [fact], settings=ON))
    assert result.superseded_ids == (fact.id,)
    result = run(engine.resolve_contradictions(corrected, [fact], settings=ON))
    assert result.superseded_ids == (fact.id,)


def test_expiration_and_rank_order():
    now = datetime(2026, 10, 24, tzinfo=UTC)
    engine = RuleBasedLearningEngine(clock=lambda: now)
    expired = replace(pref(), expires_at=now)
    pending = replace(pref(), approval_status=ApprovalStatus.PENDING)
    inferred = pref(source=MemorySource.AUTOMATIC)
    explicit = pref()
    assert engine.rank_relevance("short", [expired, pending, inferred, explicit]) == (
        explicit,
        inferred,
    )
    assert run(engine.resolve_contradictions(pref(), [expired], settings=ON)) is not None
    (record,) = run(
        engine.process_explicit_feedback(
            feedback("Remember that I use Windows"), settings=replace(ON, default_expiration_days=7)
        )
    )
    assert record.expires_at == now + timedelta(days=7)


def test_approved_feedback_beats_newer_inference():
    explicit = pref()
    inferred = replace(
        pref("long", MemorySource.AUTOMATIC), updated_at=explicit.updated_at + timedelta(days=1)
    )
    assert RuleBasedLearningEngine().adaptive_values([inferred, explicit]).verbosity == 0.2
    pending = replace(pref("long"), approval_status=ApprovalStatus.PENDING)
    assert RuleBasedLearningEngine().adaptive_values([pending, explicit]).verbosity == 0.2


def test_optional_inference_waits_for_repetition_and_cannot_approve():
    calls = []

    async def infer(text):
        calls.append(text)
        return [pref("long")]

    engine = RuleBasedLearningEngine(inference=infer)
    for turn in ("a", "b"):
        assert run(engine.propose_memories("shorter please", "", settings=ON, source_id=turn)) == ()
    records = run(engine.propose_memories("shorter please", "", settings=ON, source_id="c"))
    assert calls == ["shorter please"]
    assert all(r.approval_status == ApprovalStatus.PENDING for r in records)
    assert all(r.source == MemorySource.AUTOMATIC for r in records)
    assert len(records) == 1


def test_forget_exact_and_reset_evidence():
    engine = RuleBasedLearningEngine()
    old = pref()
    assert engine.propose_forgetting(feedback("Forget short"), [old], settings=ON) == (old.id,)
    assert engine.propose_forgetting(feedback("Forget everything"), [old], settings=ON) == (old.id,)
    for turn in ("a", "b"):
        run(engine.propose_memories("shorter please", "", settings=ON, source_id=turn))
    engine.reset_signals()
    assert run(engine.propose_memories("shorter please", "", settings=ON, source_id="c")) == ()
