# Architecture

## Coaching and tutoring application integration

`coaching_runtime.py` and `ui/coaching_window.py` connect the shared contract,
URL tutorial coach and live polynomial tutor. `app.py` creates a dedicated model
client using the existing backend configuration. CompanionManager model changes
propagate to coaching. No new configuration schema or symbolic dependency is
needed: the checker uses bounded AST parsing and exact Fraction arithmetic.

The tutorial widget also accepts explicitly selected local TXT/Markdown/HTML/PDF
documents. `tutorial_coach/files.py` performs bounded extraction on a worker and
`Coach.prepare_file` reuses source-attributed preview/plan construction. PDF text
comes from QtPdf with page references; scanned PDFs need a future OCR adapter.
Opaque upload IDs avoid transmitting absolute local paths. No source scripts,
linked resources or file instructions are executed; no persistent copies are made.

Tray entries select Tutorial URL coach, Live integral tutor or ordinary assistant.
The visible mode selector states which session owns push-to-talk. Only the
manager consumes final transcripts. Ordinary mode preserves memory, screenshot,
streaming, TTS and POINT behavior. Coaching routes to its service, speaks final
text and never interprets model control tags as desktop actions. Coaching work
is excluded from the ordinary conversation buffer and persistent learning.

Mode changes cancel old requests/audio, end legacy walkthroughs and pause active
tutorial navigation. Stop/Escape/window close restore ordinary mode. Request
generations reject late output and hints for older tutoring problems. Shutdown
awaits UI-owned captures and URL tasks, disconnects signals and releases Qt objects
on the GUI thread before closing the existing memory worker.

Screen sharing requires a feature button. Capture hides the Curio window/overlay
and uses the existing capture function. Equation recognition requires editable
confirmation before exact assessment. Tutorial screen comparisons are model
claims, not verified completion. See coaching-integration.md for the review and
the feature docs for input limits and unsupported cases.

Curio is a Python + PySide6 system-tray app. It uses `qasync` to run
asyncio on Qt's event loop, so network I/O never blocks the UI.

## One voice turn

```
 Ctrl+Alt down          release              transcript            answer streamed           done
──────┬────────────────────┬────────────────────────┬──────────────────────────┬───────────────┬──
 IDLE │ LISTENING          │ PROCESSING             │ RESPONDING               │ IDLE, or
      │ mic → PCM buffer   │ STT finishes           │ parse STEP + POINT tags  │ GUIDING if a
      │ (waveform shown)   │ hide overlay           │ fly to target + pill     │ walkthrough
      │                    │ screenshot all screens │ speak the answer         │ step is open
      │                    │ LLM answers (spinner)  │                          │
```

`CompanionManager` (`curio/companion_manager.py`) owns this state machine.
It doesn't know which backend is in use: each client below has the same
signals and methods in both backends.

## Modules

| Module | Role |
|---|---|
| `app.py` | Bootstraps Qt, loads config, chooses the backend's clients, wires signals. |
| `companion_manager.py` | The turn pipeline above, cancellation, conversation history. |
| `hotkey.py` | Global Ctrl+Alt detection via a pynput keyboard hook. Strict: fires only when *only* Ctrl+Alt are held. |
| `mic_capture.py` | 16 kHz int16 mono PCM from the default mic (sounddevice). |
| `screen_capture.py` | Screenshots every monitor (mss), cursor screen first, scaled to ≤1280 px, JPEG. Labels include the image size. |
| `prompts.py` | The system prompt: voice style, POINT-tag rules, coordinate format, knowledge base. |
| `point_parser.py` / `point_mapper.py` | Parse `[POINT:x,y:label:screenN]` and map it to real screen pixels. |
| `knowledge_base.py` | Per-app markdown docs chosen by the foreground window title. |
| `ui/companion_widget.py` | The buddy, matching macOS Curio: triangle (idle/speaking), waveform (listening), spinner (thinking), arc flights, point-and-return, launch greeting, transient show/hide. |
| `ui/flight.py` | Pure geometry for flights: bezier arc, duration, rotation, scale, follow and landing offsets. |
| `ui/pointer_bubble.py` | Small blue pill typed out letter by letter ("right here!", "hey! i'm curio"), red for errors. |
| `ui/window_effects.py` | Win32 setup shared by both overlays (click-through, no Windows 11 border or shadow). |
| `click_watcher.py` | Global left-click listener used to advance walkthroughs. |
| `ui/pet_widget.py` | Animated pet presentation (sprite instead of triangle) and monitor placement. Subclasses `CompanionWidget`. |
| `pets.py`, `pet_motion.py`, `pet_config.py` | Sprite timing, accelerated pursuit, behavior profiles and persisted pet preferences. |
| `ui/history_window.py`, `ui/tray_icon.py` | Transcript window and tray menu. |

