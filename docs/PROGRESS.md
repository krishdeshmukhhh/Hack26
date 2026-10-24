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
  - The scripts are generic and read per-machine settings from `curio.env`.
  - They were tested locally against a fake `nvidia-smi`. That test found two bugs: `gpu_status.sh` silently exiting when a process had just ended, and a CRLF issue.

### Upgrades
- **Kokoro voice** (`tts_engine = "kokoro"`, now the default).
  - Speech starts ~0.4 s after the answer arrives, because it's spoken sentence by sentence.
  - Default onnxruntime settings were 6–9× slower once other threads were busy, so it now uses 8 threads with spinning off (0.23× real time on the laptop CPU).
  - Falls back to the Windows voice if Kokoro can't load.
- **Whisper `small.en` tried and reverted.** It took 2–5 s per question on the laptop CPU against 0.7–1.4 s for `base.en`, and transcribed our test sentence no better. The default stays `base.en`; `small.en` makes sense only with `whisper_device = "cuda"`.
- **Speech bubble** next to the triangle. The original Curio had one; the Windows port never built it.
  - Streams the answer, keeping the newest lines.
  - Titles the pointing target and walkthrough step.
  - Shows errors in plain words, including config errors at startup, which used to fail silently.
  - Checked visually with screenshots.
- **Guided walkthroughs**: one step at a time, a fresh screenshot after each click, Esc to stop. See [ARCHITECTURE.md](ARCHITECTURE.md#guided-walkthroughs).
  - Live testing showed the 30B model mostly ignores the step format when it's only in the system prompt. A short reminder appended to how-to requests fixed it: 4 of 4 runs tagged correctly, and ordinary questions stayed untagged.
  - Not yet tried by hand through a full real walkthrough.

## Current status

Working end to end, with no API keys: voice → Whisper → Qwen3-VL on the H100
→ Kokoro voice + pointing + speech bubble. Guided walkthroughs are built and
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
- **Step counts:** the model sometimes underestimates the number of steps. When it says `[STEP:1/1]` for a multi-click task, the walkthrough ends early; asking "what's next?" continues it.
- **Model quality:** the 30B model is sometimes sloppy about where things are (it called the centred Windows 11 Start button "bottom left"). Qwen3-VL-32B would be the upgrade when a full GPU is free.
