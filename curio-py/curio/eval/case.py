"""Eval case on disk: ``<cases>/<name>/case.json`` plus screen JPEGs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from curio.screen_capture import ScreenshotImage

CASE_FILE = "case.json"


@dataclass(frozen=True)
class Expected:
    first_step_keywords: tuple[str, ...] = ()
    forbidden_keywords: tuple[str, ...] = ()
    point_box: dict[str, Any] | None = None  # {screen, x0, y0, x1, y1} in image pixels
    min_steps: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Expected:
        data = data or {}
        box = data.get("point_box")
        min_steps = data.get("min_steps")
        return cls(
            first_step_keywords=tuple(str(k) for k in data.get("first_step_keywords") or ()),
            forbidden_keywords=tuple(str(k) for k in data.get("forbidden_keywords") or ()),
            point_box=box if isinstance(box, dict) and box else None,
            min_steps=int(min_steps) if min_steps else None,
        )

    @property
    def is_empty(self) -> bool:
        return not (
            self.first_step_keywords
            or self.forbidden_keywords
            or self.point_box
            or self.min_steps
        )


@dataclass(frozen=True)
class EvalCase:
    name: str
    question: str
    windows_text: str | None
    window_title: str
    screens: list[ScreenshotImage]
    expected: Expected = field(default_factory=Expected)


def screenshot_meta(shot: ScreenshotImage, file: str) -> dict[str, Any]:
    return {
        "file": file,
        "label": shot.label,
        "is_cursor_screen": shot.is_cursor_screen,
        "display_width_px": shot.display_width_px,
        "display_height_px": shot.display_height_px,
        "image_width_px": shot.image_width_px,
        "image_height_px": shot.image_height_px,
        "scale": shot.scale,
        "monitor_left": shot.monitor_left,
        "monitor_top": shot.monitor_top,
    }


def load_case(directory: Path) -> EvalCase:
    data = json.loads((directory / CASE_FILE).read_text(encoding="utf-8"))
    screens: list[ScreenshotImage] = []
    for meta in data["screens"]:
        screens.append(
            ScreenshotImage(
                jpeg_bytes=(directory / meta["file"]).read_bytes(),
                label=meta["label"],
                is_cursor_screen=bool(meta.get("is_cursor_screen", False)),
                display_width_px=int(meta["display_width_px"]),
                display_height_px=int(meta["display_height_px"]),
                image_width_px=int(meta["image_width_px"]),
                image_height_px=int(meta["image_height_px"]),
                scale=float(meta.get("scale", 1.0)),
                monitor_left=int(meta.get("monitor_left", 0)),
                monitor_top=int(meta.get("monitor_top", 0)),
            )
        )
    return EvalCase(
        name=data.get("name") or directory.name,
        question=data["question"],
        windows_text=data.get("windows_text") or None,
        window_title=data.get("window_title", ""),
        screens=screens,
        expected=Expected.from_dict(data.get("expected")),
    )


def load_cases(root: Path) -> list[EvalCase]:
    """Load every ``<root>/*/case.json`` (sorted by name)."""
    return [
        load_case(d) for d in sorted(root.iterdir()) if d.is_dir() and (d / CASE_FILE).is_file()
    ]