### Backends (`backend` in config.toml)

| Job | `cloud` | `local` |
|---|---|---|
| Speech-to-text | `TranscriptionClient`: AssemblyAI streaming websocket | `WhisperTranscriptionClient`: buffers audio, transcribes on release with faster-whisper |
| LLM | `LLMClient`: Anthropic Messages SSE via the Worker | `OpenAICompatLLMClient`: any `/v1/chat/completions` server (vLLM) |
| Voice | `TTSClient`: ElevenLabs MP3 via the Worker | `KokoroTTSClient` (default): Kokoro on CPU, sentence by sentence, falls back to `SystemTTSClient` (Windows voices) |

The rest of the app builds requests in Anthropic format.
`OpenAICompatLLMClient.to_openai_messages` converts them: the system prompt
becomes the first message, and base64 image blocks become `image_url` data URIs.

## Pointing

The model ends its answer with `[POINT:x,y:label]` (or `[POINT:none]`).
`point_parser` strips the tag from the spoken text; `point_mapper` turns it
into screen pixels; the companion widget flies there.

The coordinate space depends on the model, set by `point_coords`:

| `point_coords` | Meaning | Used by |
|---|---|---|
| `pixel` | Pixels of the downscaled screenshot (e.g. 1280×800) | Claude, Qwen2.5-VL |
| `norm1000` | 0–1000 on each axis, independent of image size | Qwen3-VL (its native grounding format) |

`prompts.py` tells the model which space to use, and `point_mapper` must be
told the same one. The prompt and the mapper both read `config.point_coords`,
so they can't get out of sync. Qwen3-VL is much more accurate in its native
0–1000 format than when asked for pixels.

## Guided walkthroughs

For how-to questions the model answers one step at a time and tags each
answer with `[STEP:k/N]` next to its POINT tag.

1. `parse_step_tag` strips the STEP tag, then `parse_point_tag` the POINT tag.
   The companion flies there with `hold=True` and a "(k/N)" suffix on its pill.
2. Any STEP tag (whatever `N` says) makes the manager store the step, start
   `ClickWatcher`, and after speaking enter **GUIDING**: the companion stays
   on the target. `N` is display-only, because the model's totals are
   unreliable (it often says 1/1 for multi-click tasks).
3. The next left click → `PROCESSING` → wait 0.8 s for the UI to react →
   a normal turn with the text "i did step k. what's next?" and a **fresh
   screenshot**, so each step is grounded in the current screen.
4. It ends on an answer without a STEP tag (the model says the task is
   finished), Esc, Ctrl+Alt, an error, or 2 minutes without a click.

The 30B model often skips the STEP tag if it's only described in the system
prompt. So requests for how-to questions and every continuation get a
one-line reminder (`walkthrough_reminder`) appended. `is_howto_question`
matches "how do I…" phrasings, and also task requests whose "how" Whisper
dropped ("do I enable light mode…", "I want to export…"). The
reminder goes into that request only, not into the stored history. In live
tests this took first-step tagging from 1 in 3 runs to 4 in 4.

## Walkthrough learning

Every person Curio walks through a task makes the next walkthrough better.
Shared types live in `curio/learning_contract.py`. The wiring is in
`curio/learning_events/`, and `app._build_learning` constructs it.

