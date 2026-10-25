from __future__ import annotations

import asyncio
import json
import random
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from curio.learning_contract import (
    AssistanceLevel,
    ElementRef,
    PathSource,
    StepEvent,
    StepOutcome,
    WalkthroughSummary,
    summary_to_wire,
)
from curio.map_sync import seed
from curio.map_sync.client import HttpMapSync
from curio.map_sync.server import (
    MAX_BODY_BYTES,
    MapStore,
    ValidationError,
    aggregate_paths,
    aggregate_stats,
    make_server,
    validate_summary,
)


def _step(
    index: int,
    label: str,
    outcome: StepOutcome = StepOutcome.SUCCEEDED,
    *,
    task: str = "insert a pivot table",
    app: str = "excel",
) -> StepEvent:
    return StepEvent(
        walkthrough_id="w",
        app=app,
        task=task,
        step_index=index,
        instruction=f"Click {label}.",
        assistance=AssistanceLevel.POINTED,
        outcome=outcome,
        element=ElementRef(label=label, x=0.5, y=0.25, window_title="Budget.xlsx - Excel"),
        concepts=("pivot tables",),
    )


def _summary(
    labels: list[str],
    *,
    stuck_at: int | None = None,
    completed: bool = True,
    task: str = "insert a pivot table",
    app: str = "excel",
) -> WalkthroughSummary:
    steps = []
    for i, label in enumerate(labels, start=1):
        if i == stuck_at:
            steps.append(_step(i, label, StepOutcome.RETRIED, task=task, app=app))
        steps.append(_step(i, label, task=task, app=app))
    return WalkthroughSummary(
        walkthrough_id="w", app=app, task=task, steps=tuple(steps), completed=completed
    )


def _wire(*args, **kwargs) -> dict:
    return summary_to_wire(_summary(*args, **kwargs))


def _records(wires: list[dict], *, start: datetime | None = None) -> list[dict]:
    start = start or datetime(2026, 10, 24, tzinfo=UTC)
    return [
        {"summary": validate_summary(w), "received_at": start + timedelta(seconds=i)}
        for i, w in enumerate(wires)
    ]


