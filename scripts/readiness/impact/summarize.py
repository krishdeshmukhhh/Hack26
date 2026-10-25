"""Describe a private pilot CSV; --self-test uses only simulated in-memory data."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

CONDITIONS = {"usual", "curio", "unassisted"}
STATUSES = {"completed", "timeout", "abandoned", "error"}
REQUIRED = {
    "study_id", "task_id", "period", "condition", "status", "elapsed_seconds",
    "wrong_actions", "resource_switches", "interventions", "effort_1_7", "frustration_1_7",
}


def summarize(source):
    """Reject malformed records; retain unsuccessful runs in every denominator."""
    reader = csv.DictReader(source)
    if not REQUIRED.issubset(reader.fieldnames or []):
        raise ValueError("CSV is missing required columns")
    groups = defaultdict(list)
    seen = set()
    for line, row in enumerate(reader, 2):
        try:
            key = (row["study_id"].strip(), row["task_id"].strip(), row["period"].strip())
            if not all(key) or key in seen:
                raise ValueError("blank identity or duplicate study/task/period")
            if int(key[2]) < 1:
                raise ValueError("period must be positive")
            condition, status = row["condition"], row["status"]
            if condition not in CONDITIONS or status not in STATUSES:
                raise ValueError("unknown condition or status")
            elapsed = float(row["elapsed_seconds"])
            if not math.isfinite(elapsed) or elapsed < 0 or elapsed > 600:
                raise ValueError("elapsed_seconds must be finite and within 0..600")
            counts = [int(row[name]) for name in (
                "wrong_actions", "resource_switches", "interventions",
            )]
            if any(value < 0 for value in counts):
                raise ValueError("counts must be nonnegative integers")
            for name in ("effort_1_7", "frustration_1_7"):
                if row[name] and not 1 <= int(row[name]) <= 7:
                    raise ValueError("ratings must be blank or integers within 1..7")
            seen.add(key)
            groups[condition].append((status, elapsed, counts))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"line {line}: {exc}") from exc
    results = {}
    for condition, runs in sorted(groups.items()):
        completed_times = [elapsed for status, elapsed, _ in runs if status == "completed"]
        results[condition] = {
            "started_tasks": len(runs),
            "status_counts": dict(sorted(Counter(status for status, _, _ in runs).items())),
            "all_runs_median_elapsed_seconds": statistics.median(t for _, t, _ in runs),
            "completed_only_median_seconds": (
                statistics.median(completed_times) if completed_times else None
            ),
            "wrong_actions": sum(counts[0] for _, _, counts in runs),
            "resource_switches": sum(counts[1] for _, _, counts in runs),
            "interventions": sum(counts[2] for _, _, counts in runs),
        }
    return {
        "warning": "Descriptive only. Unsuccessful elapsed times are not time to success. "
        "Inspect task/order, failures and intervention notes; no causal gain is estimated.",
        "conditions": results,
    }


def self_test():
    header = ",".join(sorted(REQUIRED)) + "\n"
    fields = sorted(REQUIRED)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for condition, status, seconds in (
        ("curio", "completed", 100), ("curio", "timeout", 600),
        ("usual", "error", 30), ("unassisted", "abandoned", 40),
    ):
        writer.writerow(dict(zip(fields, [""] * len(fields), strict=True)) | {
            "study_id": "SIMULATED", "task_id": condition + status, "period": 1,
            "condition": condition, "status": status, "elapsed_seconds": seconds,
            "wrong_actions": 0, "resource_switches": 0, "interventions": 0,
        })
    result = summarize(io.StringIO(buffer.getvalue()))["conditions"]
    assert result["curio"]["started_tasks"] == 2
    assert result["curio"]["all_runs_median_elapsed_seconds"] == 350
    assert result["curio"]["completed_only_median_seconds"] == 100
    assert result["usual"]["completed_only_median_seconds"] is None
    assert summarize(io.StringIO(header))["conditions"] == {}
    duplicate = buffer.getvalue() + buffer.getvalue().splitlines()[1] + "\n"
    for invalid in (duplicate, buffer.getvalue().replace("600", "nan")):
        try:
            summarize(io.StringIO(invalid))
        except ValueError:
            pass
        else:
            raise AssertionError("invalid simulated record accepted")
    print("SIMULATED SELF-TEST PASS: failures retained; empty/duplicate/nonfinite cases checked.")
    print("No participants were observed; no product impact was measured.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if args.csv_path:
            parser.error("self-test does not read participant files")
        self_test()
    elif args.csv_path:
        try:
            with args.csv_path.open(encoding="utf-8-sig", newline="") as source:
                print(json.dumps(summarize(source), indent=2, allow_nan=False))
        except (OSError, ValueError) as exc:
            parser.exit(2, f"Invalid observations: {exc}\n")
    else:
        parser.error("provide a private CSV path or --self-test")


if __name__ == "__main__":
    main()
