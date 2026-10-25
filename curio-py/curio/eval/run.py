"""Replay eval cases against the configured model.

    python -m curio.eval.run [--cases eval_cases] [--repeat 3] [--label baseline]
    python -m curio.eval.run --compare eval_results/a.json eval_results/b.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from curio.clients.openai_llm_client import parse_openai_sse_lines, to_openai_messages
from curio.eval.case import EvalCase, load_cases
from curio.eval.request import build_request
from curio.eval.scoring import overall, parse_reply, score_reply, score_to_dict, summarize_case
from curio.prompts import is_howto_question

DEFAULT_MAX_TOKENS = 1024  # CompanionManager calls send() without max_tokens


class EndpointUnreachable(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSettings:
    base_url: str
    model: str
    api_key: str
    temperature: float | None
    point_coords: str
    max_tokens: int = DEFAULT_MAX_TOKENS


def load_settings(config_path: Path | None = None) -> ModelSettings:
    """Read model settings from the user's real config (same file the app uses)."""
    from platformdirs import user_config_dir

    from curio.config import Config, ConfigError

    if config_path is None:
        config_path = Path(user_config_dir("Curio", appauthor=False, roaming=True)) / (
            "config.toml"
        )
    try:
        config = Config.from_path(config_path)
    except ConfigError as exc:
        raise SystemExit(f"error: {exc}") from exc
    if config.local is None:
        raise SystemExit(f"error: {config_path} must set backend = \"local\" to run the eval")
    local = config.local
    return ModelSettings(
        base_url=local.llm_base_url.rstrip("/"),
        model=local.llm_model,
        api_key=local.llm_api_key,
        temperature=local.llm_temperature,
        point_coords=local.point_coords,
    )


