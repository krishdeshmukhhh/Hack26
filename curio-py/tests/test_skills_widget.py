"""Offscreen skills window checks against a real model on tmp_path."""

import asyncio
import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from curio.learning_contract import (
    AssistanceLevel,
    SkillState,
    StepEvent,
    StepOutcome,
    WalkthroughSummary,
)
from curio.skills import ConceptGraph, SqliteSkillModel
from curio.skills.widget import CONCEPT_ROLE, MASTERY_ROLE, SkillsWidget

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def summary(app, concept, index, outcome=StepOutcome.SUCCEEDED, assistance=AssistanceLevel.NONE):
    event = StepEvent(
        walkthrough_id=f"w{index}", app=app, task="do the thing", step_index=index,
        instruction=f"Click thing {index}", assistance=assistance, outcome=outcome,
        concepts=(concept,),
    )
    return WalkthroughSummary(
        walkthrough_id=f"w{index}", app=app, task="do the thing", steps=(event,), completed=True,
    )


async def settle(widget):
    while widget._tasks:
        await asyncio.gather(*tuple(widget._tasks), return_exceptions=True)
        await asyncio.sleep(0)


def concept_items(widget):
    items = []
    for i in range(widget.tree.topLevelItemCount()):
        group = widget.tree.topLevelItem(i)
        for j in range(group.childCount()):
            items.append((group.text(0), group.child(j)))
    return items


def make_model(tmp_path):
    return SqliteSkillModel(
        tmp_path / "skills.sqlite3", graph=ConceptGraph.load(), clock=lambda: NOW
    )


def test_groups_bars_evidence_and_live_refresh(app, tmp_path):
    async def scenario():
        model = make_model(tmp_path)
        for i in range(3):
            await model.observe(summary("photoshop", "layers", i + 1))
        await model.observe(summary("figma", "frames", 10, assistance=AssistanceLevel.POINTED))
        widget = SkillsWidget(model, clock=lambda: NOW)
        assert widget.tree.headerItem().text(1) == "Estimated mastery"
        refreshed = []
        widget.refreshed.connect(lambda: refreshed.append(True))
        widget.show()
        await settle(widget)
        items = concept_items(widget)
        assert [(g, i.text(0)) for g, i in items] == [("Figma", "Frames"), ("Photoshop", "Layers")]
        figma_item = items[0][1]
        assert figma_item.data(0, CONCEPT_ROLE) == "layers"
        assert 0 < figma_item.data(1, MASTERY_ROLE) < 1
        assert figma_item.text(2) == "4" and figma_item.text(3) == "Today"
        assert widget.summary.text() == "1 skill · 2 apps"
        assert refreshed

        widget.tree.setCurrentItem(figma_item)
        await settle(widget)
        assert widget.concept_title.text().startswith("Layers")
        assert "frames" in widget.concept_title.text()
        assert widget.mastery_label.text().endswith("%")
        assert widget.evidence_list.count() == 4
        assert "with pointing" in widget.evidence_list.item(0).text()
        assert "Model reported progress" in widget.evidence_list.item(0).text()
        assert "Helps with:" in widget.related_label.text()

        # observing a walkthrough refreshes the open window
        await model.observe(summary("excel", "pivot tables", 20, StepOutcome.RETRIED))
        await settle(widget)
        assert any(i.text(0) == "Pivot tables" for _, i in concept_items(widget))
        assert widget._selected == "layers"  # selection kept across refresh
        assert not widget.grab().isNull()
        widget.close()
        assert model._listeners == []

    asyncio.run(scenario())


def test_reset_concept_reset_all_and_export(app, tmp_path, monkeypatch):
    async def scenario():
        model = make_model(tmp_path)
        await model.observe(summary("excel", "charts", 1))
        await model.observe(summary("excel", "pivot tables", 2))
        widget = SkillsWidget(model, clock=lambda: NOW)
        widget.refresh()
        await settle(widget)
        widget.tree.setCurrentItem(concept_items(widget)[0][1])
        await settle(widget)
        selected = widget._selected
        monkeypatch.setattr(widget, "_confirm", lambda *args: False)
        widget.reset_selected()
        widget.reset_all()
        await settle(widget)
        assert len(await model.snapshot()) == 2
        monkeypatch.setattr(widget, "_confirm", lambda *args: True)
        widget.reset_selected()
        await settle(widget)
        assert [s.concept for s in await model.snapshot()] != [] and selected not in {
            s.concept for s in await model.snapshot()
        }
        assert len(concept_items(widget)) == 1

        target = tmp_path / "export.json"
        widget.export_to(target)
        await settle(widget)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["format"] == "curio-skills" and len(data["skills"]) == 1
        assert "Exported 1" in widget.status.text()

        widget.reset_all()
        await settle(widget)
        assert await model.snapshot() == ()
        assert widget.tree.topLevelItemCount() == 0
        assert "No skills yet" in widget.concept_meta.text()
        widget.close()

    asyncio.run(scenario())


def test_plain_protocol_model_and_failures(app, tmp_path):
    async def scenario():
        class PlainModel:  # only the SkillModel protocol, no extras
            observe = AsyncMock()
            snapshot = AsyncMock()
            recommend_assistance = AsyncMock()
            prompt_context = AsyncMock()
            reset = AsyncMock()

        model = PlainModel()
        model.snapshot.return_value = (
            SkillState(concept="charts", mastery=0.9, attempts=3, last_practiced=NOW,
                       apps=("excel",)),
        )
        widget = SkillsWidget(model, clock=lambda: NOW)
        assert widget.reset_concept_button.isHidden()
        widget.refresh()
        await settle(widget)
        widget.tree.setCurrentItem(concept_items(widget)[0][1])
        assert "doesn't keep per-step evidence" in widget.evidence_list.item(0).text()
        widget.export_to(tmp_path / "plain.json")
        await settle(widget)
        assert json.loads((tmp_path / "plain.json").read_text())["skills"][0]["mastery"] == 0.9
        model.snapshot.side_effect = OSError("disk")
        widget.refresh()
        await settle(widget)
        assert "failed" in widget.status.text()
        assert widget.refresh_button.isEnabled()
        widget.close()

    asyncio.run(scenario())


def test_without_event_loop_reports_error(app, tmp_path):
    widget = SkillsWidget(make_model(tmp_path))
    results = []
    widget.operation_finished.connect(lambda *a: results.append(a))
    widget.refresh()
    assert results == [("Load skills", False)]
    widget.close()
