# Curio eval cases

A replayable benchmark: each case is a frozen screen state + question. The runner
sends it to the model exactly like the app's first how-to turn, scores the reply,
and records time-to-first-token (TTFT) and total time. Use it to tune the demo
scenarios and to get a before/after number (change prompt or model, re-run, compare).

All commands run from `curio-py/`.

## 1. Capture a case

```
uv run python -m curio.eval.capture --name bg-chrome-max --question "how do I change my desktop background?" --delay 5
```

Arrange your windows during the delay (the capture takes all monitors, the open-window
block and the foreground title, like the app). This writes `eval_cases/bg-chrome-max/`
with `screen1.jpg` (...) and `case.json`.

## 2. Fill in expectations

Edit the `expected` section of `case.json`:

| key | meaning |
| --- | --- |
| `first_step_keywords` | any-of list; at least one must appear in the spoken reply (case-insensitive) |
| `forbidden_keywords` | none of these may appear |
| `point_box` | optional `{"screen": 1, "x0":..,"y0":..,"x1":..,"y1":..}` in screenshot image pixels (open `screen1.jpg`, 1-based screen as in the label) |
| `min_steps` | optional; the model's `[STEP:1/N]` must have N >= this |

A run passes when it is well-formed (has `[POINT:...]` or `[POINT:none]`, and `[STEP:k/N]`
for how-to questions) and every expectation you set holds. Unset expectations are skipped.

## 3. Run

```
uv run python -m curio.eval.run --repeat 3 --label baseline
```

Uses model, base URL, temperature and `point_coords` from your real
`%APPDATA%\Curio\config.toml` (`backend = "local"`; override with `--config`). Needs
the SSH tunnel up. Prints a per-case table (pass rate, median TTFT / total) and saves
`eval_results/<label>-<timestamp>.json`. `--only name1 name2` runs a subset.

## 4. Compare

```
uv run python -m curio.eval.run --compare eval_results/baseline-....json eval_results/tuned-....json
```

## Suggested demo scenarios (10-15)

1. `bg-chrome-max` - change desktop background with a maximized Chrome (expect: minimize first)
2. `bg-clear-desktop` - same question, desktop visible (expect: right-click the desktop)
3. `dark-mode-settings` - Settings app open, "turn on dark mode"
4. `dark-mode-nothing-open` - same, no Settings open (expect: open Start/Settings)
5. `excel-pivot` - Excel with data, "how do I make a pivot table?"
6. `excel-sum` - "how do I add up this column?"
7. `explorer-new-folder` - File Explorer, "how do I make a new folder?"
8. `dialog-blocking` - a modal dialog open over the task (expect: deal with the dialog first)
9. `wifi-connect` - taskbar visible, "how do I connect to wifi?"
10. `screenshot-snip` - "how do I take a screenshot of part of my screen?"
11. `two-monitors` - target on the second screen (checks `point_box.screen`)
12. `word-bold-heading` - Word, "how do I make this a heading?"
13. `chrome-bookmark` - "how do I bookmark this page?"
14. `taskmgr-kill` - "how do I close a frozen app?"
15. `volume-mute` - "how do I mute my computer?"

`example-*` cases here are synthetic placeholders showing the format; delete them once
you have real captures.
