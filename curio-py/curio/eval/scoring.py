"""Pure parsing + scoring of one model reply (no network)."""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass

from curio.eval.case import Expected
from curio.point_mapper import map_point_to_screen
from curio.point_parser import parse_concepts_tag, parse_point_tag, parse_step_tag
from curio.screen_capture import ScreenshotImage

_POINT_NONE_RE = re.compile(r"\[POINT:none\]\s*$")


@dataclass(frozen=True)
class ParsedReply:
    spoken: str
    has_point_tag: bool  # POINT:x,y or POINT:none present
    point: tuple[int, int, int] | None  # (screen 1-based, x, y) in image pixels
    step: int | None
    total_steps: int | None


@dataclass(frozen=True)
class Score:
    well_formed: bool
    keyword_pass: bool | None  # None = no expectation of that kind
    point_pass: bool | None
    steps_pass: bool | None
    passed: bool


def parse_reply(reply: str, screens: list[ScreenshotImage], point_coords: str) -> ParsedReply:
    """Parse with the app's own parsers and mapper (same order as _run_turn)."""
    without_step, step = parse_step_tag(reply)
    without_concepts, _ = parse_concepts_tag(without_step)
    spoken, tag = parse_point_tag(without_concepts)
    has_point = tag is not None or bool(_POINT_NONE_RE.search(without_concepts))
    point = None
    if tag is not None and screens:
        coords = map_point_to_screen(tag, screens, point_coords)
        if coords is not None:
            idx = tag.screen - 1 if tag.screen and 1 <= tag.screen <= len(screens) else 0
            shot = screens[idx]
            # Invert the mapper's image->global step back into image pixels.
            x = round((coords[0] - shot.monitor_left) * shot.scale)
            y = round((coords[1] - shot.monitor_top) * shot.scale)
            point = (idx + 1, x, y)
    return ParsedReply(
        spoken=spoken,
        has_point_tag=has_point,
        point=point,
        step=step.index if step else None,
        total_steps=step.total if step else None,
    )


def point_in_box(point: tuple[int, int, int] | None, box: dict) -> bool:
    if point is None:
        return False
    screen, x, y = point
    if int(box.get("screen", 1)) != screen:
        return False
    return box["x0"] <= x <= box["x1"] and box["y0"] <= y <= box["y1"]


def score_reply(parsed: ParsedReply, expected: Expected, *, howto: bool = True) -> Score:
    text = parsed.spoken.lower()
    keyword_pass: bool | None = None
    if expected.first_step_keywords or expected.forbidden_keywords:
        has_any = not expected.first_step_keywords or any(
            k.lower() in text for k in expected.first_step_keywords
        )
        has_bad = any(k.lower() in text for k in expected.forbidden_keywords)
        keyword_pass = has_any and not has_bad
    point_pass = point_in_box(parsed.point, expected.point_box) if expected.point_box else None
    steps_pass = (
        parsed.total_steps is not None and parsed.total_steps >= expected.min_steps
        if expected.min_steps
        else None
    )
    well_formed = parsed.has_point_tag and (not howto or parsed.step is not None)
    checks = [well_formed, keyword_pass, point_pass, steps_pass]
    return Score(
        well_formed,
        keyword_pass,
        point_pass,
        steps_pass,
        passed=all(c is not False for c in checks),
    )


def score_to_dict(score: Score) -> dict:
    return asdict(score)


def rate(values: list[bool | None]) -> float | None:
    """Pass rate over applicable (non-None) values, or None if none apply."""
    applicable = [v for v in values if v is not None]
    return sum(applicable) / len(applicable) if applicable else None


def summarize_case(runs: list[dict]) -> dict:
    """Aggregate one case's run dicts (each with ``score``, ``ttft_s``, ``total_s``)."""
    ok = [r for r in runs if not r.get("error")]
    ttfts = [r["ttft_s"] for r in ok if r.get("ttft_s") is not None]
    totals = [r["total_s"] for r in ok if r.get("total_s") is not None]
    return {
        "runs": len(runs),
        "errors": len(runs) - len(ok),
        "pass_rate": (sum(r["score"]["passed"] for r in ok) / len(runs)) if runs else None,
        "keyword_rate": rate([r["score"]["keyword_pass"] for r in ok]),
        "point_rate": rate([r["score"]["point_pass"] for r in ok]),
        "steps_rate": rate([r["score"]["steps_pass"] for r in ok]),
        "well_formed_rate": rate([r["score"]["well_formed"] for r in ok]),
        "median_ttft_s": statistics.median(ttfts) if ttfts else None,
        "median_total_s": statistics.median(totals) if totals else None,
    }


def overall(case_summaries: dict[str, dict]) -> dict:
    """Totals across cases, weighting every run equally."""
    total_runs = sum(s["runs"] for s in case_summaries.values())
    passed = sum(round((s["pass_rate"] or 0) * s["runs"]) for s in case_summaries.values())
    ttfts = [s["median_ttft_s"] for s in case_summaries.values() if s["median_ttft_s"] is not None]
    totals = [
        s["median_total_s"] for s in case_summaries.values() if s["median_total_s"] is not None
    ]
    return {
        "cases": len(case_summaries),
        "runs": total_runs,
        "pass_rate": passed / total_runs if total_runs else None,
        "median_ttft_s": statistics.median(ttfts) if ttfts else None,
        "median_total_s": statistics.median(totals) if totals else None,
    }
