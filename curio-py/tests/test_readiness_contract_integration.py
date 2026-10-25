"""Shared provenance stays conservative across local stores and public wire data."""

import asyncio
import sqlite3
from dataclasses import replace

import pytest

from curio.learning_contract import (
    AssistanceLevel,
    StepEvent,
    StepOutcome,
    path_from_wire,
    summary_to_wire,
)
from curio.learning_events.recorder import PendingStep, WalkthroughRecorder
from curio.learning_events.store import SqliteEventLog
from curio.skills import ConceptGraph, SqliteSkillModel
from curio.skills.demo import fill
from curio.skills.widget import SkillsWidget
from curio.task_map import SqliteTaskMap


def test_shared_event_and_completion_origin_round_trip(tmp_path):
    event = StepEvent(
        walkthrough_id="w", app="calc", task="chart", step_index=1,
        instruction="Insert", assistance=AssistanceLevel.POINTED,
        outcome=StepOutcome.SUCCEEDED, evidence_basis="checked_success",
        evidence_ref="private-local-result:1",
    )
    assert event.independently_verified

    async def run():
        log = SqliteEventLog(tmp_path / "events.sqlite3")
        await log.append(event)
        assert await log.recent() == (event,)

    asyncio.run(run())
    recorder = WalkthroughRecorder(app="calc", task="chart")
    recorder.step_answered(PendingStep(
        step_index=1, instruction="Insert", assistance=AssistanceLevel.POINTED,
    ))
    settled, summary = recorder.finish(StepOutcome.SUCCEEDED, completed=True)
    assert type(settled) is StepEvent
    assert settled.evidence_basis == summary.completed_basis == "model_inferred"
    assert "evidence_ref" not in str(summary_to_wire(summary))
    assert summary_to_wire(replace(summary, synthetic=True))["synthetic"] is True
    assert not replace(event, synthetic=True).independently_verified
    with pytest.raises(ValueError):
        StepEvent(**{**vars(event), "evidence_ref": ""})


def test_remote_path_cannot_claim_local_verification():
    raw = {"v": 1, "app": "calc", "task": "chart", "steps": [],
           "verified_count": 3, "evidence_basis": "checked_success"}
    path = path_from_wire(raw)
    assert path.report_count == 3
    assert path.evidence_basis == "unknown"


def test_skills_demo_origin_survives_restart_and_migration(tmp_path):
    async def run():
        path = tmp_path / "skills.sqlite3"
        await fill(path)
        reopened = SqliteSkillModel(path, graph=ConceptGraph.load())
        assert await reopened.has_synthetic_data()
        assert all(e.synthetic for e in await reopened.evidence("layers"))
        exported = await reopened.export_data()
        assert all(e["synthetic"] for e in exported["evidence"])
        widget = SkillsWidget(reopened)
        try:
            await widget._fetch()
            assert not widget.synthetic_banner.isHidden()
            assert "SIMULATED" in widget.synthetic_banner.text()
        finally:
            widget.close()
        # Simulate a pre-provenance database; historical origin stays unknown.
        with sqlite3.connect(path) as conn:
            conn.execute("ALTER TABLE evidence DROP COLUMN synthetic")
            conn.execute("ALTER TABLE evidence DROP COLUMN evidence_basis")
            conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        legacy = SqliteSkillModel(path, graph=ConceptGraph.load())
        rows = await legacy.evidence("layers")
        assert rows and all(e.evidence_basis == "unknown" for e in rows)
        assert not await legacy.has_synthetic_data()

    asyncio.run(run())


def test_path_origin_persists_and_synthetic_does_not_reinforce(tmp_path):
    async def run():
        recorder = WalkthroughRecorder(app="calc", task="chart")
        recorder.step_answered(PendingStep(
            step_index=1, instruction="Insert", assistance=AssistanceLevel.POINTED,
        ))
        _, summary = recorder.finish(StepOutcome.SUCCEEDED, completed=True)
        path = tmp_path / "paths.sqlite3"
        async with SqliteTaskMap(path) as store:
            assert (await store.record(summary)).evidence_basis == "model_reported"
            assert await store.record(replace(summary, synthetic=True)) is None
        async with SqliteTaskMap(path) as store:
            found = await store.find("calc", "chart")
            assert found.report_count == 1
            assert found.evidence_basis == "model_reported"
        # Old paths keep counts/steps but cannot gain a provenance claim on migration.
        with sqlite3.connect(path) as conn:
            conn.execute("ALTER TABLE paths DROP COLUMN evidence_basis")
            conn.execute("PRAGMA user_version=1")
        async with SqliteTaskMap(path) as store:
            found = await store.find("calc", "chart")
            assert found.report_count == 1 and found.evidence_basis == "unknown"

    asyncio.run(run())
