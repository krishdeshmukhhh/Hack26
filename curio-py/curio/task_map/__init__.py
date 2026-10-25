"""Verified task paths on this machine, learned from finished walkthroughs.

See docs/task-map.md.
"""

from __future__ import annotations

from curio.task_map.difficulty import LocalDifficulty
from curio.task_map.matching import MATCH_THRESHOLD, task_similarity, tasks_match
from curio.task_map.prompt import HARD_STEP_DIFFICULTY, format_for_prompt
from curio.task_map.store import SqliteTaskMap, clean_steps, default_path

__all__ = [
    "HARD_STEP_DIFFICULTY",
    "MATCH_THRESHOLD",
    "LocalDifficulty",
    "SqliteTaskMap",
    "clean_steps",
    "default_path",
    "format_for_prompt",
    "task_similarity",
    "tasks_match",
]