async def stream_completion(
    client: httpx.AsyncClient, settings: ModelSettings, messages: list[dict], system: str
) -> tuple[str, float | None, float]:
    """Return ``(text, ttft_seconds, total_seconds)`` for one streamed request."""
    body: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        "stream": True,
        "messages": to_openai_messages(messages, system),
    }
    if settings.temperature is not None:
        body["temperature"] = settings.temperature
    headers = {"authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}

    text = ""
    ttft: float | None = None
    buf = b""
    start = time.perf_counter()
    try:
        async with client.stream(
            "POST", f"{settings.base_url}/chat/completions", json=body, headers=headers
        ) as response:
            if response.is_error:
                detail = (await response.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(f"server returned {response.status_code}: {detail[:300]}")
            async for chunk in response.aiter_bytes():
                buf += chunk
                complete, sep, buf = buf.rpartition(b"\n")
                if not sep:
                    continue
                for fragment in parse_openai_sse_lines(complete):
                    if ttft is None:
                        ttft = time.perf_counter() - start
                    text += fragment
        for fragment in parse_openai_sse_lines(buf):
            if ttft is None:
                ttft = time.perf_counter() - start
            text += fragment
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise EndpointUnreachable(
            f"cannot reach the model at {settings.base_url} - is the VPN up and the SSH "
            f"tunnel running? ({exc})"
        ) from exc
    return text, ttft, time.perf_counter() - start


async def run_case(
    client: httpx.AsyncClient, settings: ModelSettings, case: EvalCase, repeat: int
) -> list[dict]:
    messages, system = build_request(case, settings.point_coords)
    howto = is_howto_question(case.question)
    runs: list[dict] = []
    for _ in range(repeat):
        try:
            reply, ttft, total = await stream_completion(client, settings, messages, system)
        except EndpointUnreachable:
            raise
        except Exception as exc:  # noqa: BLE001 - record and keep going
            runs.append({"error": str(exc)})
            continue
        parsed = parse_reply(reply, case.screens, settings.point_coords)
        score = score_reply(parsed, case.expected, howto=howto)
        runs.append(
            {
                "reply": reply,
                "ttft_s": ttft,
                "total_s": total,
                "point": parsed.point,
                "step": parsed.step,
                "total_steps": parsed.total_steps,
                "score": score_to_dict(score),
            }
        )
    return runs


async def run_all(
    settings: ModelSettings, cases: list[EvalCase], repeat: int, label: str
) -> dict:
    results: dict[str, dict] = {}
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for case in cases:
            print(f"running {case.name} x{repeat} ...", file=sys.stderr, flush=True)
            runs = await run_case(client, settings, case, repeat)
            results[case.name] = {
                "question": case.question,
                "summary": summarize_case(runs),
                "runs": runs,
            }
    summaries = {name: r["summary"] for name, r in results.items()}
    return {
        "label": label,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": settings.model,
        "base_url": settings.base_url,
        "temperature": settings.temperature,
        "repeat": repeat,
        "overall": overall(summaries),
        "cases": results,
    }


# --- formatting -----------------------------------------------------------


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def _sec(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}s"


def _table(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    lines = [
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
        for row in [header, ["-" * w for w in widths], *rows]
    ]
    return "\n".join(lines)


def format_results(result: dict) -> str:
    header = ["case", "pass", "kw", "point", "steps", "formed", "ttft", "total", "err"]
    rows = []
    for name, case in result["cases"].items():
        s = case["summary"]
        rows.append(
            [
                name, _pct(s["pass_rate"]), _pct(s["keyword_rate"]), _pct(s["point_rate"]),
                _pct(s["steps_rate"]), _pct(s["well_formed_rate"]),
                _sec(s["median_ttft_s"]), _sec(s["median_total_s"]), str(s["errors"]),
            ]
        )
    o = result["overall"]
    rows.append(
        [
            "OVERALL", _pct(o["pass_rate"]), "", "", "", "",
            _sec(o.get("median_ttft_s")), _sec(o.get("median_total_s")), "",
        ]
    )
    title = f"{result['label']} ({result['model']}, repeat={result['repeat']})"
    return f"{title}\n{_table(header, rows)}"


def _delta(a: float | None, b: float | None, *, pct: bool) -> str:
    if a is None or b is None:
        return "-"
    d = (b - a) * (100 if pct else 1)
    return f"{d:+.0f}pp" if pct else f"{d:+.2f}s"


def format_comparison(a: dict, b: dict) -> str:
    header = ["case", "pass A", "pass B", "delta", "ttft A", "ttft B", "total A", "total B"]
    rows = []
    for name in sorted(set(a["cases"]) | set(b["cases"])):
        sa = a["cases"].get(name, {}).get("summary")
        sb = b["cases"].get(name, {}).get("summary")
        g = lambda s, k: s[k] if s else None  # noqa: E731
        rows.append(
            [
                name, _pct(g(sa, "pass_rate")), _pct(g(sb, "pass_rate")),
                _delta(g(sa, "pass_rate"), g(sb, "pass_rate"), pct=True),
                _sec(g(sa, "median_ttft_s")), _sec(g(sb, "median_ttft_s")),
                _sec(g(sa, "median_total_s")), _sec(g(sb, "median_total_s")),
            ]
        )
    oa, ob = a["overall"], b["overall"]
    rows.append(
        [
            "OVERALL", _pct(oa["pass_rate"]), _pct(ob["pass_rate"]),
            _delta(oa["pass_rate"], ob["pass_rate"], pct=True),
            _sec(oa.get("median_ttft_s")), _sec(ob.get("median_ttft_s")),
            _sec(oa.get("median_total_s")), _sec(ob.get("median_total_s")),
        ]
    )
    return f"A = {a['label']}   B = {b['label']}\n{_table(header, rows)}"


# --- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay Curio eval cases.")
    parser.add_argument("--cases", type=Path, default=Path("eval_cases"))
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--label", default="run")
    parser.add_argument("--out", type=Path, default=None, help="result JSON path")
    parser.add_argument("--config", type=Path, default=None, help="config.toml (default: app's)")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--only", nargs="*", help="run only these case names")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"))
    args = parser.parse_args(argv)

    if args.compare:
        a, b = (json.loads(p.read_text(encoding="utf-8")) for p in args.compare)
        print(format_comparison(a, b))
        return 0

    cases = load_cases(args.cases) if args.cases.is_dir() else []
    if args.only:
        cases = [c for c in cases if c.name in args.only]
    if not cases:
        print(f"error: no cases found in {args.cases}", file=sys.stderr)
        return 2
    empty = [c.name for c in cases if c.expected.is_empty]
    if empty:
        print(f"warning: no expectations filled in for: {', '.join(empty)}", file=sys.stderr)

    settings = load_settings(args.config)
    settings = ModelSettings(**{**settings.__dict__, "max_tokens": args.max_tokens})
    try:
        result = asyncio.run(run_all(settings, cases, args.repeat, args.label))
    except EndpointUnreachable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = args.out or Path("eval_results") / (
        f"{args.label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(format_results(result))
    print(f"\nsaved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
