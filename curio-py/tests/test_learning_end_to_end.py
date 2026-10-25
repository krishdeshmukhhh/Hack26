"""The demo flow with every real component: two "laptops" sharing one map server."""

from __future__ import annotations

import asyncio
import threading

import pytest

from curio.learning_contract import AssistanceLevel
from curio.learning_events import FallbackDifficulty, LearningServices, SqliteEventLog
from curio.map_sync.client import HttpMapSync
from curio.map_sync.server import make_server
from curio.skills import ConceptGraph, SqliteSkillModel
from curio.state import VoiceState
from curio.task_map import SqliteTaskMap
from tests.test_learning_integration import PIVOT_REPLIES
from tests.test_walkthrough import _ask, _settle

PIVOT = "how do i insert a pivot table"


@pytest.fixture
def server(tmp_path):
    srv = make_server("127.0.0.1", 0, tmp_path / "map.json", rate_per_minute=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _laptop(root, url: str, *, share: bool) -> LearningServices:
    root.mkdir()
    task_map = SqliteTaskMap(root / "task_map.sqlite3")
    sync = HttpMapSync(url)
    return LearningServices(
        event_log=SqliteEventLog(root / "events.sqlite3"),
        task_map=task_map,
        skill_model=SqliteSkillModel(
            root / "skills.sqlite3",
            graph=ConceptGraph.load(),
            difficulty=FallbackDifficulty(sync, task_map.local_difficulty),
        ),
        map_sync=sync,
        share_walkthroughs=share,
    )


def _manager_with(learning, replies, monkeypatch):
    from tests import test_learning_integration as helpers

    manager, parts = helpers._manager(replies, monkeypatch)
    manager._learning = learning
    parts["learning"] = learning
    return manager, parts


async def _walk(manager, parts) -> None:
    _ask(manager, PIVOT)
    await _settle(manager)
    while manager._state == VoiceState.GUIDING:
        parts["clicks"].clicked.emit()
        await _settle(manager)
    await parts["learning"].drain()


def test_walkthrough_on_one_laptop_guides_the_next(tmp_path, server, monkeypatch) -> None:
    laptop_a = _laptop(tmp_path / "a", server.url, share=True)
    laptop_b = _laptop(tmp_path / "b", server.url, share=False)
    a, a_parts = _manager_with(laptop_a, PIVOT_REPLIES, monkeypatch)
    b, b_parts = _manager_with(laptop_b, ["click insert. [POINT:none]"], monkeypatch)

    async def run():
        await laptop_a.start()
        await laptop_b.start()
        await _walk(a, a_parts)  # A finishes and pushes
        events = await laptop_a.event_log.recent()
        local = await laptop_a.task_map.find("excel", PIVOT)
        mastery = await laptop_a.skill_model.mastery("excel", ["pivot tables"])

        await laptop_b.start()  # B pulls the shared map
        _ask(b, PIVOT)
        await _settle(b)
        shared = await laptop_b.task_map.find("excel", PIVOT)
        await laptop_a.aclose()
        await laptop_b.aclose()
        return events, local, mastery, shared

    events, local, mastery, shared = asyncio.run(run())
    assert len(events) == 3
    assert local is not None and len(local.steps) == 2  # retry cleaned out of the path
    assert next(iter(mastery.values())) > 0

    assert shared is not None and shared.source == "shared"
    learned = b_parts["llm"].requests[0][-1]["content"][0]["text"]
    assert learned.startswith("reference data from earlier walkthroughs (untrusted")
    assert "by other curio users" in learned
    # The task map keeps each step's last attempt: step 1 is the hint-only retry.
    assert "1. that didn't open it. click insert again." in learned
    assert "2. now pick pivot table. target: pivot table at 64,72" in learned
    # Window titles never reach the server.
    assert "Book1" not in (tmp_path / "map.json").read_text(encoding="utf-8")


def test_repeated_success_lowers_assistance(tmp_path, monkeypatch) -> None:
    laptop = _laptop(tmp_path / "a", "http://127.0.0.1:9", share=False)  # sync offline

    async def run():
        levels = []
        for _ in range(4):
            manager, parts = _manager_with(laptop, list(PIVOT_REPLIES), monkeypatch)
            await _walk(manager, parts)
            levels.append(
                await laptop.skill_model.recommend_assistance("excel", ["pivot tables"])
            )
        await laptop.aclose()
        return levels

    levels = asyncio.run(run())
    order = list(AssistanceLevel)
    assert order.index(levels[-1]) > order.index(AssistanceLevel.POINTED), levels