```
answer with [STEP] ──► WalkthroughRecorder ──► StepEvent ──► SqliteEventLog
                         (pending step settled          │ walkthrough ends
                          by the next event)            ▼
                                                 WalkthroughSummary
                    ┌──────────────────────────────────┼──────────────────────────┐
                    ▼                                  ▼                          ▼
          SqliteTaskMap.record              SqliteSkillModel.observe     HttpMapSync.push
          (curio/task_map)                 (curio/skills)              (curio/map_sync,
                    ▲                                  ▲                  sharing on only)
                    └── merge(pull()) ◄────────────────┴── step_difficulty ───┘
```

- **Tags.** Walkthrough answers end with `[POINT:…] [STEP:k/N] [CONCEPTS:a, b]`.
  `parse_concepts_tag` takes the concepts tag from anywhere in the answer
  (one to three app-independent skill names, normalised with `concept_key`).
  Like the other tags it's stripped from speech, history and the display,
  even half-streamed.
- **Outcomes.** The first STEP answer starts a recorder keyed on
  `app_key(window title)` and `task_key(question)`. Each answer leaves a
  pending step with its instruction, the element at 0..1 fractions of the
  screenshot, its concepts and its assistance (`POINTED` with a point,
  `HINTED` without). The next event settles it:
  - higher step index: `SUCCEEDED`
  - same or lower index: `RETRIED`
  - tagless answer: `SUCCEEDED`, walkthrough completed
  - Esc, a new question or an error: `ABANDONED`
  - two minutes without a click: `TIMED_OUT`

  `CompanionManager._end_walkthrough(outcome)` is the single exit, and
  `_step_assistance` is the hook for hands-free mode's `DID_IT`.
- **Fan-out.** `LearningServices` runs all writes as background tasks that
  log failures. Event appends, `task_map.record` and `skill_model.observe`
  run for every summary. `map_sync.push` runs only when the sharing toggle
  is on, and a successful push is followed by a pull and merge.
- **Pull ranking.** The server lists the best path first within each task,
  but the task map prefers the highest `verified_count`. `rank_by_pull_order`
  therefore clamps every later path for a task below the first one before
  merging, so an outdated path with many old verifications can't win.
- **Per request.** This covers how-to questions and walkthrough continuations
  only. `task_map.find` supplies the path, which WS2's `format_for_prompt`
  renders in the active POINT coordinates. Steps with unknown difficulty get
  the crowd's value, and hard steps are called out. The skill model then
  gives an assistance level for the path's concepts (or the current step's),
  mapped to one prompt line. `NONE`/`HINTED` means a spoken hint with
  `[POINT:none]`; `DID_IT` means small steps, pointing at each. Its
  `prompt_context` sentence is added too. Everything goes into that request
  only, as untrusted reference data, never into stored history. The lookup
  is capped at 1.5 s and fails soft.
- **Privacy.** The event log, task map and skill model are local SQLite
  files under `%LOCALAPPDATA%\Curio`. `summary_to_wire` drops ids,
  timestamps and window titles, and the server rejects unknown keys.
  Difficulty for the skill model comes from map sync first, then this
  machine's own history (`FallbackDifficulty`).

## Voice

`KokoroTTSClient` splits the answer into sentences and synthesises the next
one while the current one plays, so speech starts about 0.4 s after the
answer arrives. onnxruntime is limited to 8 threads with busy-wait spinning
off; with the defaults, synthesis was 6–9× slower once other threads were
busy. Model files download to `%LOCALAPPDATA%\Curio\models\kokoro` on
first use.

## Matching macOS Curio

The overlay follows the original's `OverlayWindow.swift` and
`CompanionManager.swift`:

