"""Render a verified path as plain lowercase text for the system prompt."""

from __future__ import annotations

from curio.learning_contract import PathSource, TaskPath

HARD_STEP_DIFFICULTY = 0.4  # share of users stuck at which a step is called out


def _position(x: float, y: float, point_coords: str, image_size: tuple[int, int] | None) -> str:
    if point_coords == "norm1000":
        return f"{round(x * 1000)},{round(y * 1000)}"
    if point_coords == "pixel":
        if image_size is None:
            return ""
        width, height = image_size
        return f"{round(x * width)},{round(y * height)}"
    raise ValueError(f"unknown point_coords: {point_coords!r}")


def format_for_prompt(
    path: TaskPath, point_coords: str, image_size: tuple[int, int] | None
) -> str:
    """Numbered steps with instruction, element label and position.

    ``point_coords`` is "norm1000" (0-1000 grid) or "pixel" (``image_size``
    pixels of the screenshot; positions are left out when it's None).
    """
    who = "on this computer" if path.source == PathSource.LOCAL else "by other curio users"
    times = "once" if path.verified_count == 1 else f"{path.verified_count} times"
    lines = [
        f"a verified path for this task, followed to the end {times} {who}. "
        "guide the user along it one step at a time, but trust the current screenshot "
        "if it looks different:"
    ]
    for step in path.steps:
        line = f"{step.index}. {step.instruction.strip().rstrip('.')}"
        if step.element is not None:
            line += f". target: {step.element.label}"
            position = _position(step.element.x, step.element.y, point_coords, image_size)
            if position:
                line += f" at {position}"
        if step.difficulty is not None and step.difficulty >= HARD_STEP_DIFFICULTY:
            line += ". most people get stuck here, so be extra clear"
        lines.append(line.lower())
    return "\n".join(lines)
