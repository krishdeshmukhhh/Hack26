"""Post realistic fake walkthroughs to a map server for the demo.

    python -m curio.map_sync.seed --url http://127.0.0.1:8765 --users 40

Each task has one clearly hard step. "turn on dark mode" first gets a batch
of walkthroughs on the old Settings layout, then on the new one, so the
dashboard and ``/v1/paths`` show the newer path overtaking the stale one.
"""

from __future__ import annotations

import argparse
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from curio.learning_contract import (
    AssistanceLevel,
    ElementRef,
    StepEvent,
    StepOutcome,
    WalkthroughSummary,
    summary_to_wire,
)


@dataclass(frozen=True)
class _Step:
    instruction: str
    label: str
    x: float
    y: float
    stuck: float  # chance a user gets stuck here
    concepts: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Task:
    app: str
    task: str
    steps: tuple[_Step, ...]
    app_version: str = ""


PIVOT = _Task(
    app="excel",
    task="insert a pivot table",
    app_version="16.0",
    steps=(
        _Step("Click any cell inside your data.", "data range", 0.32, 0.41, 0.05, ("cell ranges",)),
        _Step("Open the Insert tab on the ribbon.", "Insert", 0.11, 0.06, 0.08, ("ribbon",)),
        _Step(
            "Click PivotTable on the far left.", "PivotTable", 0.04, 0.12, 0.12, ("pivot tables",)
        ),
        _Step("Press OK to put it on a new sheet.", "OK", 0.58, 0.71, 0.06, ("pivot tables",)),
        _Step(
            "Drag a field into Rows in the PivotTable Fields pane.",
            "pivot fields",
            0.88,
            0.62,
            0.62,
            ("pivot tables", "drag and drop"),
        ),
    ),
)

_DARK_MODE_START = (
    _Step("Open Settings from the Start menu.", "Settings", 0.42, 0.55, 0.04, ("start menu",)),
    _Step("Choose Personalization.", "Personalization", 0.09, 0.38, 0.10, ("settings navigation",)),
    _Step("Open Colors.", "Colors", 0.45, 0.33, 0.12, ("settings navigation",)),
)
DARK_MODE_OLD = _Task(
    app="settings",
    task="turn on dark mode",
    app_version="10.0.19045",
    steps=(
        *_DARK_MODE_START,
        _Step(
            "Under Choose your default app mode, pick Dark.",
            "Choose your default app mode",
            0.47,
            0.58,
            0.35,
            ("dark mode",),
        ),
    ),
)
DARK_MODE_NEW = _Task(
    app="settings",
    task="turn on dark mode",
    app_version="10.0.22631",
    steps=(
        *_DARK_MODE_START,
        _Step(
            "Open the Choose your mode dropdown and pick Dark.",
            "Choose your mode",
            0.78,
            0.29,
            0.18,
            ("dark mode",),
        ),
    ),
)

BROWSER = _Task(
    app="settings",
    task="change default browser",
    app_version="10.0.22631",
    steps=(
        _Step("Open Settings.", "Settings", 0.42, 0.55, 0.04, ("start menu",)),
        _Step("Click Apps in the sidebar.", "Apps", 0.08, 0.41, 0.07, ("settings navigation",)),
        _Step("Open Default apps.", "Default apps", 0.46, 0.35, 0.15, ("default apps",)),
        _Step(
            "Search for your browser in the app list and open it.",
            "Set defaults for applications",
            0.5,
            0.47,
            0.36,
            ("default apps", "search"),
        ),
        _Step("Click Set default at the top.", "Set default", 0.82, 0.22, 0.14, ("default apps",)),
    ),
)

CLEAR_DATA = _Task(
    app="google chrome",
    task="clear browsing data",
    app_version="129",
    steps=(
        _Step("Open the three-dot menu.", "Customize and control", 0.97, 0.06, 0.09, ("menus",)),
        _Step(
            "Choose Delete browsing data.", "Delete browsing data", 0.78, 0.39, 0.21, ("privacy",)
        ),
        _Step("Set the time range to All time.", "Time range", 0.52, 0.3, 0.41, ("privacy",)),
        _Step("Press Delete data.", "Delete data", 0.66, 0.79, 0.05, ("privacy",)),
    ),
)

_ASSISTANCE_WEIGHTS = (
    (AssistanceLevel.POINTED, 0.65),
    (AssistanceLevel.HINTED, 0.2),
    (AssistanceLevel.DID_IT, 0.1),
    (AssistanceLevel.NONE, 0.05),
)


def _event(
    task: _Task, index: int, step: _Step, outcome: StepOutcome, rng: random.Random
) -> StepEvent:
    levels, weights = zip(*_ASSISTANCE_WEIGHTS, strict=True)
    jitter = rng.uniform(-0.01, 0.01)
    return StepEvent(
        walkthrough_id="seed",
        app=task.app,
        task=task.task,
        step_index=index,
        instruction=step.instruction,
        assistance=rng.choices(levels, weights)[0],
        outcome=outcome,
        element=ElementRef(
            label=step.label,
            x=min(max(step.x + jitter, 0.0), 1.0),
            y=min(max(step.y - jitter, 0.0), 1.0),
        ),
        concepts=step.concepts,
        app_version=task.app_version,
    )


def simulate(task: _Task, rng: random.Random) -> WalkthroughSummary:
    """One user's walkthrough: stuck steps are retried, and sometimes given up on."""
    events: list[StepEvent] = []
    completed = True
    for index, step in enumerate(task.steps, start=1):
        if rng.random() < step.stuck:
            events.append(_event(task, index, step, StepOutcome.RETRIED, rng))
            if rng.random() < 0.25:
                gave_up = rng.choice((StepOutcome.ABANDONED, StepOutcome.TIMED_OUT))
                events.append(_event(task, index, step, gave_up, rng))
                completed = False
                break
        events.append(_event(task, index, step, StepOutcome.SUCCEEDED, rng))
    return WalkthroughSummary(
        walkthrough_id="seed",
        app=task.app,
        task=task.task,
        steps=tuple(events),
        completed=completed,
        app_version=task.app_version,
    )


def build(users: int, rng: random.Random) -> list[WalkthroughSummary]:
    """Walkthroughs in posting order: the old dark-mode layout comes first."""
    old_users = round(users * 0.55)
    summaries = []
    for user in range(users):
        dark = DARK_MODE_OLD if user < old_users else DARK_MODE_NEW
        for task in (PIVOT, dark, BROWSER, CLEAR_DATA):
            if rng.random() < 0.8:
                summaries.append(simulate(task, rng))
    return summaries


def post_all(url: str, summaries: Sequence[WalkthroughSummary], *, delay: float = 0.0) -> int:
    posted = 0
    with httpx.Client(base_url=url.rstrip("/"), timeout=5.0) as client:
        for summary in summaries:
            while True:
                response = client.post("/v1/walkthroughs", json=summary_to_wire(summary))
                if response.status_code != 429:
                    break
                time.sleep(float(response.headers.get("Retry-After", "1")))
            response.raise_for_status()
            posted += 1
            if delay:
                time.sleep(delay)
    return posted


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed a Curio map server with demo data")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--users", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7, help="random seed")
    parser.add_argument(
        "--delay", type=float, default=0.0, help="seconds between posts (watch the dashboard fill)"
    )
    args = parser.parse_args(argv)

    summaries = build(args.users, random.Random(args.seed))
    posted = post_all(args.url, summaries, delay=args.delay)
    print(f"Posted {posted} walkthroughs from {args.users} simulated users to {args.url}")


if __name__ == "__main__":
    main()
