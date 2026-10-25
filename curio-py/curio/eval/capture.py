"""Record an eval scenario: ``python -m curio.eval.capture --name X --question "..."``.

After ``--delay`` seconds (arrange your windows!) it captures the screens the
way the app does, plus the open-window block and foreground title, and writes
``eval_cases/<name>/`` with the JPEGs and a ``case.json`` to fill in.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from curio.eval.case import CASE_FILE, screenshot_meta

EXPECTED_TEMPLATE = {
    "first_step_keywords": [],
    "forbidden_keywords": [],
    "point_box": None,
    "min_steps": None,
}


def build_case_json(name: str, question: str, windows_text, window_title, screens) -> dict:
    files = [f"screen{i + 1}.jpg" for i in range(len(screens))]
    return {
        "name": name,
        "question": question,
        "window_title": window_title,
        "windows_text": windows_text,
        "screens": [screenshot_meta(s, f) for s, f in zip(screens, files, strict=True)],
        "expected": {
            **EXPECTED_TEMPLATE,
            "_help": (
                "first_step_keywords: any-of, case-insensitive, matched against the spoken "
                "reply. forbidden_keywords: none may appear. point_box: "
                '{"screen": 1, "x0": 0, "y0": 0, "x1": 100, "y1": 40} in screenshot image '
                "pixels (see screen*.jpg dimensions); screen is 1-based as in the labels. "
                "min_steps: the model's STEP total must be at least this."
            ),
        },
    }


def capture_case(name: str, question: str, out_root: Path, delay: float) -> Path:
    # Imported here so unit tests of the pure bits don't need mss/pynput.
    from curio.active_window import get_foreground_window_title
    from curio.screen_capture import capture_all
    from curio.window_context import describe_windows

    if delay > 0:
        print(f"capturing in {delay:g}s - arrange your windows now...")
        time.sleep(delay)
    screens = capture_all()
    windows_text = describe_windows()
    title = get_foreground_window_title()

    directory = out_root / name
    directory.mkdir(parents=True, exist_ok=True)
    for i, shot in enumerate(screens):
        (directory / f"screen{i + 1}.jpg").write_bytes(shot.jpeg_bytes)
    data = build_case_json(name, question, windows_text, title, screens)
    (directory / CASE_FILE).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture a Curio eval case.")
    parser.add_argument("--name", required=True, help="case folder name, e.g. bg-chrome-max")
    parser.add_argument("--question", required=True)
    parser.add_argument("--delay", type=float, default=5.0, help="seconds before capturing")
    parser.add_argument("--cases", type=Path, default=Path("eval_cases"))
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.name):
        print("error: --name may only contain letters, digits, '-', '_' and '.'", file=sys.stderr)
        return 2
    directory = capture_case(args.name, args.question, args.cases, args.delay)
    print(f"saved {directory}")
    print(f"next: fill in the \"expected\" section of {directory / CASE_FILE}")
    print("      (keywords, optional point_box in screenshot pixels, optional min_steps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
