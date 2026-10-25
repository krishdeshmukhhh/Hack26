"""HTTP client for the shared map server. Implements ``MapSync``.

Every method fails soft: when the server is down, slow or returns junk, it
logs and returns ``False`` or an empty result so the app keeps working offline.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from curio.learning_contract import (
    TaskPath,
    WalkthroughSummary,
    path_from_wire,
    summary_to_wire,
    task_key,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 3.0

_DifficultyKey = tuple[str, str, int]


class HttpMapSync:
    """Pushes anonymous walkthroughs and pulls shared paths and step difficulty.

    Pass ``client`` to share an ``httpx.AsyncClient`` (tests use a mock
    transport); otherwise one is created and ``aclose()`` closes it.
    """

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        self._difficulty: dict[_DifficultyKey, float] = {}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def push(self, summary: WalkthroughSummary) -> bool:
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/walkthroughs",
                json=summary_to_wire(summary),
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as e:
            logger.info("Map sync push failed (offline?): %s", e)
            return False
        if response.is_success:
            return True
        logger.warning(
            "Map server rejected walkthrough: %s %s", response.status_code, response.text[:200]
        )
        return False

    async def pull(self, app: str | None = None) -> tuple[TaskPath, ...]:
        payload = await self._get_json("/v1/paths", app)
        raw_paths = payload.get("paths") if isinstance(payload, dict) else None
        if not isinstance(raw_paths, list):
            return ()
        paths = []
        for raw in raw_paths:
            try:
                paths.append(path_from_wire(raw))
            except (ValueError, KeyError, TypeError, AttributeError):
                logger.debug("Skipping malformed shared path", exc_info=True)
        # Paths arrive best first per task, so only the first fills the cache.
        cache: dict[_DifficultyKey, float] = {}
        for path in paths:
            for step in path.steps:
                if step.difficulty is not None:
                    cache.setdefault((path.app, task_key(path.task), step.index), step.difficulty)
        self._update_difficulty(cache, app)
        return tuple(paths)

    async def refresh_stats(self, app: str | None = None) -> bool:
        """Refresh the difficulty cache from ``/v1/stats``, which counts every attempt."""
        payload = await self._get_json("/v1/stats", app)
        if not isinstance(payload, dict) or not isinstance(payload.get("apps"), list):
            return False
        cache: dict[_DifficultyKey, float] = {}
        try:
            for app_entry in payload["apps"]:
                for task in app_entry["tasks"]:
                    for step in task["steps"]:
                        key = (
                            str(app_entry["app"]),
                            task_key(str(task["task"])),
                            int(step["index"]),
                        )
                        cache[key] = min(max(float(step["stuck_rate"]), 0.0), 1.0)
        except (KeyError, TypeError, ValueError):
            logger.debug("Malformed map stats", exc_info=True)
            return False
        self._update_difficulty(cache, app)
        return True

    def step_difficulty(self, app: str, task: str, step_index: int) -> float | None:
        """Share of users who got stuck at this step, from the last pull or stats refresh."""
        return self._difficulty.get((app, task_key(task), step_index))

    def _update_difficulty(self, fresh: dict[_DifficultyKey, float], app: str | None) -> None:
        # Swap in a new dict so the UI thread never sees one mid-update.
        if app is None:
            merged = fresh
        else:
            merged = {k: v for k, v in self._difficulty.items() if k[0] != app}
            merged.update(fresh)
        self._difficulty = merged

    async def _get_json(self, path: str, app: str | None) -> Any:
        params = {"app": app} if app else None
        try:
            response = await self._client.get(
                f"{self._base_url}{path}", params=params, timeout=TIMEOUT_SECONDS
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.info("Map sync GET %s failed (offline?): %s", path, e)
            return None
