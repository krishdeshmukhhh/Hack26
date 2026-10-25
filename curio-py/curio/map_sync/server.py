"""Shared map server: stores minimized reports, serves paths, stats and a dashboard.

Standard library only. Run it on the demo network with::

    python -m curio.map_sync.server --host 0.0.0.0 --port 8765 --data map.json

Endpoints:

- ``POST /v1/walkthroughs``: one ``summary_to_wire`` payload, validated strictly.
- ``GET /v1/paths?app=``: aggregated ``path_to_wire`` paths, best first per task.
- ``GET /v1/stats?app=``: per app, task and step: attempts and stuck rate.
- ``GET /``: the "where people get stuck" dashboard.

Storage is one JSON file rewritten atomically after every accepted walkthrough.
The server adds only a receipt time, which never leaves it.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import tempfile
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from curio.learning_contract import (
    WIRE_VERSION,
    AssistanceLevel,
    ElementRef,
    PathSource,
    PathStep,
    StepOutcome,
    TaskPath,
    path_to_wire,
    task_key,
)

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024
MAX_DRAIN_BYTES = 1024 * 1024  # bigger bodies get a 413 and a closed connection
MAX_STEPS = 30
MAX_INSTRUCTION_CHARS = 300
MAX_TASK_CHARS = 300
MAX_APP_CHARS = 100
MAX_LABEL_CHARS = 200
MAX_CONCEPTS = 10
MAX_CONCEPT_CHARS = 100
MAX_STEP_INDEX = 100
MAX_STORED = 50_000  # oldest walkthroughs are dropped past this

# Recency: a summary's weight halves every RANK_HALF_LIFE newer completed summaries
# of the same task, and every AGE_HALF_LIFE_DAYS. Rank matters most in a demo,
# where every summary arrives within minutes.
RANK_HALF_LIFE = 8.0
AGE_HALF_LIFE_DAYS = 30.0

STUCK_OUTCOMES = frozenset({StepOutcome.RETRIED, StepOutcome.TIMED_OUT, StepOutcome.ABANDONED})

_SUMMARY_KEYS = frozenset({"v", "app", "app_version", "task", "completed", "steps", "synthetic"})
_STEP_KEYS = frozenset({"index", "instruction", "element", "concepts", "assistance", "outcome"})
_ELEMENT_KEYS = frozenset({"label", "x", "y"})
_ASSISTANCE_VALUES = frozenset(a.value for a in AssistanceLevel)
_OUTCOME_VALUES = frozenset(o.value for o in StepOutcome)


# --- Validation ---------------------------------------------------------------


class ValidationError(ValueError):
    """The payload isn't a valid ``summary_to_wire`` walkthrough."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _check_keys(raw: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = set(raw) - allowed
    # Unknown keys are rejected so ids, timestamps or titles can't sneak in.
    _require(not unknown, f"{where}: unexpected keys {sorted(unknown)}")


def _text(value: Any, where: str, *, max_chars: int, allow_empty: bool = False) -> str:
    _require(isinstance(value, str), f"{where} must be a string")
    _require(len(value) <= max_chars, f"{where} is longer than {max_chars} characters")
    _require(allow_empty or bool(value.strip()), f"{where} must not be empty")
    return value


def _fraction(value: Any, where: str) -> float:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{where} must be a number",
    )
    _require(math.isfinite(value) and 0.0 <= value <= 1.0, f"{where} must be in 0..1")
    return float(value)