@pytest.fixture
def server(tmp_path):
    srv = make_server("127.0.0.1", 0, tmp_path / "map.json", rate_per_minute=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


# --- Validation ----------------------------------------------------------------


def test_valid_summary_round_trips():
    wire = _wire(["Insert", "PivotTable"])
    assert validate_summary(json.loads(json.dumps(wire))) == wire


@pytest.mark.parametrize(
    "mutate",
    [
        lambda w: w.update(v=2),
        lambda w: w.update(v=True),
        lambda w: w.update(app=""),
        lambda w: w.update(task=7),
        lambda w: w.update(completed="yes"),
        lambda w: w.update(steps=[]),
        lambda w: w.update(steps=w["steps"] * 31),
        lambda w: w.update(walkthrough_id="abc"),  # ids must never be stored
        lambda w: w["steps"][0].update(instruction="x" * 301),
        lambda w: w["steps"][0].update(index=0),
        lambda w: w["steps"][0].update(index=True),
        lambda w: w["steps"][0].update(outcome="exploded"),
        lambda w: w["steps"][0].update(assistance="magic"),
        lambda w: w["steps"][0].update(occurred_at="2026-10-24T00:00:00"),
        lambda w: w["steps"][0]["element"].update(x=1.5),
        lambda w: w["steps"][0]["element"].update(y=-0.1),
        lambda w: w["steps"][0]["element"].update(x=float("nan")),
        lambda w: w["steps"][0]["element"].update(x="0.5"),
        lambda w: w["steps"][0]["element"].update(window_title="Budget.xlsx - Excel"),
        lambda w: w["steps"][0].update(concepts="pivot tables"),
    ],
)
def test_validation_rejects_bad_payloads(mutate):
    wire = _wire(["Insert", "PivotTable"])
    mutate(wire)
    with pytest.raises(ValidationError):
        validate_summary(wire)


def test_wire_payload_drops_window_titles():
    wire = _wire(["Insert"])
    assert "window_title" not in json.dumps(wire)
    assert validate_summary(wire)["steps"][0]["element"] == {"label": "Insert", "x": 0.5, "y": 0.25}


def test_http_rejects_bad_requests(server):
    with httpx.Client(base_url=server.url) as client:
        assert client.post("/v1/walkthroughs", content=b"{nope").status_code == 400
        bad = _wire(["Insert"])
        bad["v"] = 99
        response = client.post("/v1/walkthroughs", json=bad)
        assert response.status_code == 400
        assert "wire version" in response.json()["error"]
        big = b" " * (MAX_BODY_BYTES + 1)
        assert client.post("/v1/walkthroughs", content=big).status_code == 413
        assert client.post("/v1/nowhere", json={}).status_code == 404
        assert client.get("/v1/stats").json()["walkthroughs"] == 0


def test_http_rate_limit(tmp_path):
    srv = make_server("127.0.0.1", 0, tmp_path / "map.json", rate_per_minute=3)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with httpx.Client(base_url=srv.url) as client:
            codes = [
                client.post("/v1/walkthroughs", json=_wire(["A"])).status_code for _ in range(5)
            ]
        assert codes[:3] == [201, 201, 201]
        assert codes[3:] == [429, 429]
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("size", [0, 2, MAX_BODY_BYTES + 1])
def test_unknown_post_returns_404_without_resetting_connection(server, size):
    with httpx.Client(base_url=server.url) as client:
        response = client.post("/v1/nowhere", content=b"x" * size)
        assert response.status_code == 404
        assert response.json() == {"error": "not found"}
        assert client.get("/v1/stats").json()["walkthroughs"] == 0


def test_store_persists_atomically(tmp_path):
    path = tmp_path / "data" / "map.json"
    store = MapStore(path)
    store.add(validate_summary(_wire(["Insert"])))
    store.add(validate_summary(_wire(["Insert", "PivotTable"])))
    assert not list(path.parent.glob("*.tmp"))
    reloaded = MapStore(path)
    assert [len(r["summary"]["steps"]) for r in reloaded.records()] == [1, 2]


def test_store_survives_corrupt_file(tmp_path):
    path = tmp_path / "map.json"
    path.write_text("{not json", encoding="utf-8")
    assert MapStore(path).records() == []


# --- Aggregation ---------------------------------------------------------------


def test_paths_group_by_label_sequence_and_count():
    records = _records(
        [
            _wire(["Insert", "PivotTable", "OK"]),
            _wire(["Insert", "PivotTable", "OK"], stuck_at=2),
            _wire(["Insert", "PivotTable", "OK"], task="How do I insert a pivot table?"),
            _wire(["Insert", "PivotTable"], completed=False),  # difficulty only
            _wire(["Settings"], app="settings", task="turn on dark mode"),
        ]
    )
    paths = aggregate_paths(records, "excel")
    assert len(paths) == 1
    path = paths[0]
    assert path["task"] == "insert a pivot table"
    assert path["verified_count"] == 3
    assert [s["element"]["label"] for s in path["steps"]] == ["Insert", "PivotTable", "OK"]
    assert "window_title" not in json.dumps(paths)


def test_step_difficulty_is_share_of_walkthroughs_stuck():
    records = _records(
        [
            _wire(["Insert", "PivotTable", "Fields"], stuck_at=3),
            _wire(["Insert", "PivotTable", "Fields"], stuck_at=3),
            _wire(["Insert", "PivotTable", "Fields"]),
            _wire(["Insert", "PivotTable", "Fields"], stuck_at=1),
        ]
    )
    steps = aggregate_paths(records)[0]["steps"]
    assert [s["difficulty"] for s in steps] == [0.25, 0.0, 0.5]

    stats = aggregate_stats(records)
    task = stats["apps"][0]["tasks"][0]
    assert task["walkthroughs"] == 4
    assert [(s["label"], s["attempts"], s["stuck"]) for s in task["steps"]] == [
        ("Insert", 4, 1),
        ("PivotTable", 4, 0),
        ("Fields", 4, 2),
    ]
    assert stats["hardest"][0]["label"] == "Fields"


def test_incomplete_walkthroughs_count_toward_difficulty_only():
    abandoned = summary_to_wire(
        WalkthroughSummary(
            walkthrough_id="w",
            app="excel",
            task="insert a pivot table",
            steps=(_step(1, "Insert"), _step(2, "PivotTable", StepOutcome.ABANDONED)),
            completed=False,
        )
    )
    records = _records([_wire(["Insert", "PivotTable"]), abandoned])
    path = aggregate_paths(records)[0]
    assert path["verified_count"] == 1
    assert path["steps"][1]["difficulty"] == 0.5


def test_newer_path_overtakes_stale_one():
    old = [_wire(["Personalization", "Choose your default app mode"])] * 6
    new = [_wire(["Personalization", "Choose your mode"])] * 4
    paths = aggregate_paths(_records(old + new))
    assert [p["verified_count"] for p in paths] == [4, 6]
    assert paths[0]["steps"][1]["element"]["label"] == "Choose your mode"
    assert paths[0]["score"] > paths[1]["score"]


def test_old_walkthroughs_decay_with_age():
    now = datetime(2026, 10, 24, tzinfo=UTC)
    stale = _records([_wire(["Old"])] * 3, start=now - timedelta(days=120))
    fresh = _records([_wire(["New"])] * 2, start=now - timedelta(days=60))
    # Interleave so rank doesn't favour either side; age alone decides.
    records = [stale[0], fresh[0], stale[1], fresh[1], stale[2]]
    paths = aggregate_paths(records, now=now)
    assert paths[0]["steps"][0]["element"]["label"] == "New"


def test_http_end_to_end_paths_and_stats(server):
    with httpx.Client(base_url=server.url) as client:
        for wire in [_wire(["Insert", "PivotTable"], stuck_at=2), _wire(["Insert", "PivotTable"])]:
            assert client.post("/v1/walkthroughs", json=wire).status_code == 201
        paths = client.get("/v1/paths", params={"app": "excel"}).json()["paths"]
        assert paths[0]["verified_count"] == 2
        assert client.get("/v1/paths", params={"app": "word"}).json()["paths"] == []
        stats = client.get("/v1/stats").json()
        assert stats["apps"][0]["tasks"][0]["steps"][1]["stuck_rate"] == 0.5
        page = client.get("/")
        assert page.status_code == 200
        assert "Where people get" in page.text


# --- Client --------------------------------------------------------------------


def test_client_push_pull_and_difficulty(server):
    async def scenario():
        sync = HttpMapSync(server.url)
        try:
            assert await sync.push(_summary(["Insert", "PivotTable"], stuck_at=2))
            assert await sync.push(_summary(["Insert", "PivotTable"]))
            assert sync.step_difficulty("excel", "insert a pivot table", 2) is None
            paths = await sync.pull("excel")
            assert len(paths) == 1
            assert paths[0].source is PathSource.SHARED
            assert paths[0].verified_count == 2
            assert sync.step_difficulty("excel", "How do I insert a pivot table?", 2) == 0.5
            assert sync.step_difficulty("excel", "insert a pivot table", 9) is None
            assert await sync.refresh_stats()
            assert sync.step_difficulty("excel", "insert a pivot table", 1) == 0.0
        finally:
            await sync.aclose()

    asyncio.run(scenario())


def test_client_fails_soft_when_server_is_down():
    async def scenario():
        sync = HttpMapSync("http://127.0.0.1:1")
        try:
            assert await sync.push(_summary(["Insert"])) is False
            assert await sync.pull() == ()
            assert await sync.refresh_stats() is False
            assert sync.step_difficulty("excel", "insert a pivot table", 1) is None
        finally:
            await sync.aclose()

    asyncio.run(scenario())


def test_client_fails_soft_on_timeouts_and_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/paths":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(500, text="boom")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sync = HttpMapSync("http://map", client=client)
            assert await sync.push(_summary(["Insert"])) is False
            assert await sync.pull() == ()
            assert await sync.refresh_stats() is False

    asyncio.run(scenario())


def test_client_skips_malformed_paths():
    good = {
        "v": 1,
        "app": "excel",
        "task": "insert a pivot table",
        "verified_count": 3,
        "steps": [{"index": 1, "instruction": "Click Insert.", "element": None, "difficulty": 0.4}],
    }
    body = {"paths": [good, {"v": 2}, {"v": 1, "app": "excel"}, "junk", {**good, "steps": [{}]}]}

    async def scenario():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        async with httpx.AsyncClient(transport=transport) as client:
            sync = HttpMapSync("http://map", client=client)
            paths = await sync.pull()
            assert len(paths) == 1
            assert sync.step_difficulty("excel", "insert a pivot table", 1) == 0.4

    asyncio.run(scenario())


def test_client_ignores_non_json_responses():
    async def scenario():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))
        async with httpx.AsyncClient(transport=transport) as client:
            sync = HttpMapSync("http://map", client=client)
            assert await sync.pull() == ()
            assert await sync.refresh_stats() is False

    asyncio.run(scenario())


# --- Seeding -------------------------------------------------------------------


def test_seed_data_is_valid_and_shows_self_healing(server):
    summaries = seed.build(40, random.Random(7))
    assert seed.post_all(server.url, summaries) == len(summaries)

    records = server.store.records()
    paths = aggregate_paths(records, "settings")
    dark = [p for p in paths if p["task"] == "turn on dark mode"]
    assert dark[0]["steps"][-1]["element"]["label"] == "Choose your mode"
    assert len(dark) >= 2

    stats = aggregate_stats(records, "settings")
    dark_stats = next(t for t in stats["apps"][0]["tasks"] if t["task"] == "turn on dark mode")
    assert dark_stats["steps"][-1]["label"] == "Choose your mode"  # newest label wins

    hardest = aggregate_stats(records)["hardest"][0]
    assert hardest["label"] == "pivot fields"
    assert hardest["stuck_rate"] > 0.4
