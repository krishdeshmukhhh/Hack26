# Handoff: F1 sensing → F4

Branch `feat/focus-sensing`. Everything is in `curio-py/curio/focus_sensing/`.
Tests are `tests/test_focus_sensing_{activity,classifier,drift}.py`, and the
behaviour is described in [docs/focus-sensing.md](../focus-sensing.md). No
contract changes and no new dependencies.

## Constructors

```python
from curio.focus_sensing import (
    DriftThresholds, FakeActivitySource, RuleFirstClassifier,
    SQLiteCorrectionStore, ThresholdDriftTracker, WindowsActivitySource,
    scripted_samples,
)

# ActivitySource (a QObject; build it on the Qt main thread)
WindowsActivitySource(
    *,
    interval_seconds: float = 2.0,
    input_poll_ms: int = 250,               # 0 = no sub-polling: input_events becomes 0/1
    clock: Callable[[], datetime] | None = None,   # stamps ActivitySample.at; default UTC now
    probe: Callable[[], RawActivity] | None = None,  # tests only
    input_tick: Callable[[], int] | None = None,     # tests only
    parent: QObject | None = None,
)
FakeActivitySource(
    samples: Iterable[ActivitySample] = (),
    *,
    interval_seconds: float | None = None,  # set it to replay on a QTimer (demo)
    loop: bool = False,
    parent: QObject | None = None,
)
scripted_samples(steps, *, start: datetime, interval_seconds=2.0, input_events=3)

# Corrections store: async; SQLite runs on its own worker thread
SQLiteCorrectionStore(path: Path | str, *, clock: Callable[[], datetime] | None = None)
SQLiteCorrectionStore.default_path()        # user_data_path("Curio") / "focus_corrections.sqlite3"
#   await get(app, pattern) / put(app, pattern, judgment) / remove(app, pattern)
#   await all() / clear() / close()         # all + clear are for the history/privacy UI

# TrackClassifier
RuleFirstClassifier(
    corrections: SQLiteCorrectionStore,
    *,
    model: ModelCall | None = None,
    model_enabled: bool = True,             # also a public attribute you can change at runtime
    cache_ttl: timedelta = timedelta(minutes=30),
    model_timeout_seconds: float = 8.0,
    clock: Callable[[], datetime] | None = None,
    distractions: tuple[str, ...] = DISTRACTIONS,
    reference_sites: tuple[str, ...] = REFERENCE_SITES,
    own_apps: tuple[str, ...] = ("curio",),
)

# DriftTracker
ThresholdDriftTracker(thresholds: DriftThresholds | None = None, plan: FocusPlan | None = None)
#   .reset(plan)  .update(sample, assessment) -> list[FocusSignal]
#   .drifting: bool  .totals: DriftTotals  .plan
DriftThresholds(...)  # every field has a default; see drift.py
```

## Wiring

`assess` is async: even rules-only checks wait on the SQLite worker the first
time. Process samples **one at a time**. The tracker drops out-of-order
samples, but a queue keeps every sample:

```python
queue: asyncio.Queue[ActivitySample] = asyncio.Queue(maxsize=8)
source.subscribe(lambda s: queue.put_nowait(s) if not queue.full() else None)

async def pump(plan):
    tracker.reset(plan)
    while True:
        sample = await queue.get()
        assessment = await classifier.assess(sample, plan)
        for signal in tracker.update(sample, assessment):
            intervention = policy.decide(signal, plan)
            ...

# On InterventionResponse.FALSE_ALARM for a drift signal:
await classifier.correct(signal.sample, TrackJudgment.ON_GOAL)
```

Start the source when a session starts and stop it when the session ends.
There's no need to sample outside sessions.

`SessionSummary` can be built from `tracker.totals`: `on_goal_seconds`,
`off_goal_seconds` (you may want to add `unsure_seconds / 2`),
`break_seconds` and `drift_count`. Close the store at app shutdown with
`await store.close()`.

## Suggested config keys (`[focus]` section, for F4 to add)

| Key | Default | Maps to |
|---|---|---|
| `sample_seconds` | `2.0` | `WindowsActivitySource(interval_seconds=)` |
| `send_titles_to_model` | `true` | `RuleFirstClassifier(model_enabled=)`; the research doc's privacy switch |
| `drift_after_seconds` | `90` | `DriftThresholds(drift_after_seconds=)` |
| `return_grace_seconds` | `15` | `DriftThresholds(return_grace_seconds=)` |

## Notes

- With the default `idle_pause_seconds = 60`, passively watching a video
  stops counting as drift after a minute without input. See "Known limits"
  in docs/focus-sensing.md. Raise it if the demo needs a hands-off YouTube
  drift.
- `ActivitySample.window_title` is local data. The only place it leaves the
  machine is the classifier's model call, and only when `model_enabled` is
  true.
- No keystroke content is read anywhere. `input_events` counts 250 ms ticks
  in which `GetLastInputInfo` changed.
