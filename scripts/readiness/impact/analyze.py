"""Offline descriptive pilot analysis. Never writes or transmits participant data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
from collections import Counter
from pathlib import Path

FIELDS = [
    "study_id", "task_id", "period", "condition", "status", "elapsed_seconds",
    "wrong_actions", "resource_switches", "interventions", "effort_1_7",
    "frustration_1_7", "notes",
]
METRICS = FIELDS[5:11]
STATUSES = {"completed", "timeout", "failed", "error", "withdrawn"}


def describe(values):
    observed = [x for x in values if x is not None]
    return {"observed": len(observed), "missing": len(values) - len(observed),
            "median": statistics.median(observed) if observed else None,
            "min": min(observed) if observed else None,
            "max": max(observed) if observed else None}


def analyze(path, synthetic=False):
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != FIELDS:
        raise ValueError("header must exactly match blank-results.csv")
    rows, seen, warnings = [], set(), []
    for line, row in enumerate(reader, 2):
        try:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("malformed row width")
            row = {k: v.strip() for k, v in row.items()}
            sid = row["study_id"]
            if not sid or sid.startswith("SYNTHETIC_") != synthetic:
                raise ValueError("ID must match real/synthetic input mode")
            period = int(row["period"])
            key = (sid, period)
            if key in seen:
                raise ValueError("duplicate participant/period")
            if period not in (1, 2, 3) or row["task_id"] not in {"A", "B", "C"}:
                raise ValueError("invalid task/period")
            condition = row["condition"]
            if condition not in {"usual", "curio", "unassisted"}:
                raise ValueError("unknown condition")
            if (period == 3) != (row["task_id"] == "C") or (
                period == 3
            ) != (condition == "unassisted"):
                raise ValueError("C/unassisted must be period 3 only")
            if row["status"] not in STATUSES:
                raise ValueError("unknown status")
            for metric in METRICS:
                value = row[metric]
                number = float(value) if value else None
                if number is not None:
                    upper = 600 if metric == "elapsed_seconds" else (
                        7 if metric.endswith("1_7") else math.inf)
                    lower = 1 if metric.endswith("1_7") else 0
                    if not math.isfinite(number) or not lower <= number <= upper:
                        raise ValueError(f"invalid {metric}")
                    if metric != "elapsed_seconds" and not number.is_integer():
                        raise ValueError(f"{metric} must be an integer")
                row[metric] = number
            if row["status"] == "timeout" and row["elapsed_seconds"] not in (None, 600):
                raise ValueError("timeout elapsed must be 600 or missing")
            if row["status"] == "completed" and row["elapsed_seconds"] == 600:
                raise ValueError("at-limit completion must be timeout under protocol")
            row["period"] = period
            seen.add(key)
            rows.append(row)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"line {line}: {exc}") from exc
    ids = sorted({r["study_id"] for r in rows})
    for sid in ids:
        participant = [r for r in rows if r["study_id"] == sid]
        measured = [r for r in participant if r["period"] < 3]
        if len(participant) != 3:
            warnings.append(f"{sid}: incomplete session; absent periods not imputed")
        if len(measured) == 2 and (
            {r["task_id"] for r in measured} != {"A", "B"}
            or {r["condition"] for r in measured} != {"usual", "curio"}
        ):
            warnings.append(f"{sid}: protocol deviation in task/condition pairing")
    def group(selected):
        return {"started": len(selected),
                "statuses": dict(sorted(Counter(r["status"] for r in selected).items())),
                "intervened_runs": sum((r["interventions"] or 0) > 0 for r in selected),
                "metrics": {m: describe([r[m] for r in selected]) for m in METRICS},
                "completed_only_elapsed": describe([
                    r["elapsed_seconds"] for r in selected if r["status"] == "completed"])}
    conditions = {c: group([r for r in rows if r["condition"] == c])
                  for c in sorted({r["condition"] for r in rows})}
    strata = {f"{c}/{t}/period{p}": group([
        r for r in rows if (r["condition"], r["task_id"], r["period"]) == (c, t, p)])
        for c, t, p in sorted({(r["condition"], r["task_id"], r["period"]) for r in rows})}
    pairs = []
    for sid in ids:
        measured = [r for r in rows if r["study_id"] == sid and r["period"] < 3]
        if (len(measured) == 2 and {r["condition"] for r in measured} == {"usual", "curio"}
                and {r["task_id"] for r in measured} == {"A", "B"}
                and all(r["status"] == "completed" and r["elapsed_seconds"] is not None
                        for r in measured)):
            by = {r["condition"]: r for r in measured}
            pairs.append({"study_id": sid,
                          "curio_minus_usual_seconds": by["curio"]["elapsed_seconds"]
                          - by["usual"]["elapsed_seconds"],
                          "curio_task": by["curio"]["task_id"],
                          "curio_period": by["curio"]["period"],
                          "interventions": [r["interventions"] for r in measured]})
    return {"data_label": "SYNTHETIC TEST ONLY" if synthetic else "USER-SUPPLIED; verify consent",
            "source": {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()},
            "participants_observed": len(ids), "warnings": warnings,
            "interpretation": "Descriptive small sample only. All-run elapsed is time spent, "
            "not time to success; timeouts censored. Completed-only times/pairs are selected. "
            "No significance, productivity percentages or causal learning claim. "
            "Missing metrics are not zero. Inspect interventions, task/order and raw notes.",
            "conditions": conditions, "task_period_strata": strata,
            "successful_pairs_only": pairs,
            "participants_without_successful_timed_pair": len(ids) - len(pairs)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--synthetic", action="store_true",
                        help="Required for separately stored SYNTHETIC_ fixture IDs")
    args = parser.parse_args()
    try:
        print(json.dumps(analyze(args.csv_path, args.synthetic), indent=2, allow_nan=False))
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"Invalid input: {exc}\n")


if __name__ == "__main__":
    main()
