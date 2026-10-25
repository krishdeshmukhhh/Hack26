"""Evidence must retain its origin across recording, persistence and sharing."""
import asyncio
import random
import sqlite3
import threading

import httpx
import pytest

from curio.learning_contract import AssistanceLevel, StepOutcome, summary_to_wire
from curio.learning_events.evidence import EvidenceStepEvent
from curio.learning_events.recorder import PendingStep, WalkthroughRecorder
from curio.learning_events.store import SqliteEventLog
from curio.map_sync.seed import build
from curio.map_sync.server import (
    MapStore,
    aggregate_paths,
    aggregate_stats,
    make_server,
    validate_summary,
)
from curio.task_map.store import SqliteTaskMap


def test_progress_is_inferred_and_persists(tmp_path):
    recorder = WalkthroughRecorder(app="excel", task="chart")
    for index in (1, 2):
        event = recorder.step_answered(PendingStep(
            step_index=index, instruction="Insert", assistance=AssistanceLevel.NONE,
        ))
    assert event.evidence_basis == "model_inferred"
    assert not event.independently_verified
    log = SqliteEventLog(tmp_path / "events.sqlite3")

    async def run():
        await log.append(event)
        restored, = await log.recent()
        assert restored.evidence_basis == "model_inferred"
        assert not restored.independently_verified
    asyncio.run(run())


def test_checked_results_need_reference_and_matching_outcome():
    values = dict(
        walkthrough_id="w", app="excel", task="chart", step_index=1,
        instruction="Insert", assistance=AssistanceLevel.NONE,
        outcome=StepOutcome.SUCCEEDED, evidence_basis="checked_success",
    )
    with pytest.raises(ValueError):
        EvidenceStepEvent(**values)
    event = EvidenceStepEvent(**values, evidence_ref="verifier-result:1")
    assert event.independently_verified
    with pytest.raises(ValueError):
        EvidenceStepEvent(**{**values, "outcome": StepOutcome.RETRIED}, evidence_ref="result:2")


def test_v1_event_migration_preserves_unknown_origin(tmp_path):
    path = tmp_path / "v1.sqlite3"
    log = SqliteEventLog(path)
    event = EvidenceStepEvent(
        walkthrough_id="w", app="excel", task="chart", step_index=1,
        instruction="Insert", assistance=AssistanceLevel.NONE,
        outcome=StepOutcome.SUCCEEDED,
    )
    asyncio.run(log.append(event))
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE step_events DROP COLUMN evidence_basis")
        conn.execute("ALTER TABLE step_events DROP COLUMN evidence_ref")
        conn.execute("ALTER TABLE step_events DROP COLUMN synthetic")
        conn.execute("PRAGMA user_version = 1")
    restored, = asyncio.run(log.recent())
    assert restored.id == event.id
    assert getattr(restored, "evidence_basis", "unknown") == "unknown"
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_seed_records_visible_as_demo_but_excluded_from_sync(tmp_path):
    server = make_server("127.0.0.1", 0, tmp_path / "map.json", rate_per_minute=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        from curio.map_sync.seed import post_all
        posted = post_all(url, build(1, random.Random(7)))
        with httpx.Client(base_url=url) as client:
            assert client.get("/v1/paths").json()["paths"] == []
            assert client.get("/v1/stats").json()["walkthroughs"] == 0
            demo = client.get("/v1/stats?include_synthetic=1").json()
            assert demo["provenance"]["synthetic"] == posted
            assert demo["walkthroughs"] == posted
            assert "synthetic demo records" in client.get("/").text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_user_confirmation_is_not_independent():
    recorder = WalkthroughRecorder(app="excel", task="chart")
    recorder.step_answered(PendingStep(
        step_index=1, instruction="Insert", assistance=AssistanceLevel.NONE,
    ))
    event, _ = recorder.finish(
        StepOutcome.SUCCEEDED, completed=True, evidence_basis="user_confirmed",
    )
    assert event.evidence_basis == "user_confirmed"
    assert not event.independently_verified


def test_synthetic_and_legacy_map_provenance_survives_reload(tmp_path):
    wire = summary_to_wire(build(1, random.Random(7))[0])
    legacy = validate_summary(wire)
    synthetic = validate_summary({**wire, "synthetic": True})
    store = MapStore(tmp_path / "map.json")
    store.add(legacy)
    store.add(synthetic)
    records = MapStore(tmp_path / "map.json").records()
    assert aggregate_stats(records)["provenance"] == {"synthetic": 1, "unknown": 1}
    assert all(p["evidence_basis"] == "model_reported" for p in aggregate_paths(records))


def test_completion_cannot_override_later_failure(tmp_path):
    recorder = WalkthroughRecorder(app="excel", task="chart")
    for index in (1, 2, 1):
        recorder.step_answered(PendingStep(
            step_index=index, instruction="Insert", assistance=AssistanceLevel.NONE,
        ))
    _, summary = recorder.finish(
        StepOutcome.RETRIED, completed=True,
        evidence_basis="checked_failure", evidence_ref="local-result:1",
    )

    async def run():
        async with SqliteTaskMap(tmp_path / "map.sqlite3") as store:
            assert await store.record(summary) is None
            assert await store.paths() == ()
    asyncio.run(run())
