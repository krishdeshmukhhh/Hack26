# Progress log

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

## Current status

Working end to end: voice → Whisper → Qwen3-VL on the H100 → Windows voice +
pointing, with no API keys.

## Next up

In priority order:
1. **Text bubble** next to the cursor showing the answer as it streams, plus a
   label at the pointing target. The original Curio had one; the Windows port
   never built it.
2. **Guided multi-step walkthroughs:** one step at a time, a fresh screenshot
   after each of your clicks, and the cursor flying to each step.
3. **Kokoro voice** (local, much more natural than the Windows voices), spoken
   sentence by sentence so it starts sooner.
4. **Whisper `small.en`** by default for better accuracy.

Later: one-click startup script (tunnel + app), on-screen error messages,
higher-resolution screenshots for small UI elements, and a knowledge base for
the demo app.

## Known issues

- **Cloud mode:** pausing mid-question can split it into two turns (see the review above).
- **Config errors** only show in the log; the app looks normal but does nothing.
- **Duplicate errors:** an LLM failure is reported twice (the client's signal and the manager's `except`).
- **Shared GPUs:** our GPUs are shared and can be taken at any time; there's no automatic fallback.

## Animated pets ? 2026-10-24

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
