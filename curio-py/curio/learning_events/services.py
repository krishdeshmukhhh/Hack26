"""The learning pieces the companion talks to, bundled with background fan-out.

Writes (event appends, summaries to the task map, skill model and map sync)
run as background tasks: they log failures and never block a turn or the UI.
Reads for a request are bounded by a short timeout and fail soft.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Sequence

from curio.learning_contract import (
    AssistanceLevel,
    EventLog,
    MapSync,
    SkillModel,
    StepEvent,
    TaskMap,
    TaskPath,
    WalkthroughSummary,
)
from curio.learning_events.context import format_path_for_prompt, learning_prompt_text

logger = logging.getLogger(__name__)

# A request waits at most this long for the task map and skill model.
CONTEXT_TIMEOUT_SECONDS = 1.5


class LearningServices:
    def __init__(
        self,
        *,
        event_log: EventLog,
        task_map: TaskMap,
        skill_model: SkillModel,
        map_sync: MapSync,
        share_walkthroughs: bool = False,
    ) -> None:
        self.event_log = event_log
        self.task_map = task_map
        self.skill_model = skill_model
        self.map_sync = map_sync
        # Changed from the tray at runtime; read when each summary is fanned out.
        self.share_walkthroughs = share_walkthroughs
        self._tasks: set[asyncio.Task] = set()

    # ---- background writes ------------------------------------------------

    def _spawn(self, what: str, coro: Awaitable) -> None:
        async def guarded() -> None:
            try:
                await coro
            except Exception:  # noqa: BLE001
                logger.exception("learning: %s failed", what)

        task = asyncio.ensure_future(guarded())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def record_step(self, event: StepEvent) -> None:
        logger.info(
            "learning: step %d of %s/%r %s (%s)",
            event.step_index, event.app, event.task, event.outcome.value, event.assistance.value,
        )
        self._spawn("event append", self.event_log.append(event))

    def finish_walkthrough(self, summary: WalkthroughSummary) -> None:
        logger.info(
            "learning: walkthrough %s/%r finished, %d steps, completed=%s",
            summary.app, summary.task, len(summary.steps), summary.completed,
        )
        if not summary.steps:
            return
        self._spawn("task map record", self.task_map.record(summary))
        self._spawn("skill model observe", self.skill_model.observe(summary))
        if self.share_walkthroughs:
            self._spawn("map sync push", self._push(summary))

    async def _push(self, summary: WalkthroughSummary) -> None:
        if await self.map_sync.push(summary):
            await self._pull(summary.app)

    def refresh_shared(self, app: str | None = None) -> None:
        """Pull shared paths into the task map in the background."""
        self._spawn("map sync pull", self._pull(app))

    async def _pull(self, app: str | None) -> None:
        shared = await self.map_sync.pull(app)
        if shared:
            changed = await self.task_map.merge(shared)
            logger.info("learning: merged %d shared paths (%d changed)", len(shared), changed)

    async def drain(self) -> None:
        """Wait for pending background writes (tests and shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ---- per-request context ----------------------------------------------

    async def prompt_text(
        self,
        *,
        app: str,
        task: str,
        concepts: Sequence[str] = (),
        point_coords: str,
        image_size: tuple[int, int],
    ) -> str | None:
        """Verified path and skill advice for a how-to request, or None."""
        try:
            return await asyncio.wait_for(
                self._prompt_text(app, task, concepts, point_coords, image_size),
                CONTEXT_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001  (includes TimeoutError)
            logger.exception("learning: no context for %s/%r", app, task)
            return None

    async def _prompt_text(
        self,
        app: str,
        task: str,
        concepts: Sequence[str],
        point_coords: str,
        image_size: tuple[int, int],
    ) -> str | None:
        path = await self.task_map.find(app, task) if task else None
        path_text = None
        if path is not None and path.steps:
            path_text = self._format_path(path, point_coords, image_size)
            concepts = _path_concepts(path) or concepts
        concepts = tuple(concepts)
        assistance = AssistanceLevel.POINTED
        skill_context = None
        if concepts:
            assistance = await self.skill_model.recommend_assistance(app, concepts)
            skill_context = await self.skill_model.prompt_context(app, concepts)
        return learning_prompt_text(
            path_text=path_text, assistance=assistance, skill_context=skill_context
        )

    def _format_path(
        self, path: TaskPath, point_coords: str, image_size: tuple[int, int]
    ) -> str:
        return format_path_for_prompt(
            path,
            point_coords=point_coords,
            image_size=image_size,
            difficulty=lambda index: self.map_sync.step_difficulty(path.app, path.task, index),
        )


def _path_concepts(path: TaskPath) -> tuple[str, ...]:
    seen: list[str] = []
    for step in path.steps:
        for concept in step.concepts:
            if concept not in seen:
                seen.append(concept)
    return tuple(seen)
