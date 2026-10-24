# Progress log

## Tutorial file uploads - 2026-10-24

Added an explicit local file chooser alongside tutorial URL preview. TXT,
Markdown, HTML and text-based PDFs feed the existing attributed plan and coaching
flow. Bounds: 2 MB, 60,000 characters, 800 blocks and 100 PDF pages. Text extraction
runs off the UI thread; QtPdf needs no additional dependency. Absolute local paths
are excluded from model requests; references retain filename and source location.
No file copy or automatic persistent memory is created. Scanned/encrypted PDFs
and unsupported formats fail before model inference rather than fabricating content.

Full suite: **397 passed** on Python 3.12.15 with cache disabled and a unique
temporary base. Eight new tests cover formats/provenance, real PDF extraction,
empty/binary/oversize/invalid inputs, absent PDF text, plan reuse and the file-picker
UI flow. Scoped tutorial/upload Ruff passes. Physical native file dialog and live
provider smoke remain unverified. Previous Git permission restrictions still apply.

## Tutorial URL coach and live tutor integration - 2026-10-24

Integrated the available feature source additions into the `main` working tree
at baseline `integration snapshot`. Both named feature branch refs are absent; no branch merge
is claimed. Staging the reviewed integration failed because `.git/index.lock`
could not be created (permission denied). No integration commit was created.
Reviewed the shared contract and each package, tests and handoff before
wiring app startup, separate configured provider clients, tray entries, a shared
scrollable window, explicit active-mode selection and one transcript dispatcher.
Existing tracked memory contracts/runtime remain unchanged.

Coaching final replies use existing TTS; ordinary assistant streaming, screenshots,
memory and POINT/walkthrough behavior remain covered by their original tests.
Mode switch/Stop/Escape/close interrupt old work and restore ordinary assistance.
Late results, even from cancellation-suppressing providers, cannot replace current
work. Hints for a revised math problem are discarded. Shutdown awaits widget-owned
tasks, disconnects callbacks and destroys Qt objects on the GUI thread. An early
combined run hit a native Qt access violation; explicit lifecycle cleanup was
added and subsequent focused and full runs passed. Physical desktop shutdown
remains unverified.

Verified on Windows, Python 3.12.15:

- `uv run pytest`: **389 passed**. Existing environment selected with
  `UV_NO_SYNC=true`; UV cache redirected into the workspace. `PYTEST_ADDOPTS`
  disabled cache and selected a new unique temporary base to avoid earlier ACL
  problems. No tests excluded.
- Nine integration tests cover URL -> attributed editable preview -> start ->
  mismatched-screen recovery -> stop; a polynomial integral with an incorrect
  differential, hint/correction, exact final differentiation and independent
  practice; one voice owner and return to ordinary mode; explicit screenshot
  comparison/recognition confirmation; cancellation, stale-problem hints, UI
  reopen, disabled-memory isolation and awaited capture shutdown.
- Models, URLs, screenshots and TTS are mocked in tests. Mathematical verdicts
  use the real exact checker, not model assertions. Tutorial screen comparisons
  stay `needs_clarification` without an independent verifier.
- Changed/new coaching components and integration tests pass Ruff.
  `uv run ruff check .` still fails on **23 pre-existing violations in unchanged
  client/hotkey/geometry/test files**. No lint suppressions or unrelated fixes.
- Offscreen Qt controls and a rendered tutoring window were inspected. The
  inspection harness explicitly loaded Segoe UI because offscreen Qt exposed no
  fonts. Computer Use native-pipe discovery failed after retries/reset; no
  physical Windows UI, real microphone/audio, live model/vision or live URL smoke
  is claimed.

No additional symbolic dependency: the reviewed checker uses standard-library
bounded AST parsing and Fraction arithmetic. This slice supports polynomial
substitution only. Videos require actual supplied transcripts; JavaScript-only,
authenticated/PDF pages and automatic transcript retrieval are unsupported.
Live-provider accuracy, real capture/recognition, focus/multiple displays,
interrupting audible TTS and frozen application startup still need manual checks.
See RUNNING.md and coaching-integration.md.

What's been done on Curio for HackOhio 2026, why, and what's next.
Newest entries at the bottom of each section.

## Starting point

## 2026-10-24

