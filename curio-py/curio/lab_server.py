"""Lab server for classroom mode: run by the TA, polled by every student's Curio.

    uv run curio-lab lab.toml            # or: python -m curio.lab_server lab.toml

It prints a join code for students and a private dashboard link for the TA.
The server keeps only what students' Curios report (an anonymous id, a step
number and a stuck flag) and shows the TA counts per step, never ids,
questions or screenshots. A hint the TA sends is queued for the students
stuck on that step at that moment; their Curios fetch it on the next poll.

Standard library only, so it runs on any TA laptop with the repo checked out.
Traffic is plain HTTP on the lab network; the join code and instructor key
keep strangers from posting, not from listening.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import secrets
import socket
import threading
import time
import tomllib
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from curio.lab import MAX_HINT_TARGET, MAX_HINT_TEXT, LabStep

logger = logging.getLogger(__name__)

# A student whose Curio hasn't checked in for this long has left (or quit).
STALE_AFTER_SECONDS = 20.0
MAX_STUDENT_ID = 64
MAX_BODY_BYTES = 8 * 1024
AUDIENCES = {"stuck", "step"}
DASHBOARD_PATH = Path(__file__).resolve().parent / "assets" / "lab" / "dashboard.html"


class LabRequestError(ValueError):
    """A bad request: the message is safe to send back."""


@dataclass(frozen=True)
class LabDefinition:
    name: str
    steps: tuple[LabStep, ...]
    code: str
    instructor_key: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LabDefinition:
        name = data.get("name", "Lab")
        if not isinstance(name, str):
            raise ValueError("name must be a string")
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("add at least one [[steps]] entry with a title")
        steps = []
        for index, item in enumerate(raw_steps, start=1):
            title = item.get("title") if isinstance(item, dict) else item
            if not isinstance(title, str) or not title.strip():
                raise ValueError(f"step {index} needs a title")
            steps.append(LabStep(index, title.strip()))
        code = data.get("code") or secrets.token_hex(3).upper()
        key = data.get("instructor_key") or secrets.token_urlsafe(12)
        if not isinstance(code, str) or not isinstance(key, str):
            raise ValueError("code and instructor_key must be strings")
        return cls(name.strip() or "Lab", tuple(steps), code.strip(), key)

    @classmethod
    def from_path(cls, path: Path) -> LabDefinition:
        return cls.from_dict(tomllib.loads(path.read_text(encoding="utf-8")))


@dataclass
class _Student:
    step: int
    stuck: bool
    seen: float


@dataclass
class _Hint:
    id: int
    step: int
    text: str
    target: str
    audience: str
    sent: float
    recipients: frozenset[str]
    delivered: set[str] = field(default_factory=set)

    def payload(self) -> dict[str, Any]:
        return {"id": self.id, "step": self.step, "text": self.text, "target": self.target}


def _text(value: Any, name: str, limit: int, *, required: bool) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise LabRequestError(f"{name} must be a string")
    value = " ".join(value.split())
    if required and not value:
        raise LabRequestError(f"{name} is required")
    if len(value) > limit:
        raise LabRequestError(f"{name} is longer than {limit} characters")
    return value


class LabRoom:
    """Server state for one lab session. Not thread-safe; the server locks around it."""

    def __init__(self, lab: LabDefinition, *, stale_after: float = STALE_AFTER_SECONDS) -> None:
        self.lab = lab
        self._stale_after = stale_after
        self._students: dict[str, _Student] = {}
        self._hints: list[_Hint] = []

    def _step(self, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise LabRequestError("step must be an integer")
        if not 0 <= value <= len(self.lab.steps):
            raise LabRequestError(f"step must be from 0 to {len(self.lab.steps)}")
        return value

    def _active(self, now: float) -> dict[str, _Student]:
        stale = [s for s, v in self._students.items() if now - v.seen > self._stale_after]
        for student_id in stale:
            del self._students[student_id]
        return self._students

    def lab_payload(self) -> dict[str, Any]:
        return {
            "name": self.lab.name,
            "steps": [{"index": s.index, "title": s.title} for s in self.lab.steps],
        }

    def check_in(self, body: dict[str, Any], now: float) -> dict[str, Any]:
        """A student's Curio reports in. Returns the lab and any new hints for it."""
        if not hmac.compare_digest(str(body.get("code", "")).upper(), self.lab.code.upper()):
            raise PermissionError("wrong lab code")
        student_id = _text(body.get("student"), "student", MAX_STUDENT_ID, required=True)
        step = self._step(body.get("step", 0))
        stuck = body.get("stuck", False)
        if not isinstance(stuck, bool):
            raise LabRequestError("stuck must be true or false")
        since = body.get("since", 0)
        if isinstance(since, bool) or not isinstance(since, int):
            raise LabRequestError("since must be an integer")

        self._active(now)[student_id] = _Student(step, stuck, now)
        hints = []
        for hint in self._hints:
            if hint.id > since and student_id in hint.recipients:
                hint.delivered.add(student_id)
                hints.append(hint.payload())
        return {"lab": self.lab_payload(), "hints": hints}

    def add_hint(self, body: dict[str, Any], now: float) -> dict[str, Any]:
        step = self._step(body.get("step"))
        text = _text(body.get("text"), "text", MAX_HINT_TEXT, required=True)
        target = _text(body.get("target"), "target", MAX_HINT_TARGET, required=False)
        audience = body.get("audience", "stuck")
        if audience not in AUDIENCES:
            raise LabRequestError(f"audience must be one of {sorted(AUDIENCES)}")
        recipients = frozenset(
            student_id
            for student_id, student in self._active(now).items()
            if student.step == step and (student.stuck or audience == "step")
        )
        hint = _Hint(len(self._hints) + 1, step, text, target, audience, now, recipients)
        self._hints.append(hint)
        logger.info("hint %d for step %d -> %d students", hint.id, step, len(recipients))
        return {"id": hint.id, "recipients": len(recipients)}

    def dashboard(self, now: float) -> dict[str, Any]:
        """Counts only: no student ids leave the server."""
        students = self._active(now).values()
        rows = []
        for index in range(len(self.lab.steps) + 1):
            here = [s for s in students if s.step == index]
            if index == 0 and not here:
                continue
            rows.append({
                "index": index,
                "title": self.lab.steps[index - 1].title if index else "Step not known yet",
                "working": sum(not s.stuck for s in here),
                "stuck": sum(s.stuck for s in here),
            })
        return {
            **self.lab_payload(),
            "code": self.lab.code,
            "students": len(students),
            "stuck": sum(s.stuck for s in students),
            "rows": rows,
            "hints": [
                {
                    **hint.payload(),
                    "audience": hint.audience,
                    "age_seconds": round(now - hint.sent),
                    "recipients": len(hint.recipients),
                    "delivered": len(hint.delivered),
                }
                for hint in reversed(self._hints)
            ],
        }


class LabServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], room: LabRoom) -> None:
        super().__init__(address, _Handler)
        self.room = room
        self.lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    server: LabServer
    server_version = "CurioLab/1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug("%s %s", self.address_string(), format % args)

    def _send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _is_instructor(self) -> bool:
        key = self.headers.get("X-Lab-Key", "")
        return hmac.compare_digest(key, self.server.room.lab.instructor_key)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise LabRequestError("request too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LabRequestError("body must be JSON") from exc
        if not isinstance(body, dict):
            raise LabRequestError("body must be a JSON object")
        return body

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send(HTTPStatus.OK, DASHBOARD_PATH.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/dashboard":
            if not self._is_instructor():
                self._send(HTTPStatus.FORBIDDEN, {"error": "instructor key required"})
                return
            with self.server.lock:
                payload = self.server.room.dashboard(time.monotonic())
            self._send(HTTPStatus.OK, payload)
        else:
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        room = self.server.room
        try:
            if path == "/api/checkin":
                body = self._body()
                with self.server.lock:
                    payload = room.check_in(body, time.monotonic())
            elif path == "/api/hints":
                if not self._is_instructor():
                    raise PermissionError("instructor key required")
                body = self._body()
                with self.server.lock:
                    payload = room.add_hint(body, time.monotonic())
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
        except PermissionError as exc:
            self._send(HTTPStatus.FORBIDDEN, {"error": str(exc)})
        except LabRequestError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        else:
            self._send(HTTPStatus.OK, payload)


def _lan_address() -> str:
    # Connecting a UDP socket sends nothing; it only picks the outgoing interface.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Curio classroom lab session.")
    parser.add_argument("lab", type=Path, help="lab definition TOML (see lab.example.toml)")
    parser.add_argument("--host", default="0.0.0.0", help="interface to listen on")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    try:
        lab = LabDefinition.from_path(args.lab)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        parser.error(f"cannot load {args.lab}: {exc}")
    server = LabServer((args.host, args.port), LabRoom(lab))
    host = _lan_address() if args.host == "0.0.0.0" else args.host
    base = f"http://{host}:{server.server_address[1]}"
    print(f"\n  {lab.name}: {len(lab.steps)} steps")
    print("\n  Students: put this in the [lab] section of their Curio config.toml")
    print(f'    enabled = true\n    server_url = "{base}"\n    code = "{lab.code}"')
    print(f"\n  TA dashboard (keep this link private):\n    {base}/?key={lab.instructor_key}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
