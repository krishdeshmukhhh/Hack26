"""Fill a skill model with a believable history for the demo.

    python -m curio.skills.demo --path demo-skills.sqlite3 [--reset] [--show]

The user is strong with photoshop layers, middling with masks, learning excel
pivot tables, and has never opened figma, so asking about figma frames shows
transfer from photoshop layers. ``--show`` opens the skills window.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from curio.learning_contract import (
    AssistanceLevel,
    StepEvent,
    StepOutcome,
    WalkthroughSummary,
)
from curio.skills.concepts import ConceptGraph
from curio.skills.model import SqliteSkillModel

A = AssistanceLevel
O = StepOutcome  # noqa: E741

# (days ago, app, task, [(instruction, concepts, assistance, outcome), ...])
HISTORY: tuple[tuple[int, str, str, tuple[tuple[str, tuple[str, ...], A, O], ...]], ...] = (
    (38, "photoshop", "add a new layer", (
        ("Open the Layers panel", ("layers",), A.POINTED, O.SUCCEEDED),
        ("Click the new layer button", ("layers",), A.POINTED, O.RETRIED),
        ("Click the new layer button at the bottom", ("layers",), A.POINTED, O.SUCCEEDED),
    )),
    (31, "photoshop", "group layers", (
        ("Select both layers", ("layers",), A.HINTED, O.SUCCEEDED),
        ("Press Ctrl+G", ("layer groups", "keyboard shortcuts"), A.POINTED, O.SUCCEEDED),
    )),
    (24, "photoshop", "add a layer mask", (
        ("Select the photo layer", ("layers",), A.NONE, O.SUCCEEDED),
        ("Click Add layer mask", ("masks",), A.POINTED, O.SUCCEEDED),
        ("Paint black to hide", ("masks",), A.POINTED, O.RETRIED),
        ("Paint with black on the mask", ("masks",), A.POINTED, O.SUCCEEDED),
    )),
    (17, "photoshop", "change the blend mode", (
        ("Select the texture layer", ("layers",), A.NONE, O.SUCCEEDED),
        ("Open the blend mode menu", ("blend modes",), A.HINTED, O.SUCCEEDED),
        ("Choose Multiply", ("blend modes",), A.HINTED, O.SUCCEEDED),
    )),
    (9, "photoshop", "add an adjustment layer", (
        ("Reorder the layers", ("layers",), A.NONE, O.SUCCEEDED),
        ("Add a Curves adjustment", ("adjustment layers",), A.HINTED, O.SUCCEEDED),
        ("Clip it to the layer below", ("masks", "layers"), A.HINTED, O.SUCCEEDED),
    )),
    (4, "photoshop", "duplicate a layer", (
        ("Right-click the layer", ("layers",), A.NONE, O.SUCCEEDED),
        ("Choose Duplicate Layer", ("layers",), A.NONE, O.SUCCEEDED),
    )),
    (12, "excel", "use vlookup", (
        ("Click the empty cell", ("cell references",), A.HINTED, O.SUCCEEDED),
        ("Type =VLOOKUP(", ("vlookup", "formulas"), A.POINTED, O.SUCCEEDED),
        ("Select the lookup range", ("vlookup", "cell references"), A.POINTED, O.RETRIED),
        ("Select the whole table", ("vlookup", "cell references"), A.POINTED, O.SUCCEEDED),
    )),
    (2, "excel", "insert a pivot table", (
        ("Click Insert", ("pivot tables",), A.POINTED, O.SUCCEEDED),
        ("Click PivotTable", ("pivot tables",), A.POINTED, O.TIMED_OUT),
        ("Click PivotTable on the left of the ribbon", ("pivot tables",), A.POINTED, O.SUCCEEDED),
    )),
)


async def fill(path: Path, *, reset: bool = False, now: datetime | None = None) -> SqliteSkillModel:
    now = now or datetime.now(UTC)
    current = [now]
    model = SqliteSkillModel(path, graph=ConceptGraph.load(), clock=lambda: current[0])
    if reset:
        await model.reset()
    for n, (days_ago, app, task, steps) in enumerate(sorted(HISTORY, key=lambda h: -h[0])):
        current[0] = now - timedelta(days=days_ago)
        walkthrough_id = f"demo-{n}"
        events = tuple(
            StepEvent(
                walkthrough_id=walkthrough_id, app=app, task=task, step_index=i,
                instruction=text, assistance=assistance, outcome=outcome, concepts=concepts,
                id=f"{walkthrough_id}-{i}", occurred_at=current[0],
                synthetic=True,
            )
            for i, (text, concepts, assistance, outcome) in enumerate(steps, start=1)
        )
        await model.observe(WalkthroughSummary(
            walkthrough_id=walkthrough_id, app=app, task=task, steps=events,
            completed=True, finished_at=current[0], synthetic=True,
        ))
    current[0] = now
    return model


async def report(model: SqliteSkillModel) -> None:
    print(f"SIMULATED demo history — not observed user learning. Skill model: {model.path}")
    for state in await model.snapshot():
        bar = "#" * round(state.mastery * 20)
        print(f"  {state.concept:<20} {bar:<20} {state.mastery:4.0%}  "
              f"{state.attempts:>2} tries  {', '.join(state.apps)}")
    for app, concepts in (("figma", ["frames"]), ("excel", ["pivot tables"]),
                          ("excel", ["xlookup"]), ("photoshop", ["layers"])):
        advice = await model.recommend_assistance(app, concepts)
        context = await model.prompt_context(app, concepts)
        print(f"\n{app} / {', '.join(concepts)}: {advice.value}")
        if context:
            print(f"  prompt: {context}")


def _show(model: SqliteSkillModel) -> int:
    import qasync
    from PySide6.QtWidgets import QApplication

    from curio.skills.widget import SkillsWidget

    app = QApplication.instance() or QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    widget = SkillsWidget(model)
    widget.show()
    closed = asyncio.Event()
    app.lastWindowClosed.connect(closed.set)
    with loop:
        loop.run_until_complete(closed.wait())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--path", type=Path, default=Path("demo-skills.sqlite3"),
        help="separate demo database to fill (default: demo-skills.sqlite3)",
    )
    parser.add_argument("--reset", action="store_true", help="clear the model first")
    parser.add_argument("--show", action="store_true", help="open the skills window afterwards")
    args = parser.parse_args(argv)
    model = asyncio.run(fill(args.path, reset=args.reset))
    asyncio.run(report(model))
    return _show(model) if args.show else 0


if __name__ == "__main__":
    raise SystemExit(main())