### Code review
- All 73 original tests passed; `ruff` found only style issues (22, 14 auto-fixable).
- **Bug fixed: pointing accuracy.** The prompt told the model that screenshots
  are "labeled with their pixel dimensions", but the labels never included
  them, so the model was guessing the coordinate space. Labels now say
  `(image dimensions: 1280x800 pixels)`.
- Found but not fixed (cloud mode only): pausing mid-question while holding
  Ctrl+Alt makes AssemblyAI end the turn early and can start two overlapping
  answers. The local backend avoids this by transcribing once on release.

### Local backend: no API keys
Added `backend = "local"`:
- **LLM:** `OpenAICompatLLMClient`, which works with any OpenAI-compatible server (vLLM).
- **Speech-to-text:** faster-whisper on the laptop, run once when the key is released.
- **Voice:** Windows voices via `QTextToSpeech`.
- **Pointing:** `point_coords = "norm1000"`, because Qwen3-VL gives coordinates on
  a 0–1000 scale rather than in pixels (checked against Qwen's docs).
- Also fixed: a cancelled hotkey press could still start a turn afterwards.
- Verified on the laptop: Whisper transcribed a spoken test sentence exactly,
  the Windows voice played and reported finishing, and the LLM client parsed a
  stream split mid-line.

### Finding a GPU
- First assumed a Slurm cluster. It turned out the lab machines are standalone
  workstations with no scheduler, so the Slurm job script was replaced.
- **H200 box** (`ece-drf95318s`, GPUs 4–7 ours): every GPU was busy with
  another user's jobs, and `/local/scratch` was nearly full. Earlier model
  downloads there had been deleted.
- **Model choice:** Qwen3-VL-30B-A3B-Instruct-FP8. It's a mixture-of-experts
  model with about 3B active parameters, so it's fast enough for a voice
  assistant; FP8 halves its memory use (~32 GB); and the Instruct version has
  no reasoning step to strip out. Qwen3-VL-32B (dense) is the upgrade if
  quality isn't enough.
- **First launch on H200 GPU 7 crashed:** DeepGEMM JIT-compiles FP8 kernels
  with the system `nvcc`, which was 12.8, and it needs 12.9 or newer. Fix:
  `VLLM_USE_DEEP_GEMM=0`. The GPU was taken by someone else before the retry.
- **H100 box** (`ece-cnc197130s`, GPU 3 ours) is where it now runs.
  - `/local/scratch` has only ~20 GB usable (about 92 GB is free, but 5% of the disk is reserved for root), so the weights and venv went to `~/curio-models` on the home network drive.
  - Its driver supports CUDA 12.5. vLLM 0.11.0 with the torch 2.8.0 cu128 wheel works anyway through CUDA minor-version compatibility, with transformers pinned to 4.57.1.
- Lab housekeeping done on the server: `.bashrc` cache variables that pointed
  at the full scratch disk were commented out (backup kept), and the pip cache
  was purged (16.5 GB).

### End to end, verified
- A real screenshot sent through the app's own pipeline to the H100: **first
  token in 1.7 s, full answer in 2.4 s**. It described the screen correctly
  and pointed at the Windows Start button. The spoken text contradicted itself
  slightly ("bottom right… far left"), a model-quality issue.

### Bug fixed: Ctrl+Alt stopped working
- **Symptom:** the overlay appeared, but Ctrl+Alt did nothing.
- **Cause 1 (Windows behaviour):** keystrokes in an *Administrator* window are
  invisible to normal apps. The tunnel window had been opened as admin.
- **Cause 2 (code bug):** typing Shift+I and releasing Shift first is reported
  as "I" down, "i" up, so "I" stayed "held" forever. The strict "only
  Ctrl+Alt held" check never passed again.
- **Fix:** keys are now identified by their virtual-key code, and Windows is
  asked (`GetAsyncKeyState`) which keys are actually down before arming.
  There are regression tests in `tests/test_hotkey_stuck_keys.py`.
- Confirmed working by hand afterwards.

### Repo
- Pushed to [triplev06/Hack26](https://github.com/krishdeshmukhhh/Hack26),
  replacing the stock macOS Curio that was there. The previous commit is
  kept in history.
- Added server scripts (`server/`) and these docs.
  - The scripts are generic and read per-machine settings from `curio.env`.
  - They were tested locally against a fake `nvidia-smi`. That test found two bugs: `gpu_status.sh` silently exiting when a process had just ended, and a CRLF issue.

### Upgrades
- **Kokoro voice** (`tts_engine = "kokoro"`, now the default).
  - Speech starts ~0.4 s after the answer arrives, because it's spoken sentence by sentence.
  - Default onnxruntime settings were 6–9× slower once other threads were busy, so it now uses 8 threads with spinning off (0.23× real time on the laptop CPU).
  - Falls back to the Windows voice if Kokoro can't load.
- **Whisper `small.en` tried and reverted.** It took 2–5 s per question on the laptop CPU against 0.7–1.4 s for `base.en`, and transcribed our test sentence no better. The default stays `base.en`; `small.en` makes sense only with `whisper_device = "cuda"`.
- **Speech bubble** next to the triangle, streaming the whole answer. *Replaced later the same day, see "Matching macOS Curio" below.*
  - Streams the answer, keeping the newest lines.
  - Titles the pointing target and walkthrough step.
  - Shows errors in plain words, including config errors at startup, which used to fail silently.
  - Checked visually with screenshots.
- **Guided walkthroughs**: one step at a time, a fresh screenshot after each click, Esc to stop. See [ARCHITECTURE.md](ARCHITECTURE.md#guided-walkthroughs).
  - Live testing showed the 30B model mostly ignores the step format when it's only in the system prompt. A short reminder appended to how-to requests fixed it: 4 of 4 runs tagged correctly, and ordinary questions stayed untagged.
  - Not yet tried by hand through a full real walkthrough.

### Matching macOS Curio
Read the original's Swift source to match its overlay exactly; see the table in
[ARCHITECTURE.md](ARCHITECTURE.md#matching-macos-curio).
- The original never shows answer text (`CompanionResponseOverlay` is dead code), so the transcript bubble was removed.
- Pointing now uses the original's curved, rotating, swelling flight, lands just beside the target (the old code landed ~17 px left of it), and pops a typed "right here!"-style pill, then flies back.
- Waveform and spinner replace the triangle while listening and thinking, as on Mac; the triangle keeps following the cursor while speaking.
- Launch fade-in plus "hey! i'm curio"; tray **Show Curio** toggle; history trimmed to 10 tagless exchanges.
- Verified with screenshots of every state, plus 9 geometry tests.

### Merged: Mac-style overlay + animated pets
`merge-pets` combines `mac-parity-overlay` with PR #1 (`codex/animated-pet-design`).
- The pet subclassed the old companion's internals (cursor timer, `_track_cursor`,
  pulse/breathing waveforms, `fly_to(x, y)`), which the Mac-parity rewrite removed.
  The base widget now has explicit hooks (`_advance_motion`, `_snap_to_cursor`,
  `_bubble_anchor`, `_is_pointing`) and the pet overrides those instead.
- Pets get the Mac pointer pill beside the sprite, the launch greeting, red
  error pills, the waveform and spinner, and the Show Curio toggle.
- Walkthrough steps keep the pet at the target until the click (the controller's
  normal visit is 800 ms); the pill fades when the pet's visit ends.
- Manager keeps both sides: the PR's turn generations / `speaking_changed`
  and the walkthrough flow with the spinner-until-answer timing. The pet's
  "text started" reaction now also fires during PROCESSING, since answers
  stream before RESPONDING.
- Test fakes updated to the real interfaces (`escape_pressed`, TTS playback
  signals). 167 tests pass; every pet state checked with on-screen screenshots.

## Current status

Working end to end, with no API keys: voice → Whisper → Qwen3-VL on the H100
→ Kokoro voice + Mac-style pointing. Guided walkthroughs are built and
unit-tested, and the model follows the format live, but nobody has tried a
full walkthrough by hand yet.

## Next up

In priority order:
1. **Try a full walkthrough by hand** in the demo app, and tune the prompt
   from what goes wrong.
2. **One-click startup** (`start.ps1`): open the tunnel, wait for the server,
   launch Curio.
3. **Sharper pointing:** screenshots are capped at 1280 px; Qwen3-VL can take
   1920 px for small UI elements.
4. **Knowledge base** for whatever app we demo.
5. **Speak while the answer streams** instead of after it's complete, to save
   another ~0.5 s.

## Known issues

- **Cloud mode:** pausing mid-question can split it into two turns (see the review above).
- **Config errors** only show in the log; the app looks normal but does nothing.
- **Duplicate errors:** an LLM failure is reported twice (the client's signal and the manager's `except`).
- **Shared GPUs:** our GPUs are shared and can be taken at any time; there's no automatic fallback.
- **Walkthrough clicks:** any left click counts as "step done", including a click somewhere unrelated.
- **Step counts:** the model's step totals are unreliable (it often says `[STEP:1/1]` for multi-click tasks). Fixed by ignoring the total for control flow: a walkthrough continues after each click until an answer has no STEP tag. The cost is one extra "you're done" turn at the end.
- **Mishearing:** Whisper `base.en` sometimes garbles words ("wallpaper in Windows" → "wallpaper in the model"). Running Whisper on the GPU would allow a more accurate model.
- **Model quality:** the 30B model is sometimes sloppy about where things are (it called the centred Windows 11 Start button "bottom left"). Qwen3-VL-32B would be the upgrade when a full GPU is free.

## Animated pets - 2026-10-24

Implemented on `codex/animated-pet-design` after design/mapping approval.

### Verified milestone: player and behavior
- Four packaged sheets, explicit mappings and per-frame jump timing.
- Smooth movement, randomized idle play and traversal hops, cooldowns, data-driven
  profiles, sleep/wake and reduced motion. No queued jumps or extra vertical arc.
- Tests cover frame bounds/alpha, one-shot recovery, live destinations, priority,
  cooldown, profile selection and missing-clip fallback. Slow movement counts as
  activity and sleeping pets are not awakened by optional idle scheduling.

### Verified milestone: settings and integration
- Tray > Pet switches species immediately and persists in the existing TOML file,
  preserving comments and unrelated settings. Existing configs use defaults.
- Selection preserves streaming/speaking and POINT lifecycle. Point arrival holds
  800 ms then resumes cursor following independent of TTS.
- Retained base Windows window behavior, microphone/output waveforms, capture
  hide/restore and triangle asset fallback. Separate text-streaming and actual
  playback events drive presentation; cancellation stops pending synthesis.
- Security warning has a presentation event, not automatic detection.
- Fixed existing CRLF event parsing in cloud SSE after original tests exposed the
  issue on this Windows checkout.

### Verification and remaining checks
- **138 tests pass** with Python 3.13.5/PySide6 6.8.3. Declared support remains
  Python 3.12, which was unavailable here. Scoped pet/integration Ruff checks pass; repository-wide Ruff still reports
  22 existing style issues, including two in the minimally patched SSE client.
- Inspected 24 actual offscreen Qt renders: pet-review/implemented-preview.png.
- Manual verification remains for desktop click-through/focus, real audio timing,
  full-speed animation feel, physical multi-monitor/mixed DPI, display hot-unplug
  and frozen executable startup. No live model-server check was performed.
- Cat speaking is a grooming fallback; sleep is a resting pose. Jump height is
  reserved for future external-arc clips and does not affect these four sheets.

## Whimsical pursuit refinement - 2026-10-24

Work was split in parallel into pursuit motion, behavior/profile tuning, and
widget/config integration tests. All work remains on codex/animated-pet-design.

- Replaced cursor-attached exponential convergence with PursuitMotion: a finite
  0.25-0.65 second hesitation, then walking at profile-specific speed, eased
  arrival and a resting radius. The latest destination updates during hesitation
  and hops without restarting the delay or queuing paths.
- Walking frames begin only when the pet actually travels. Idle play and hopping
  are more noticeable, with profile-specific intervals/cooldowns. POINT bypasses
  hesitation; reduced motion and important AI reactions retain their behavior.
- New configs default to sleep after 45 seconds. Existing explicit sleep settings
  remain unchanged. Verified settle, sleep and wake transitions.
- **156 tests pass with Python 3.12.15**, including new deterministic pursuit,
  shared jump/walk trajectory and actual widget timer tests. Scoped Ruff passes.
- Rendered and inspected delayed-pursuit-preview.png using actual Qt sprite
  painting. Its sleep threshold is shortened to 10 seconds for the preview only.
  Physical desktop animation feel and multi-monitor behavior remain manual checks.

## Accelerated catch-up and moving fox jumps - 2026-10-24

- Distant pursuit now accelerates smoothly up to 5x profile walking speed,
  slowing at arrival without overshoot. The existing reaction pause is retained.
- Removed the 600-pixel jump exclusion. Failed hop rolls retry after actual travel
  rather than suppressing jumps for an entire long chase. The playful profile
  uses 55% per eligible opportunity and a 4-second cooldown.
- Uses the fox's existing R4 C1-11 jump sequence, with no doubled vertical arc.
  Jump movement follows the same accelerating trajectory as walking; active AI,
  POINT and reduced-motion exclusions are preserved.
- Added regressions for acceleration, long-distance fox clip selection, returning
  cursor/no overshoot, repeated hop opportunities and cooldowns. Verification:
  160 tests pass on Python 3.12.15; scoped Ruff passes. Actual desktop speed/feel
  remains a manual check after restarting the app.

## Five-second catch-up and all-pet arrival hops - 2026-10-24

- Stronger acceleration and a five-second pursuit budget (including hesitation)
  replace the former fixed 5x catch-up limit. Progress uses remaining distance
  and time, keeps the latest target and clamps arrival without overshoot.
- Increased traversal-hop probabilities for reserved, relaxed and energetic
  profiles, so cat/red panda/ferret jumps are easier to see. All species use
  their own approved sprite clips, not a shared fox animation.
- Added one-shot cursor-arrival hops with a separate cooldown. No extra hop is
  queued behind an existing animation. AI, POINT, reduced-motion, missing-clip
  and jump-disabled exclusions remain in effect.
- Verified deadline behavior across four base speeds and 500-20,000 pixel
  distances, all four pets' traversal/arrival mappings, one-shot completion and
  interaction exclusions. Full suite: 188 tests pass on Python 3.12.15; scoped
  Ruff passes. Physical desktop animation feel still needs manual review.

### Main integration verification
Merged the accelerated pursuit and arrival hops with main's newer overlay and walkthrough changes. Resolved documentation/test conflicts while preserving both sets of behavior. All 219 application tests pass on Python 3.12.15 after integration.

## Continuous learning integration ? 2026-10-24

Integrated the available storage, learning, UI and conversation implementations
in the `main` working tree. Four separate development branch refs were not present;
the changes arrived as modified/untracked files. Reviewed those source groups and
their available summaries before connecting them. This is not a record of four
Git merges. Git index writes are denied in this environment, so no integration
commit or merge commit was created.

Added MemoryRuntime and validated memory settings parsing/persistence; wired the
real SQLite store, rule-based learning, memory window and conversation adapter in
app startup/shutdown. Resolved missing approval controls, lexical-only preference
retrieval, immutable store policy updates, and the management-while-disabled
contract discrepancy. Fixed a storage test fixture that accidentally set an update
time before its default creation time. Preserved worker-based SQLite I/O, async
cancellation, ten-turn history, provider conversion and voice/pointer contracts.

Verification on Windows / Python 3.12.15:

- `uv run pytest`: **295 passed**, including all four component suites and six
  integration tests. `UV_NO_SYNC=true` used the existing environment after uv's
  attempted dependency sync was blocked by restricted network access. UV cache
  was redirected into the workspace; uv was added to PATH from its installed path.
- Verified persistence across separate Python processes, approved preferences
  reaching a mocked AI turn, preference correction/reversal, disabled learning,
  local/session policy changes, deletion, automatic proposal gating, and startup/
  shutdown wiring. This verifies request influence, not compliance by a live model.
- Real MemoryWindow and real SQLite/learning services exercised on qasync with
  offscreen Qt: live event refresh, approve, edit/reapproval, reject, disable and
  delete. Existing suites cover export, clear, errors, stale edits, streaming,
  cancellation, screenshot construction, TTS fallback and POINT/walkthroughs.
- `uv run ruff check .`: **23 existing violations in unchanged files**. Scoped
  lint on the memory components and integration changes passes. Left unrelated
  client/hotkey/geometry/test formatting unchanged.
- Interactive Windows smoke could not run: Computer Use native pipe unavailable,
  including after retries/session reset. No physical microphone, audible TTS,
  live Groq/local server, desktop click-through or mixed-DPI test was performed.

Do not mark the memory release complete until the Windows/live-provider checklist
in RUNNING.md is performed and the available changes are reviewed/committed in a
Git-writable checkout. See memory-integration.md for remaining limitations.
