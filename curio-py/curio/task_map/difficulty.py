"""Per-step difficulty from this machine's own walkthrough history."""

from __future__ import annotations

from collections.abc import Mapping

from curio.task_map.matching import MATCH_THRESHOLD, task_similarity

# (app, task) -> step_index -> (attempts, stuck); stuck = retried or timed out.
StepStats = Mapping[tuple[str, str], Mapping[int, tuple[int, int]]]


class LocalDifficulty:
    """``DifficultyProvider`` over a snapshot the task map refreshes after each record.

    Synchronous and cached: safe to call on the UI thread, never touches SQLite.
    Returns None until the map has loaded its history or when a step has no attempts.
    """

    def __init__(self, min_attempts: int = 1) -> None:
        self._min_attempts = min_attempts
        # Stats and the task-match memo for them, swapped together as one tuple
        # so a UI-thread reader never mixes a memo with a newer snapshot.
        self._snapshot: tuple[StepStats, dict[tuple[str, str], tuple[str, str] | None]] = (
            {},
            {},
        )

    def update(self, stats: StepStats) -> None:
        self._snapshot = (stats, {})

    def step_difficulty(self, app: str, task: str, step_index: int) -> float | None:
        stats, resolved = self._snapshot
        key = (app, task)
        if key not in resolved:
            resolved[key] = self._resolve(stats, app, task)
        match = resolved[key]
        if match is None:
            return None
        attempts, stuck = stats[match].get(step_index, (0, 0))
        if attempts < self._min_attempts:
            return None
        return stuck / attempts

    @staticmethod
    def _resolve(stats: StepStats, app: str, task: str) -> tuple[str, str] | None:
        if (app, task) in stats:
            return (app, task)
        scored = [
            (task_similarity(task, other, app), (a, other)) for (a, other) in stats if a == app
        ]
        best = max(scored, default=None)
        return best[1] if best is not None and best[0] >= MATCH_THRESHOLD else None
