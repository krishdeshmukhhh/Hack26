"""Do-nothing task map, skill model and map sync.

They let the app run before the real implementations are wired in, and
stand in when learning or sharing is switched off.
"""

from __future__ import annotations

from collections.abc import Sequence

from curio.learning_contract import (
    AssistanceLevel,
    SkillState,
    TaskPath,
    WalkthroughSummary,
)


class NullTaskMap:
    async def record(self, summary: WalkthroughSummary) -> TaskPath | None:
        return None

    async def find(self, app: str, task: str) -> TaskPath | None:
        return None

    async def paths(self, app: str | None = None) -> tuple[TaskPath, ...]:
        return ()

    async def merge(self, shared: Sequence[TaskPath]) -> int:
        return 0


class NullSkillModel:
    async def observe(self, summary: WalkthroughSummary) -> None:
        return None

    async def snapshot(self) -> tuple[SkillState, ...]:
        return ()

    async def recommend_assistance(self, app: str, concepts: Sequence[str]) -> AssistanceLevel:
        # Today's behaviour: point at every step.
        return AssistanceLevel.POINTED

    async def prompt_context(self, app: str, concepts: Sequence[str]) -> str | None:
        return None

    async def reset(self) -> None:
        return None


class NullMapSync:
    def step_difficulty(self, app: str, task: str, step_index: int) -> float | None:
        return None

    async def push(self, summary: WalkthroughSummary) -> bool:
        return False

    async def pull(self, app: str | None = None) -> tuple[TaskPath, ...]:
        return ()
