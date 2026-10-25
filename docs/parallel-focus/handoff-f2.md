# Handoff F2 → F4: focus policy

Branch `feat/focus-policy`. Package: `curio/focus_policy/`. Behaviour and
rules are in [docs/focus-policy.md](../focus-policy.md).

**No contract changes, no new config keys required, no new dependencies.**
Optional config keys are suggested below.

## Constructors

```python
from curio.focus_policy import (
    AdaptiveFocusPolicy, PolicySettings, QuietHours, SessionTally, NOT_A_DISTRACTION,
)

AdaptiveFocusPolicy(
    *,
    clock: Callable[[], datetime] = <utc now>,
    settings: PolicySettings | None = None,          # defaults below
    interaction_frequency: float | Callable[[], float] = 0.5,  # 0..1, read on every decision
    model: ModelCall | None = None,                  # only used by rephrase()
    seen_variants: Iterable[str] = (),               # persisted policy.seen_variants
)

PolicySettings(
    *,
    max_spoken_per_hour: int = 3,
    rung_spacing: timedelta = timedelta(seconds=60),
    strict_spacing_factor: float = 0.5,
    breakpoint_cap: timedelta = timedelta(minutes=2),
    snooze: timedelta = timedelta(minutes=10),
    quiet_hours: tuple[QuietHours, ...] = (),
    max_backoff: float = 8.0,
    self_paced_stretch: timedelta = timedelta(minutes=50),
    break_decline_cooldown: timedelta = timedelta(minutes=15),
    rephrase_timeout_seconds: float = 4.0,
)

QuietHours(*, start: time, end: time, tz: tzinfo | None = None)  # None = local time; may wrap midnight

SessionTally(plan: FocusPlan, *, clock: Callable[[], datetime] = <utc now>)
```

Create **one** `AdaptiveFocusPolicy` for the app's lifetime, not one per
session. False-alarm learning, the ignored backoff, the hourly limit, snooze
and seen variants are about the learner and carry across sessions. Create a
new `SessionTally` for each session.

## Methods F4 calls

| Call | When |
|---|---|
| `policy.start_session(plan) -> Intervention` | Session start. Returns the planning prompt. Resets per-session state, so call it **before** `set_context`. |
| `policy.set_context(*, where, next_action="", source="walkthrough")` | Whenever the walkthrough step or plan position changes. Used for the next automatic resume note. |
| `policy.decide(signal, plan) -> Intervention \| None` | Every `FocusSignal` from the `DriftTracker`. Synchronous and cheap. |
| `await policy.rephrase(intervention) -> Intervention` | Optional, before speaking. Same id, choices and rationale. Returns the original if there's no model, the model fails or times out, or the output is invalid. Skips `AMBIENT_CUE` (empty message). |
| `policy.record_response(intervention, response)` | Every response, including `IGNORED` on expiry. |
| `policy.begin_break()` | The learner chose a break some other way (for example "take a break" on a check-in, or a tray action). |
| `policy.set_resume_note(ResumeNote(...))` / `policy.resume_note()` | A note the learner spoke; read the current note. |
| `policy.reflection_prompt(plan) -> Intervention` | After the session-ending metacognitive prompt is answered or expires. |
| `policy.set_interaction_frequency(value)` | If the adaptive value is pushed rather than pulled. |
| `policy.drifting`, `policy.on_break`, `policy.seen_variants` | Read-only state for the timeline UI and persistence. |
| `tally.observe(signal)` | Every signal (same stream as `decide`). |
| `tally.record_intervention(intervention)` | Every intervention actually presented. |
| `tally.record_response(intervention, response)` | Every response. |
| `tally.start_break(at=None)` | Same moments as `policy.begin_break()`. Accepted `BREAK_START`s are handled automatically. |
| `tally.add_concepts(concepts)` / `tally.summary(reflection="")` | End of session → `SessionStore.save_summary`. |

## Mapping choices to responses

`InterventionResponse` can't tell choices apart, so F4 maps them:

| Choice | Response | Extra call |
|---|---|---|
| `"not a distraction"` (`NOT_A_DISTRACTION`) | `FALSE_ALARM` | `classifier.correct(sample, ON_GOAL)` |
| `"back to it"`, `"start break"`, `"thanks"`, `"answer"` | `ACCEPTED` | none |
| `"take a break"` (check-in / plan reminder) | `ACCEPTED` | `policy.begin_break()` and `tally.start_break()` |
| `"keep going"`, `"a few more minutes"`, `"skip"` | `DISMISSED` | none |
| snooze button / "not now" | `SNOOZED` | none |
| expired | `IGNORED` | none |

## Presentation notes

- `AMBIENT_CUE` has `message == ""`. Animate only, never speak. Its choices
  ("back to it", "not a distraction") can appear if the learner clicks the
  pet.
- The only `rationale` letters used are A, C, D, E and F, so the "why?" link
  can look them up directly.
- `expires_after` is set per kind (20–120 s). Expiry → `IGNORED`.
- `REVIEW` is not produced here. F4 builds it from F3's items.

## Suggested optional config (F4 decides)

```toml
[focus]
max_check_ins_per_hour = 3
snooze_minutes = 10
quiet_hours = []            # e.g. [["22:00", "07:00"]]
```

The `seen_variants` set is small (strings like `"check_in:1"`). Persisting it
(for example alongside memory settings) keeps the "new style of check-in"
notice one-time across restarts.
