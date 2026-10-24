"""Student side of classroom mode: check in with the TA's lab server.

Every few seconds (and right away when the student's step or stuck flag
changes) it posts ``{code, student, step, stuck, since}`` and receives the
lab's step list plus any hints meant for this student. Nothing else is sent:
no name, question text or screenshot.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import uuid4

import httpx
from PySide6.QtCore import QObject, Signal

from curio.lab import LabHint, LabSettings, LabTracker, parse_steps

logger = logging.getLogger(__name__)


class LabClient(QObject):
    hint_received = Signal(object)  # LabHint
    # Step list, step, stuck flag or connection changed: refresh the tray.
    changed = Signal()

    def __init__(
        self,
        settings: LabSettings,
        tracker: LabTracker | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.tracker = tracker or LabTracker(settings.stuck_after_questions)
        self.tracker.on_change = self._on_tracker_change
        # Fresh every launch, so check-ins can't be linked across lab sessions.
        self._student_id = uuid4().hex
        self._since = 0
        self._transport = transport
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.connected = False
        self.last_error = ""

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _on_tracker_change(self) -> None:
        self._wake.set()
        self.changed.emit()

    def _set_connected(self, connected: bool, error: str = "") -> None:
        if (connected, error) != (self.connected, self.last_error):
            if connected and not self.connected:
                logger.info("lab: connected to %s", self._settings.server_url)
            elif error and error != self.last_error:
                logger.warning("lab: %s", error)
            self.connected, self.last_error = connected, error
            self.changed.emit()

    async def check_in(self, client: httpx.AsyncClient) -> None:
        """One round trip. Raises on network errors; the loop reports them."""
        response = await client.post(
            f"{self._settings.server_url}/api/checkin",
            json={
                "code": self._settings.code,
                "student": self._student_id,
                "step": self.tracker.step,
                "stuck": self.tracker.stuck,
                "since": self._since,
            },
        )
        data = response.json() if response.content else {}
        if response.status_code != 200:
            message = data.get("error") if isinstance(data, dict) else None
            raise RuntimeError(message or f"lab server said {response.status_code}")
        lab = data.get("lab") if isinstance(data, dict) else None
        if isinstance(lab, dict):
            name = lab.get("name")
            name = name if isinstance(name, str) else ""
            self.tracker.set_lab(name, parse_steps(lab.get("steps")))
        self._set_connected(True)
        for raw in data.get("hints", []) if isinstance(data, dict) else []:
            hint = LabHint.from_payload(raw)
            if hint is None or hint.id <= self._since:
                continue
            self._since = hint.id
            logger.info("lab: hint %d for step %d", hint.id, hint.step)
            self.hint_received.emit(hint)

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
            while True:
                self._wake.clear()
                try:
                    await self.check_in(client)
                except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                    self._set_connected(False, str(exc) or type(exc).__name__)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self._settings.poll_seconds)