| Behaviour | Value |
|---|---|
| Follow offset from cursor | +35, +25 px |
| Answer text on screen | none: spinner while thinking, then speech only |
| Flight | quadratic bezier bowing up by min(20% of distance, 80 px); smoothstep easing; 0.6–1.4 s (distance/800); triangle faces its travel direction and swells to 1.3× mid-flight |
| Landing | target +8, +12 px |
| Pointer pill | random phrase from "right here!", "this one!", "over here!", "click this!", "here it is!", "found it!"; typed 30–60 ms per character; pops in from 0.5× with a glow; holds 3 s, fades 0.5 s, flies back |
| Return flight | cancelled if the mouse moves >100 px; snaps back to following |
| Launch | fade in over 2 s, then "hey! i'm curio" for 2 s |
| Show Curio off | appears on push-to-talk, hides 1 s after speech and pointing finish |
| History | last 10 exchanges, tags stripped |
| Colour | `#3380FF` |

Deliberate differences: errors show a short red pill (the original speaks a
canned message), and walkthrough steps hold at the target until clicked.
The onboarding video, email capture, analytics and permissions panel aren't
ported.

## Model server

vLLM runs on one GPU of a lab workstation, bound to `127.0.0.1` with an API
key, reached from the laptop through `ssh -L 8000:localhost:8000`. See
[`server/README.md`](../server/README.md).

## Tests

```powershell
cd curio-py
uv run pytest        # includes offscreen pet tests; no network or GPU needed
uv run ruff check .
```

The parsers, config validation, coordinate mapping, message conversion,
Whisper buffering, hotkey stuck-key handling, flight geometry, pill text,
Kokoro's chunking and fallback, the full walkthrough flow (with fake
clients), and the pet UI's offscreen rendering and mocked interaction
lifecycles are unit-tested. Physical audio devices, live servers and
multi-monitor desktop behavior aren't.

## Animated pets - approved design and implementation

The design and mappings were approved and implemented on
`codex/animated-pet-design`. The details below record the design; actual status
and verification limits are listed next.

### Delayed pursuit refinement

Following now behaves as a small character deciding to catch up, rather than an
exponential cursor attachment. Profiles pair delay/speed: playful 0.4s/190px/s,
reserved 0.6s/155px/s, relaxed 0.65s/135px/s, energetic 0.25s/230px/s. These are data
settings shared by all species. The widget timer continues updating destinations
while the pet hesitates, walks and hops; there are no queued movement commands.
Idle variations are more frequent and new configurations sleep after 45 seconds.
Explicit existing sleep settings are preserved. Sleep is entered only after arrival;
optional play never wakes a sleeping pet, and user activity restores following.

The refinement passes 156 tests on Python 3.12.15, including actual widget timer
integration. The inspected Qt snapshots are in pet-review/delayed-pursuit-preview.png
(with a shortened 10-second sleep threshold for the preview only).

### Implemented status

- `ui/pet_widget.py` extends CompanionWidget, retaining click-through, Windows
  transparency and waveform drawing. It renders cached 32x32 sprites at 2x scale
  with the existing triangle as an asset-load fallback.
- `pets.py` provides catalog, elapsed-time player and behavior controller.
  Profiles are data; current cursor destination updates throughout hops, without
  a queue or added vertical arc. Jump speed scales both behavior and frame clocks.
- `pet_config.py` validates [pet] preferences. Tray > Pet changes species and
  persists only that setting, preserving comments and unrelated configuration.
  Switching preserves streaming, speaking and the pointing lifecycle.
- First text delta and actual TTS playback are distinct inputs. Cancellation
  cancels pending synthesis; stale coroutine completion cannot reset a newer turn.
- Pointing displays an arrival ring, holds 800 ms and resumes following independent
  of speech. The marker is not visible during most travel. Security warning is an
  injectable event only; automatic detection is not included.
- Jump height is reserved for future external-arc clips; no effect on supplied
  artwork. Cat sleep/speaking and other gestures remain expressive fallbacks.
- All 138 tests pass with Python 3.13.5/PySide6 6.8.3 in this host's test venv.
  The declared project requirement remains Python 3.12. Changed-file lint passes.
  See pet-review/implemented-preview.png for 24 inspected actual Qt render states.
  Physical click-through, mixed-DPI pointing, audio timing, display hot-unplug and
  frozen executable startup still require manual verification.