def _validate_element(raw: Any, where: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    _require(isinstance(raw, dict), f"{where} must be an object or null")
    _check_keys(raw, _ELEMENT_KEYS, where)
    return {
        "label": _text(raw.get("label"), f"{where}.label", max_chars=MAX_LABEL_CHARS),
        "x": _fraction(raw.get("x"), f"{where}.x"),
        "y": _fraction(raw.get("y"), f"{where}.y"),
    }


def _validate_step(raw: Any, where: str) -> dict[str, Any]:
    _require(isinstance(raw, dict), f"{where} must be an object")
    _check_keys(raw, _STEP_KEYS, where)
    index = raw.get("index")
    _require(
        isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= MAX_STEP_INDEX,
        f"{where}.index must be an integer in 1..{MAX_STEP_INDEX}",
    )
    concepts = raw.get("concepts", [])
    _require(isinstance(concepts, list), f"{where}.concepts must be a list")
    _require(len(concepts) <= MAX_CONCEPTS, f"{where}.concepts has more than {MAX_CONCEPTS}")
    assistance = raw.get("assistance")
    outcome = raw.get("outcome")
    _require(assistance in _ASSISTANCE_VALUES, f"{where}.assistance is not a known level")
    _require(outcome in _OUTCOME_VALUES, f"{where}.outcome is not a known outcome")
    return {
        "index": index,
        "instruction": _text(
            raw.get("instruction"), f"{where}.instruction", max_chars=MAX_INSTRUCTION_CHARS
        ),
        "element": _validate_element(raw.get("element"), f"{where}.element"),
        "concepts": [
            _text(c, f"{where}.concepts[{i}]", max_chars=MAX_CONCEPT_CHARS)
            for i, c in enumerate(concepts)
        ],
        "assistance": assistance,
        "outcome": outcome,
    }


def validate_summary(raw: Any) -> dict[str, Any]:
    """Return a clean copy of a ``summary_to_wire`` payload or raise ValidationError."""
    _require(isinstance(raw, dict), "body must be a JSON object")
    _check_keys(raw, _SUMMARY_KEYS, "walkthrough")
    _require(
        raw.get("v") == WIRE_VERSION and not isinstance(raw.get("v"), bool),
        f"unsupported wire version, expected {WIRE_VERSION}",
    )
    synthetic = raw.get("synthetic")
    _require(synthetic is None or isinstance(synthetic, bool), "synthetic must be boolean")
    completed = raw.get("completed")
    _require(isinstance(completed, bool), "completed must be true or false")
    steps = raw.get("steps")
    _require(isinstance(steps, list), "steps must be a list")
    _require(1 <= len(steps) <= MAX_STEPS, f"steps must have 1..{MAX_STEPS} entries")
    return {
        "v": WIRE_VERSION,
        "app": _text(raw.get("app"), "app", max_chars=MAX_APP_CHARS),
        "app_version": _text(
            raw.get("app_version", ""), "app_version", max_chars=MAX_APP_CHARS, allow_empty=True
        ),
        "task": _text(raw.get("task"), "task", max_chars=MAX_TASK_CHARS),
        **({"synthetic": synthetic} if synthetic is not None else {}),
        "completed": completed,
        "steps": [_validate_step(s, f"steps[{i}]") for i, s in enumerate(steps)],
    }


# --- Storage -----------------------------------------------------------------


class MapStore:
    """Walkthroughs in a JSON file, rewritten atomically. Thread-safe."""

    def __init__(self, path: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = self._load()
        self._generation = 0

    @property
    def generation(self) -> int:
        """Bumped on every change; lets callers cache aggregates."""
        return self._generation

    def _load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            logger.exception("Map data at %s is unreadable; starting empty", self._path)
            return []
        records = []
        for item in raw.get("walkthroughs", []) if isinstance(raw, dict) else []:
            try:
                summary = validate_summary(item.get("summary"))
                received = datetime.fromisoformat(item["received_at"])
            except (ValidationError, KeyError, TypeError, ValueError, AttributeError):
                continue
            records.append({"summary": summary, "received_at": received})
        return records

    def add(self, summary: dict[str, Any]) -> None:
        with self._lock:
            self._records.append({"summary": summary, "received_at": self._clock()})
            del self._records[:-MAX_STORED]
            self._generation += 1
            self._save()

    def records(self) -> list[dict[str, Any]]:
        """Snapshot, oldest first."""
        with self._lock:
            return list(self._records)

    def _save(self) -> None:
        payload = {
            "v": WIRE_VERSION,
            "walkthroughs": [
                {"summary": r["summary"], "received_at": r["received_at"].isoformat()}
                for r in self._records
            ],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self._path.name, suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


# --- Aggregation ---------------------------------------------------------------


def _steps_by_index(summary: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    by_index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for step in summary["steps"]:
        by_index[step["index"]].append(step)
    return dict(sorted(by_index.items()))


def _label(step: dict[str, Any]) -> str:
    element = step.get("element")
    return element["label"] if element else ""


def _group_key(summary: dict[str, Any]) -> tuple[str, str]:
    return summary["app"], task_key(summary["task"])


def _filter_app(records: Iterable[dict[str, Any]], app: str | None) -> list[dict[str, Any]]:
    return [r for r in records if not app or r["summary"]["app"] == app]


@dataclass(frozen=True)
class _StepStats:
    attempts: int
    stuck: int
    label: str

    @property
    def stuck_rate(self) -> float:
        return self.stuck / self.attempts if self.attempts else 0.0


def _task_stats(summaries: Sequence[dict[str, Any]]) -> dict[int, _StepStats]:
    """Per step index: how many walkthroughs reached it and how many got stuck there.

    A walkthrough counts as stuck at a step if any attempt at that index was
    retried, timed out or abandoned, even if it succeeded afterwards. The label
    is the newest one seen (summaries are oldest first), so it follows app updates.
    """
    attempts: Counter[int] = Counter()
    stuck: Counter[int] = Counter()
    labels: dict[int, str] = {}
    for summary in summaries:
        for index, events in _steps_by_index(summary).items():
            attempts[index] += 1
            if any(StepOutcome(e["outcome"]) in STUCK_OUTCOMES for e in events):
                stuck[index] += 1
            labels[index] = _label(events[-1]) or events[-1]["instruction"]
    return {
        index: _StepStats(
            attempts=attempts[index],
            stuck=stuck[index],
            label=labels[index],
        )
        for index in sorted(attempts)
    }


def aggregate_stats(records: Sequence[dict[str, Any]], app: str | None = None) -> dict[str, Any]:
    by_task: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in _filter_app(records, app):
        by_task[_group_key(record["summary"])].append(record["summary"])

    apps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    hardest = []
    for (app_name, task), summaries in sorted(by_task.items()):
        steps = _task_stats(summaries)
        step_rows = [
            {
                "index": index,
                "label": s.label,
                "attempts": s.attempts,
                "stuck": s.stuck,
                "stuck_rate": round(s.stuck_rate, 4),
            }
            for index, s in steps.items()
        ]
        apps[app_name].append(
            {
                "task": task,
                "walkthroughs": len(summaries),
                "completed": sum(1 for s in summaries if s["completed"]),
                "steps": step_rows,
            }
        )
        hardest.extend({"app": app_name, "task": task, **row} for row in step_rows)

    hardest = [h for h in hardest if h["attempts"] >= 3 and h["stuck"] > 0]
    hardest.sort(key=lambda h: (-h["stuck_rate"], -h["attempts"]))
    return {
        "v": WIRE_VERSION,
        "walkthroughs": sum(t["walkthroughs"] for ts in apps.values() for t in ts),
        "apps": [{"app": name, "tasks": tasks} for name, tasks in sorted(apps.items())],
        "hardest": hardest[:10],
        "evidence_basis": "model_reported",
        "provenance": {
            "synthetic": sum(r["summary"].get("synthetic") is True
                             for r in _filter_app(records, app)),
            "unknown": sum(r["summary"].get("synthetic") is not True
                           for r in _filter_app(records, app)),
        },
    }


def _recency_weight(rank_from_newest: int, age_days: float) -> float:
    return 0.5 ** (rank_from_newest / RANK_HALF_LIFE) * 0.5 ** (
        max(age_days, 0.0) / AGE_HALF_LIFE_DAYS
    )


def _canonical_steps(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """The step the user finally got through at each index (the last attempt)."""
    return [events[-1] for events in _steps_by_index(summary).values()]


def aggregate_paths(
    records: Sequence[dict[str, Any]],
    app: str | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Group completed walkthroughs into paths, best first within each task.

    Paths are grouped by app, task and element-label sequence. ``verified_count``
    is the number of walkthroughs that followed the path; ``score`` sums their
    recency weights and decides the order, so a corrected path overtakes a stale
    one after an app update even when the stale one has more walkthroughs.
    """
    now = now or datetime.now(UTC)
    records = _filter_app(records, app)

    by_task: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_task[_group_key(record["summary"])].append(record)

    out: list[dict[str, Any]] = []
    for (app_name, task), task_records in sorted(by_task.items()):
        difficulty = _task_stats([r["summary"] for r in task_records])
        completed = [r for r in task_records if r["summary"]["completed"]]
        groups: dict[tuple[str, ...], dict[str, Any]] = {}
        for rank, record in enumerate(reversed(completed)):  # newest first
            steps = _canonical_steps(record["summary"])
            if any(s["outcome"] != StepOutcome.SUCCEEDED for s in steps):
                continue  # A completion flag cannot erase a later failed attempt.
            labels = tuple(_label(s) for s in steps)
            age_days = (now - record["received_at"]).total_seconds() / 86400
            group = groups.setdefault(
                labels, {"latest": record["summary"], "steps": steps, "count": 0, "score": 0.0}
            )
            group["count"] += 1
            group["score"] += _recency_weight(rank, age_days)

        ranked = sorted(groups.values(), key=lambda g: -g["score"])
        for group in ranked:
            path = TaskPath(
                app=app_name,
                task=task,
                steps=tuple(
                    PathStep(
                        index=s["index"],
                        instruction=s["instruction"],
                        element=None
                        if s["element"] is None
                        else ElementRef(
                            label=s["element"]["label"], x=s["element"]["x"], y=s["element"]["y"]
                        ),
                        concepts=tuple(s["concepts"]),
                        difficulty=round(difficulty[s["index"]].stuck_rate, 4)
                        if s["index"] in difficulty
                        else None,
                    )
                    for s in group["steps"]
                ),
                verified_count=group["count"],
                source=PathSource.SHARED,
                app_version=group["latest"]["app_version"],
            )
            out.append({**path_to_wire(path), "score": round(group["score"], 4),
                        "evidence_basis": "model_reported"})
    return out


# --- HTTP ----------------------------------------------------------------------


class RateLimiter:
    """Per-IP token bucket. ``per_minute`` <= 0 disables it."""

    def __init__(self, per_minute: float, *, burst: int | None = None) -> None:
        self._rate = per_minute / 60.0
        self._burst = float(burst if burst is not None else max(per_minute, 1))
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, ip: str) -> bool:
        if self._rate <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(ip, (self._burst, now))
            tokens = min(self._burst, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._buckets[ip] = (tokens, now)
                return False
            self._buckets[ip] = (tokens - 1.0, now)
            if len(self._buckets) > 10_000:  # forget idle clients
                self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < 600}
            return True


def _dashboard_html() -> bytes:
    return (resources.files("curio.map_sync") / "assets" / "dashboard.html").read_bytes()


class MapServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        store: MapStore,
        *,
        rate_per_minute: float = 120.0,
    ) -> None:
        super().__init__(address, _Handler)
        self.store = store
        self.limiter = RateLimiter(rate_per_minute)
        self._cache: dict[tuple[str, str | None], tuple[int, Any]] = {}
        self._cache_lock = threading.Lock()

    def cached(self, kind: str, app: str | None, build: Callable[[], Any]) -> Any:
        """Aggregates are rebuilt only after a new walkthrough arrives."""
        generation = self.store.generation
        with self._cache_lock:
            hit = self._cache.get((kind, app))
            if hit and hit[0] == generation:
                return hit[1]
        value = build()
        with self._cache_lock:
            if len(self._cache) > 256:
                self._cache.clear()
            self._cache[(kind, app)] = (generation, value)
        return value

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class _Handler(BaseHTTPRequestHandler):
    server: MapServer
    server_version = "CurioMap/1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug("%s - %s", self.client_address[0], format % args)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def _app_param(self, query: str) -> str | None:
        app = parse_qs(query).get("app", [""])[0].strip()
        return app or None

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        if url.path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, _dashboard_html(), "text/html; charset=utf-8")
        elif url.path == "/v1/paths":
            app = self._app_param(url.query)
            paths = self.server.cached(
                "paths", app, lambda: aggregate_paths(
                    [r for r in self.server.store.records()
                     if r["summary"].get("synthetic") is not True], app)
            )
            self._json(HTTPStatus.OK, {"v": WIRE_VERSION, "paths": paths})
        elif url.path == "/v1/stats":
            app = self._app_param(url.query)
            include_synthetic = parse_qs(url.query).get("include_synthetic") == ["1"]
            stats = self.server.cached(
                "demo-stats" if include_synthetic else "stats", app,
                lambda: aggregate_stats(
                    [r for r in self.server.store.records()
                     if include_synthetic
                     or r["summary"].get("synthetic") is not True], app)
            )
            self._json(HTTPStatus.OK, stats)
        elif url.path == "/healthz":
            self._json(HTTPStatus.OK, {"ok": True})
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/v1/walkthroughs":
            # Closing with unread request bytes can reset the connection on
            # Windows before the client receives the 404. Drain bounded bodies
            # just as we do for oversized walkthrough submissions below.
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if 0 <= length <= MAX_DRAIN_BYTES:
                self.rfile.read(length)
            else:
                self.close_connection = True
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            self._error(HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
            return
        if length < 0 or length > MAX_BODY_BYTES:
            if 0 < length <= MAX_DRAIN_BYTES:
                # Discard it so the client reads our reply instead of a connection reset.
                while length > 0:
                    chunk = self.rfile.read(min(length, MAX_BODY_BYTES))
                    if not chunk:
                        break
                    length -= len(chunk)
            else:
                self.close_connection = True
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"body over {MAX_BODY_BYTES} bytes")
            return
        # Read the body even when rate limited, so the keep-alive connection stays usable.
        body = self.rfile.read(length)
        if not self.server.limiter.allow(self.client_address[0]):
            self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
            self.send_header("Retry-After", "2")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            summary = validate_summary(json.loads(body))
        except ValidationError as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
            return
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "body is not valid JSON")
            return
        self.server.store.add(summary)
        self._json(HTTPStatus.CREATED, {"ok": True})


def make_server(host: str, port: int, data: Path, *, rate_per_minute: float = 120.0) -> MapServer:
    """Bind a server (port 0 picks a free one); call ``serve_forever`` to run it."""
    return MapServer((host, port), MapStore(data), rate_per_minute=rate_per_minute)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Curio shared map server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=Path("map.json"))
    parser.add_argument(
        "--rate", type=float, default=120.0, help="POSTs per minute per IP (0 = unlimited)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    server = make_server(args.host, args.port, args.data, rate_per_minute=args.rate)
    logger.info(
        "Curio map server on http://%s:%d (data: %s, %d walkthroughs)",
        args.host,
        server.server_address[1],
        args.data,
        len(server.store.records()),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
