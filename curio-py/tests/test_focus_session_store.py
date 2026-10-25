"""SqliteSessionStore round trip and the timeline arithmetic behind summaries."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from curio.focus_contract import SessionSummary
from curio.focus_session import SessionTimeline, SqliteSessionStore, TimelineState
from tests.test_focus_session_fakes import T0


def _summary(index=0, **kw):
    start = T0 + timedelta(hours=index)
    values = dict(
        plan_id=f"plan-{index}", goal="excel assignment", started_at=start,
        ended_at=start + timedelta(minutes=25), on_goal_seconds=1200.5, off_goal_seconds=200.0,
        break_seconds=100.0, drift_count=2, interventions=3, false_alarms=1,
        concepts_practised=("vlookup", "index match"), reflection="phone got in the way",
        distractions=("youtube",),
    )
    values.update(kw)
    return SessionSummary(**values)


def test_round_trip_upsert_order_and_clear(tmp_path):
    async def scenario():
        path = tmp_path / "nested" / "focus.sqlite3"
        async with SqliteSessionStore(path) as store:
            first, second = _summary(0), _summary(1)
            await store.save_summary(first)
            await store.save_summary(second)
            await store.save_summary(replace(first, reflection="edited"))
            assert await store.summaries() == (second, replace(first, reflection="edited"))
            assert await store.summaries(limit=1) == (second,)
        async with SqliteSessionStore(path) as reopened:
            assert len(await reopened.summaries()) == 2
            await reopened.clear()
            assert await reopened.summaries() == ()

    asyncio.run(scenario())


def test_rejects_invalid_and_closed_use():
    async def scenario():
        store = SqliteSessionStore(":memory:")
        with pytest.raises(ValueError):
            await store.save_summary(_summary(plan_id=" "))
        with pytest.raises(ValueError):
            await store.save_summary(_summary(ended_at=T0 - timedelta(seconds=1)))
        await store.close()
        with pytest.raises(RuntimeError):
            await store.summaries()

    asyncio.run(scenario())


def test_refuses_unknown_database(tmp_path):
    path = tmp_path / "other.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE something (x)")
    conn.commit()
    conn.close()

    async def scenario():
        async with SqliteSessionStore(path) as store:
            with pytest.raises(OSError):
                await store.summaries()

    asyncio.run(scenario())


def _at(seconds):
    return T0 + timedelta(seconds=seconds)


def test_timeline_states_relabel_and_false_alarm():
    timeline = SessionTimeline(T0)
    timeline.observe(_at(30))
    timeline.set_state(TimelineState.ON_GOAL, _at(40))
    timeline.drift_started(_at(100), drift_seconds=50)
    timeline.set_state(TimelineState.ON_GOAL, _at(120))
    timeline.set_state(TimelineState.BREAK, _at(130))
    timeline.observe(_at(160))
    timeline.observe(_at(150))  # out of order: ignored
    totals = timeline.totals()
    assert totals == {
        TimelineState.ON_GOAL: 60.0,
        TimelineState.DRIFTING: 70.0,
        TimelineState.BREAK: 30.0,
    }
    assert timeline.total_seconds == 160
    assert [s.state for s in timeline.segments] == [
        TimelineState.ON_GOAL, TimelineState.DRIFTING, TimelineState.ON_GOAL, TimelineState.BREAK
    ]
    assert timeline.unmark_latest_drift()
    assert timeline.totals()[TimelineState.ON_GOAL] == 130
    assert len(timeline.segments) == 2
    assert not timeline.unmark_latest_drift()


def test_timeline_drift_never_reaches_before_start():
    timeline = SessionTimeline(T0)
    timeline.drift_started(_at(20), drift_seconds=500)
    assert timeline.totals()[TimelineState.DRIFTING] == 20
    assert timeline.segments[0].start == T0