### Scope and approach

Replace the triangle with one selectable pet while preserving the waveform,
click-through overlay, screenshot hiding, cursor following, pointing, interruption,
and backend contracts. Keep Qt Widgets and qasync. Alternatives considered were
embedding playback and behavior directly in CompanionWidget (smaller initial edit,
more coupled logic) or separating playback and behavior (recommended). A new
rendering framework would duplicate working window and platform integration.

CompanionWidget retains window ownership and painting. Add a validated sprite
catalog, a frame player, and a behavior/movement controller. The catalog describes
asset paths, explicit frames, per-frame durations, loop/one-shot policy, facing,
anchors, jump phases and displacement policy. The player advances frames; it
never moves windows. The controller chooses actions and owns ground position,
destination and optional jump displacement. Behavior profiles are data; there
must be no species-specific behavior branches. Asset-specific clip assignments
belong in the catalog.

No new runtime dependency is needed. Use cached QPixmap frames and integer-scale
nearest-neighbor drawing. Retain a fixed cell origin rather than tightly cropping
each frame. Ship sheets and metadata inside the existing package and include them
in wheel/PyInstaller data. Root source sheets remain untouched.

### Sprite inspection and assignments

All sheets have alpha transparency and a 32x32 grid. Coordinates below are
one-based row and column numbers. The labeled sheets and interactive player are
in [pet-review/index.html](pet-review/index.html); their proposed mapping data is
in [pet-review/proposed-mappings.json](pet-review/proposed-mappings.json).
These are review artifacts, not a runtime catalog. Visual inspection establishes
the poses and occupied cells; action names and timing are proposed interpretations
because no artist labels or frame timing were supplied.

| Action | Fox | Cat | Red Panda | Ferret |
|---|---|---|---|---|
| Idle | R1 C1-5 | R1 C1-4 | R1 C1-6 | R1 C1-8 |
| Walk | R3 C1-8 | R5 C1-8 | R3 C1-8 | R3 C1-8 |
| Run | walk, faster | R6 C1-8 | walk, faster | R4 C1-8 |
| Jump | R4 C1-11 | R9 C1-7 | R4 C1-8 | R6 C1-8 |
| Attentive | R2 C1-5 | R2 C1-4 | R2 C1-6 | R2 C1-8 |
| Thinking | idle, slower | R4 C1-4 | idle, slower | idle, slower |
| Text responding | R2 C6-9 | R2 C1-4 | R2 C1-6 | R2 C1-8 |
| Speaking | text responding | R3 C1-4 | text responding | text responding |
| Error / concerned | R5 C1-5 | R8 C1-6 | R5 C1-5 | attentive, once |
| Settle | R7 C1-7 | sleep directly | R6 C1-8 | R9 C1-8 |
| Sleep / rest | R6 C1-6 | R7 C1-4 | R7 C1-8 | R8 C1-8 |
| Wake | reversed settle | R9 C1-7 | reversed settle | reversed settle |

Fallback assignments communicate state through existing gestures; they are not
lip synchronization or dedicated thinking/security animations. Cat R3 is a
grooming gesture used as an expressive speaking fallback. Cat R7 is a low resting
pose, not a confirmed closed-eye sleeping cycle. Ferret has no convincing neutral
standing loop separate from its tail/stance cycles; use the calmer R1 cycle and
hold C1 if its movement feels too busy. Reverse-settle wake clips are proposals
for reuse, not additional source animations. Idle variations choose attentive,
reaction or settle/wake gestures only when their meaning fits a quiet idle.

#### Jump inspection

| Pet | Takeoff | Airborne / extension | Landing and recovery | Proposed frame durations |
|---|---|---|---|---|
| Fox | R4 C1-3, low preparation | C4-6, elevated/extended | C7-10, crouch; C11 grounded | 90,80,70,70,80,70,70,80,80,90,100 ms |
| Cat | R9 C1-2, upright launch | C3-4, extended body | C5-7, low recovery | 100,90,100,100,90,100,120 ms |
| Red Panda | R4 C1-2, rising | C3-4, upright extension | C5-6, low landing; C7-8 grounded | 100,90,100,90,80,90,100,110 ms |
| Ferret | R6 C1-2, rearing launch | C3-5, rotating/extended | C6, low impact; C7-8 standing | 90,80,90,90,80,90,100,110 ms |

These phase labels and jump identities are visually inferred candidates pending
animated review, not confirmed artist assignments. Changing vertical body extent
does not prove a complete ground-relative jump arc. Approve a candidate only if
playback shows recognizable takeoff, an airborne interval and grounded landing;
otherwise disable it or revise the mapping. Cat R9 also
changes from sitting to standing: show the complete sequence rather than assuming
a seamless running loop. Ferret R5 shrinks/disappears downward and R7 emerges;
exclude both from ordinary jumps. R6 is the complete acrobatic candidate.

All four candidates already move body pixels vertically within their cells.
Default additional arc height is therefore zero for all four. Never recenter each
frame, which would erase the drawn motion. A future catalog may enable a modest
external arc after visual verification. Height settings affect only clips allowing
external displacement; they cannot amplify baked motion. Playback speed scales
the entire jump, including controller phases, using the same elapsed action clock.
The player offers adjustable timing for review; it does not claim artist timing.

### State and event integration

Keep VoiceState as the existing orchestration state. Add presentation events rather
than adding sleeping, jumping or speaking to that enum. Manager adapters carry a
turn generation ID so cancelled/old text, TTS, and pointing callbacks cannot
change the new turn. Text responding begins on the first nonempty response delta,
not on entry into the current RESPONDING state, which precedes streaming.

| Trigger | Behavior |
|---|---|
| LISTENING | Cancel optional play, wake immediately, attentive clip and existing microphone waveform. |
| PROCESSING | Thinking/wait fallback, no optional jumps. |
| First text delta | Responding fallback; speaking remains false. |
| TTS starts | Speaking fallback independently of text; preserve output waveform. |
| TTS finishes | Clear speaking; resume current turn/pointing state, or idle if complete. |
| POINT parsed | Set explicit target, use walk/run with precise target marker; no optional hops during important pointing. |
| Target arrival | Hold marker briefly (proposed 800 ms), then return toward the latest cursor destination, independent of TTS duration. |
| Cancellation | Clear turn effects, pointing and pending play; return to current listening state or cursor following. |
| Error | Brief reaction (at most 800 ms), then recompute current state rather than blindly setting idle. |
| Security warning | Concerned fallback, with priority over optional play and normal presentation. |
| Extended inactivity | Settle/rest only outside active interactions. |
| Cursor movement / push-to-talk returns | Wake if available, immediately resume following/attentiveness; wake never delays interaction. |

Both TTS clients already expose playback_started/playback_finished, but app.py
does not connect them to the companion. Their start semantics need tightening:
cloud currently emits after play() rather than actual PlayingState; system TTS
also treats Synthesizing as started. Normalize actual playback onset for this
feature and explicitly clear speaking on stop, error and cancellation, since
normal-finish signals do not cover every exit. Add generation guards at the
adapter/task boundary, not merely by reading the latest ID when a stale callback
arrives.

No security-warning producer exists in the current app. Provide a typed event
input and verify it with an injected event; detection/policy is out of scope and
must not be inferred from arbitrary LLM text. A visible concerned gesture is a
presentation response, not a security detector.

### Movement, arbitration and jumping

Use one Qt update timer and monotonic elapsed time. Movement updates the latest
cursor destination every tick, including while jumping; there is no destination
queue or jump queue. Ground position uses PursuitMotion: a single profile-based
reaction delay (0.25-0.65 seconds), then a profile walking speed (135-230 logical pixels/second). Distance beyond
240 pixels increases desired speed up to a 10x distance boost. A five-second
pursuit budget, including hesitation, can raise speed further for very large
distances. Acceleration is at least 12x base speed per second; deceleration is
20x. Remaining distance/time enforces progress after ramp-up, without overshoot.
The budget does not restart as the destination changes. Cursor updates do not restart hesitation.
The pet stops 16 pixels from its follow destination; a 12-pixel hysteresis prevents
tiny cursor changes from dragging it around. POINT bypasses hesitation and uses
a precise 0.5-pixel arrival radius. Reduced motion uses direct placement.
Short travel walks; run may activate beyond 180 logical pixels. Facing follows
horizontal movement with a small dead zone. The motion controller reports actual travel; while hesitating the pet remains
idle rather than playing walking frames.

Traversal hops require at least 100 logical pixels of remaining travel, actual movement, a cooldown,
and a profile-weighted random decision at pursuit start or after another 160
pixels of travel, not every paint. A failed roll does not suppress the entire chase. They never reduce follow convergence or freeze the destination.
Long-distance catch-up can include hops; hopping never changes the ground pursuit
trajectory or acceleration. Cooldowns prevent continuous jumping.
PursuitMotion emits a one-tick just_arrived event after actual travel. A normal
cursor arrival can trigger one jump using the selected pet's existing jump clip,
with a separate cooldown of at least four seconds. This is suppressed for active
AI/POINT, reduced motion, disabled jumps, missing clips or an already-playing
optional action. Stationary ticks never retrigger it.
Completing a hop cannot enqueue a second one. Idle play starts only after 5 seconds
stationary; resample the next eligible interval after an action completes. Do not
replay the same optional action consecutively when alternatives exist.

Optional actions finish before returning to idle, but listening, warnings, errors
and cancellation can preempt them. On preemption remove optional displacement
without moving the ground anchor, and select the new grounded clip immediately.
Priority: cancellation/new listening and security warning, error, explicit target
movement, active AI presentation, wake, optional traversal jump, idle play, sleep.
Keep locomotion and interaction as separate inputs: walking to POINT can coexist
with speaking=true and waveform display; render locomotion while moving and
speaking at arrival. A warning gesture can coexist with cursor following.

For an enabled external arc use a bounded normalized trajectory, for example
4*h*u*(1-u), zero at launch and landing. Ground destination and arc offset are
independent. Reserve the entire sprite cell and maximum arc when clamping against
each screen's available geometry, including negative coordinates. Re-clamp on
display removal or DPI change. Screens are separate rectangles, not one enclosing
rectangle with usable gaps. Across separated displays, transfer directly between
valid screen positions rather than animating through inaccessible space. Preserve
the existing screenshot-to-Qt coordinate path; manually verify mixed-DPI pointing
before claiming it works. Pet anchor changes must not alter POINT coordinates.

### Profiles and configuration

Proposed defaults below are editable profile data, not species logic. Intervals
are seconds; hop probability is per eligible traversal opportunity.

| Default profile | Idle play interval | Hop probability | Jump cooldown |
|---|---|---|---|
| Fox / playful | 6-12 | 0.55 | 4 |
| Cat / reserved | 12-22 | 0.40 | 5 |
| Red Panda / relaxed | 9-18 | 0.45 | 5 |
| Ferret / energetic | 4-9 | 0.60 | 3 |

Initial configuration adds [pet] with species, profile, reduced_motion,
playful_idle, jump_frequency multiplier (0 disables), jump_height,
jump_speed multiplier, and sleep_after_seconds (default 45). Keep Settings as
the existing config-file entry; no new settings panel. Validate finite values,
nonnegative height/frequency and bounded playback speed; document units and limits
when implementing. Profiles can be chosen independently of species. Configuration
missing [pet] uses Fox/playful. Invalid assets fall back to the existing triangle
and a log message, without breaking voice interaction. Missing optional clips
fall back to attentive/idle; missing jump means no autonomous jump.

Reduced motion disables optional jumps, bobbing/pulses and random animated play;
use static state poses plus retained audio waveforms. Cursor tracking remains
responsive and target travel uses direct placement rather than decorative flight.
Inactivity is measured from cursor movement and interaction events, not arbitrary
keyboard logging. User return is cursor movement or push-to-talk.

### Acceptance and implementation boundaries

The mappings were approved before production work. Verify every frame rectangle and nonempty alpha, including reversed
sequences, and visually check complete takeoff/airborne/landing loops. If a
candidate is unsuitable, disable it and use walk/idle, rather than invent frames.

Implementation milestones, each followed by targeted updates to PROGRESS.md:

1. Catalog/player: validated bounds and timing, fallback handling, stable anchors,
   all four approved clips, wheel/frozen resource loading.
2. Controller: deterministic clock/RNG tests for probability, cooldown, no repeat,
   action completion, sleep/wake and configurable profiles. During a hop, moving
   the cursor must update destination on the next tick; no queued actions, no
   extra horizontal lag versus ordinary following, and zero added arc for these
   sheets. Verify reduced motion and optional missing clips.
3. Integration: first text delta versus actual TTS onset, normal finish, stop,
   errors, stale callbacks after cancellation, injected warning, POINT arrival
   and independent return. Preserve microphone/output waveforms and screenshot
   hide/restore. Mock backend events; no model server needed for these checks.
4. Windows review: click-through/no focus theft, all four pets, monitor edges,
   negative origins, display gaps, hot-unplug and mixed DPI; inspect jump feet and
   landing at normal scale. Verify no off-screen frames or ghost overlay captures.
   Run existing tests and lint with the documented Python 3.12/uv environment.

The initial environment passed 53 dependency-independent tests. After installing
dependencies, all 138 tests pass, including offscreen Qt and lifecycle tests. Physical desktop acceptance remains manual. RUNNING.md documents actual asset/config behavior. Its incorrect Kokoro/tts_engine mention has been removed.

## Continuous learning integration ? 2026-10-24

`memory_contract.py` remains the common dataclass/protocol boundary.
`app.run` constructs one `MemoryRuntime`, one `MemoryWindow` (Tray > Memories),
and passes the runtime's `ConversationMemory` to `CompanionManager`. The runtime
owns the SQLite worker, rule-based engine, serialized store operations and
post-commit change/notification callbacks on the qasync loop. Shutdown closes
subscriptions/window tasks and drains the SQLite worker.

`Config.memory` parses the optional `[memory]` table. Defaults are disabled,
local storage and automatic learning off. The UI toggle persists the memory table
using atomic file replacement while preserving unrelated parsed configuration.
Policy changes update the store and conversation adapter together and clear
session learning evidence. Session storage retains its records across an enable
toggle; changing storage path/mode opens the selected store without migrating data.

Explicit remember/preference feedback is passed to `RuleBasedLearningEngine` and
stored as pending proposals. The UI supplies Approve and Reject controls. Approval
persists the replacement before retiring conflicting memories. Re-proposing a
rejected/expired value reuses its inactive record as pending; duplicate IDs still
fail. Multi-record retirement is serialized, not crash-atomic; the shared contract
does not promise cross-method transactions. Retrieval selects the newest eligible
value for a preference key if an interrupted retirement left two approved values.

Ordinary successful user turns can supply bounded behavioral evidence only with
`automatic_learning = "propose"`; three distinct matching signals are required.
Assistant output is never evidence and conversations are not automatically archived.
Disabled settings block new learning and retrieval while explicit management
(list/edit/review/export/delete/clear) remains available. Existing session history
is retained separately from persistent memory.

Retrieval uses the store interfaces, rechecks records, includes approved global
response preferences, and renders a bounded JSON data block in the current user
message. The static system rules identify memories and external reference text
as untrusted. Memory context is never added to stored conversation history.
The application currently uses a conservative UTF-8 byte count with a 512-unit
budget, rather than installing/downloading model tokenizers. The complete rendered
block is counted. An exact provider tokenizer can be injected into `MemoryRuntime`;
exact live-provider token accounting has not been verified. Groq/local
OpenAI-compatible message conversion is unchanged.

See [memory integration review](memory-integration.md) for reviewed source groups,
verification and outstanding Git/desktop restrictions.
