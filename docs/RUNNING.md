# Running Curio

> **Upgrading from the previous app name.** The app lives in `curio-py/` and
> runs with `uv run python -m curio`.
> - Settings and data now live in `%APPDATA%\Curio` and `%LOCALAPPDATA%\Curio`.
>   To keep your old config, memory, skills and task maps, quit the app and
>   copy the contents of the previous app's folders in `%APPDATA%` and
>   `%LOCALAPPDATA%` into those two folders before the first start.
> - Run `cd curio-py && uv sync --extra local` once to build the new virtualenv,
>   then delete the old app folder's `.venv`.
> - On the lab machine, rename your server env file to `server/curio.env`.

## Focus a screen area and ask about it

Hold **Ctrl+Alt**, press the **left mouse button**, and drag a box around what
you want to ask about. Release the mouse button to keep the blue highlighted
rectangle. You can release the modifiers during the drag. Reverse drags work;
the box stays on the display where you started and must be at least 8 by 8
physical pixels. Escape cancels a drag; a cancelled or tiny replacement keeps
the previous box.

Drawing cancels any voice recording started by that Ctrl+Alt chord. Release
the keys, then hold your configured voice shortcut again to ask a question.
Ctrl+Alt without a mouse drag still records normally; `right_ctrl` and
hands-free questions also use the selected area. Each question captures fresh
contents, and the box remains across questions. Small areas inherit the
resolution of the app's downscaled screenshot.

An ordinary left click clears the box and keeps its usual application action.
During a guided walkthrough, drawing a box does not complete the pending step;
an ordinary clearing click can complete it.

When Curio points, three light blue rings expand and fade at the exact target
over about 1.5 seconds. The pet sits beside that target. A new target replaces
the old animation. The focus box, target rings, pet and speech bubble are hidden
during screenshots and restored afterward as appropriate. Explicit coaching
screen-share buttons use the selected area too; coaching replies themselves do
not execute POINT tags.

Automated checks cover input ordering, capture cleanup, crop coordinates and
overlay lifecycle. Mixed-DPI visuals, click-through over other applications,
real microphone/TTS behavior and elevated Windows applications still need
interactive verification.

## Focus and study sessions

Focus controls are enabled by default. Choose tray **Start focus session…**, or
say “Curio, I'm doing my Excel assignment for 25 minutes” through the normal
voice input. Review the goal, duration, allowed apps, break style, strict setting
and editable if-then plans, then start. Strict mode changes reminders; it does
not block apps. The live window shows remaining time and on-goal/drift/break
totals. Use card buttons or matching spoken choices such as “not a distraction”
or “snooze”. Say “take a break” or “end the session”, or use the tray's **End
focus session**. Ending opens a summary with reflection and up to three review
questions. Due questions from earlier sessions can also be offered at startup.
**Focus history…** opens saved summaries and confirmed deletion controls.

During an active session, ordinary voice help uses the study coach's hint ladder;
walkthrough progress supplies resume notes and practised concepts. Explicit
tutorial/integral coaching modes retain their own voice routing. Focus nudges
speak only when the existing voice pipeline is idle.

Optional settings in `%APPDATA%\Curio\config.toml` (restart after editing):

```toml
[focus]
enabled = true
study_minutes = 25
break_minutes = 5
break_style = "fixed" # "fixed", "self_paced", or "none"
strict = false
max_check_ins_per_hour = 3
snooze_minutes = 10
quiet_hours = [] # e.g. [["22:00", "07:00"]], local time
model_judgments = true
sample_seconds = 2.0
drift_after_seconds = 90.0
```

`study_minutes`/`break_minutes` set the work/break cycle; session duration is
chosen separately in the start panel. `enabled = false` removes the focus tray
controls and voice hooks. Quiet hours, snooze and the hourly limit govern policy
nudges. Brief reference lookups are allowed; sustained drift triggers reminders.

**Privacy:** sampling runs only during an active focus session. Every two
seconds by default it reads the foreground app (resolved from the executable),
window title, idle seconds, input-activity count, switch flag and timestamp.
Browser title changes count as switches. Input activity counts 250 ms polling
ticks that saw new input, not individual keys or their contents. Focus sensing
does not capture screenshots, page bodies or audio. Ordinary voice help still
uses the normal microphone and screenshot pipeline.

When rules and corrections cannot classify a window, `model_judgments = true`
allows sending the goal, app and up to 300 title characters to the configured
model backend, which may be remote even with `backend = "local"` (for example,
the lab server). Set it to `false` to prevent classifier title requests.
If-then suggestions, card wording and quiz generation can still send their text
context to the model; this setting is not an offline switch.

Raw samples are not saved. In the Curio user-data directory, summaries store
goals, totals, concepts, reflections and distraction app keys in
`focus_sessions.sqlite3`; false-alarm corrections store app keys, normalized
title patterns and judgments in `focus_corrections.sqlite3`; review questions
and schedules live in `study_reviews.sqlite3`. Normalized patterns may still
contain sensitive title words. **Focus history… → Delete all history…** clears
all three stores after confirmation. It leaves ordinary memory and QSettings
wording-variant preferences intact.

Automated focus tests run from `curio-py/` with
`uv run pytest tests -k focus_session`. Manual acceptance still needs a
real foreground-app/title switch, false-alarm correction, break/return, spoken
card response, audible TTS, pet reactions, end/history/delete, restart and
shutdown on Windows, plus live-model and packaged-startup checks. See
[focus-session.md](focus-session.md) for the implementation contract.

## Hackathon preflight and evidence

See [readiness register](hackathon-readiness.md),
[demo checklist](readiness/demo/preflight-and-fallback.md) and
[presentation package](presentation/README.md). From repository root:

```powershell
curio-py/.venv/Scripts/python.exe scripts/readiness/demo/preflight.py
curio-py/.venv/Scripts/python.exe scripts/readiness/impact/summarize.py --self-test
```

Preflight checks module/file discovery only, not Qt DLL loading, devices, live
model or packaged startup. The impact self-test is simulated, not participant
data. Root `tests/readiness/` is outside the Python app's default discovery; run
it separately after the normal app suite:

```powershell
$readinessParent = Join-Path (Get-Location) 'curio-py/.readiness-tmp'
New-Item -ItemType Directory -Force $readinessParent | Out-Null
$readinessBase = Join-Path $readinessParent ([guid]::NewGuid().ToString('N'))
curio-py/.venv/Scripts/python.exe -m pytest tests/readiness -q -p no:cacheprovider --basetemp "$readinessBase"
curio-py/.venv/Scripts/python.exe -m ruff check tests/readiness scripts/readiness --config curio-py/pyproject.toml
```

Use an isolated demo server/data file for seeded maps. Skills demo now defaults
to `demo-skills.sqlite3` in the working directory; its history is SIMULATED.
Explicit `--path` can still select a personal database: choose a disposable path.
New Skills demo rows retain synthetic markers and a visible warning after restart.
Unmarked history retains unknown origin. Existing estimates are not recalculated
to remove old timeout penalties.
Do not present demo records as user outcomes or guaranteed anonymous data.

The updated map server excludes marked synthetic records from ordinary paths
and stats. Its dashboard explicitly includes them with synthetic/unknown counts.
Update the server before using the new seeder; older strict servers reject the
optional extension. Archive old demo data rather than assuming it is genuine.

The current impact pilot uses [study-plan.md](readiness/impact/study-plan.md),
`blank-results.csv` and `scripts/readiness/impact/analyze.py`. Earlier generic
templates/analyzer are retained as drafts; do not mix their schemas. From root,
run `curio-py/.venv/Scripts/python.exe -B scripts/readiness/impact/check_analysis.py`.

Latest demo native checks: eight SAPI failures with access denied, zero Qt TTS
voices and a timed-out localhost model probe. Device discovery does not establish
working audio/model access. Rehearse outside the restricted process; check actual
Windows speech/microphone permissions, English recognizer/voices and model/tunnel.
No machine permissions were changed. See [integration review](readiness/integration-review.md).

For restricted environments, run the requested app checks from `curio-py` with
the installed environment only if it already has dependencies:

```powershell
$env:UV_NO_SYNC = '1'
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
New-Item -ItemType Directory -Force .readiness-tmp | Out-Null
$readinessBase = Join-Path (Get-Location) ('.readiness-tmp/' + [guid]::NewGuid().ToString('N'))
& "$env:USERPROFILE/.local/bin/uv.exe" run pytest -p no:cacheprovider --basetemp "$readinessBase"
& "$env:USERPROFILE/.local/bin/uv.exe" run ruff check .
```

This avoids dependency resolution; it does not validate a fresh installation.
Use ordinary `uv run` when dependencies and network permissions allow it. Full
lint failures must be reported, not hidden by the scoped readiness check.

## Tutorial URL coach and live integral tutor

Launch from `curio-py` with `.venv\Scripts\python.exe -m curio` as before.
Existing backend settings apply. Local model questions, plan generation and
recognition still require the local server/tunnel. Typed exact-math checking and
built-in hints do not require a model connection.

Choose **Tutorial URL coach** or **Live integral tutor** from the tray. The window
selector/status shows which mode receives Ctrl+Alt speech. Mode changes interrupt
old work and pause an active tutorial; Resume continues its navigation. Stop,
Escape, closing the shared window or **Return to ordinary assistant** restores
normal assistance. The shared window can be reopened without restarting the app.

URL flow: paste a public HTML tutorial URL, Preview plan, review/edit the source-
attributed steps, then Start. Ask by voice or text. **That didn't work** requests
recovery advice. **Check screen (share now)** authorizes capture/submission to the
configured vision provider. **I completed it** is user confirmation; Skip is a
skip. Model screen suggestions are not independent verification. For videos,
paste an actual permitted transcript. No automatic video download/transcription,
authenticated pages, JavaScript rendering, remote PDF URLs or paywall bypass is bundled.

For a local document, choose **Choose tutorial file and preview...** beside the
URL controls. TXT, Markdown, HTML and text-based PDF are supported. The extracted
text is shared with the configured AI to generate the same reviewable plan;
references identify the filename and line/block/page. Files are limited to 2 MB,
60,000 extracted characters, 800 blocks and 100 PDF pages. Scanned PDFs need OCR
and are unsupported; Word, image and video uploads are not supported. No file is
copied into persistent memory. No extra PDF dependency is required.

Math flow: enter integrand `2*x*(x^2+1)^2`, click Start problem, then submit:

```text
u=x^2+1
du=x*dx
```

The differential should be incorrect. Request a hint, then correct/continue:

```text
du=2*x*dx
I=u^2
F=u^3/3+C
F=(x^2+1)^3/3+C
```

The final answer is verified by exact differentiation. Start related unassisted
problem offers another problem with in-app coaching disabled; a submitted final
answer is checked. Guided completion does not establish independent mastery.
Use explicit `*`. Trig/log/radical/definite integrals, variable denominators,
LaTeX and implicit multiplication are unsupported. **Capture equation (share
screen)** sends a screenshot for recognition; review/edit and explicitly confirm
before assessment. Speech asks questions, never silently submits math steps.

Neither coaching mode automatically creates persistent memories. No additional
symbolic library is required. Manual checks still needed: real public URLs,
model/vision/OCR, microphone and audible TTS interruption, tray focus, multiple
displays, close during pending work and packaged startup. See coaching-integration.md.

Step-by-step guide to running Curio against the lab GPU server, from a
cold start. For first-time server setup see [`server/README.md`](../server/README.md);
for how the pieces fit together see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## What runs where

| Piece | Runs on | Model |
|---|---|---|
| Curio app (hotkey, mic, screenshots, cursor overlay) | Your Windows laptop | — |
| Speech-to-text | Laptop CPU | Whisper via faster-whisper (`whisper_model`) |
| Vision + answer | Lab GPU server, through an SSH tunnel | Qwen3-VL-30B-A3B-Instruct-FP8 via vLLM |
| Voice | Laptop CPU | Kokoro neural voice (`tts_engine = "kokoro"`), or the Windows voices (`"system"`) |

No API keys are needed for any of these.

## One-time laptop setup

1. Install **Python 3.12** and **[uv](https://docs.astral.sh/uv/)**.
2. Clone and install (the long-paths setting is needed on Windows):
   ```powershell
   git clone -c core.longpaths=true https://github.com/krishdeshmukhhh/Hack26.git
   cd Hack26\curio-py
   uv sync --extra local
   ```
3. Run it once (`uv run python -m curio`), then quit from the tray icon. That
   creates `%APPDATA%\Curio\config.toml`. The first run also downloads
   the Whisper model (~150 MB) and the Kokoro voice (~350 MB) in the
   background, so give it a few minutes on first start. Edit the config:
   ```toml
   backend = "local"

   [local]
   llm_base_url = "http://localhost:8000/v1"
   llm_model = "Qwen/Qwen3-VL-30B-A3B-Instruct-FP8"   # must match SERVED_MODEL_NAME on the server
   llm_api_key = "<contents of the server's api_key file>"
   point_coords = "norm1000"                         # Qwen3-VL's coordinate format
   whisper_model = "base.en"                         # "small.en" is more accurate but 2-5 s slower on CPU
   tts_engine = "kokoro"                             # or "system" for Windows voices
   tts_voice = ""                                    # kokoro: e.g. "af_heart", "am_michael", "bf_emma"
   ```
   Every option is documented in [`curio-py/config.example.toml`](../curio-py/config.example.toml).
4. Install **FortiClient** for the OSU VPN.
5. Optional: set up an SSH key so the tunnel doesn't ask for a password every time:
   ```powershell
   ssh-keygen -t ed25519
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <you>@ece-cnc197130s.coeit.osu.edu "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
   ```

## Every session

### 1. Start the model server

SSH in (with the VPN connected) and check for a free GPU:

```bash
ssh <you>@ece-cnc197130s.coeit.osu.edu
cd ~/Hack26/server
./gpu_status.sh
```

If a GPU says `IDLE yes`:

```bash
tmux new -d -s curio "$PWD/serve.sh"
tail -f "$(ls -t /local/scratch/$USER/Project26/curio/logs/vllm-*.log | head -1)"
```

Wait for `Application startup complete` (3–6 minutes; the weights load from a
network drive), then press Ctrl+C to stop watching. The server keeps running in
tmux. Note the `PORT=` line at the top of the log; it's 8000 unless that was
taken. Then:

```bash
./test_vision.sh    # should print PASS
```

### 2. Open the tunnel (laptop)

Open a **normal** PowerShell window (not "Run as administrator", see
[Troubleshooting](#troubleshooting)) and run:

```powershell
ssh -N -L 8000:localhost:<PORT> <you>@ece-cnc197130s.coeit.osu.edu
```

After the password it prints nothing. That means it's working. Leave the
window open; closing it closes the tunnel.

Check it from another window:

```powershell
curl.exe -H "Authorization: Bearer <api key>" http://localhost:8000/v1/models
```

You should get JSON naming the model.

### 3. Run Curio (laptop)

```powershell
cd Hack26\curio-py
uv run python -m curio
```

An animated fox appears next to your cursor and an icon in the system tray.
Use tray menu > **Pet** to select Fox, Cat, Red Panda or Ferret. Selection applies
immediately and persists across restarts. A triangle indicates asset-load fallback.

### Walkthrough learning and the shared map

On by default and local only. Guided walkthroughs are logged; model-reported
completions become recorded paths. These are not independently verified task
results. A per-concept model estimates appropriate help; mastery is not a
knowledge test. Timeouts and cancellations do not update knowledge estimates.
Tray menu > **Skills…** opens the skill map.

```toml
[learning]
enabled = true
share_walkthroughs = false   # tray > "Share walkthroughs anonymously" saves this
sync_url = ""                # e.g. "http://192.168.1.20:8765"; empty = no server
```

To share paths between laptops, run the map server on one machine (it's
standard library only):

```powershell
cd Hack26\curio-py
uv run curio-map-server --host 0.0.0.0 --port 8765 --data map.json
uv run curio-map-seed --url http://127.0.0.1:8765 --users 40   # optional demo data
```

Set `sync_url` on every laptop and restart Curio. Laptops pull the map at
startup and after each push. Only laptops with sharing on push. With a
server configured, tray > **Open stuck map** opens the dashboard, which shows
where people get stuck. Allow port 8765 through Windows Firewall on the
server machine. See [map-sync.md](map-sync.md), [task-map.md](task-map.md)
and [skills.md](skills.md).

### 4. Use it

1. Click on a normal window (not an admin PowerShell).
2. **Hold Ctrl+Alt**; the pet becomes attentive and a waveform appears.
3. Ask your question out loud, then **release**.
4. The companion shows a small spinner while it thinks, then answers out
   loud.
5. If it's talking about something on screen, the companion goes there and a
   little blue pill pops up ("right here!", "found it!"…). The classic
   triangle flies over in an arc; a pet walks over and marks the spot with a
   ring. Then it returns to your cursor. With the triangle, moving the mouse
   during the return flight snaps it back straight away.

   Pick the look in the tray menu under **Pet**: fox (default), cat, red panda
   or ferret. If the pet's artwork can't load, Curio falls back to the
   triangle.

Press Ctrl+Alt while it's talking to interrupt. Tray menu → **History** has
the full transcript.

**Step-by-step walkthroughs.** Ask a how-to question, for example "how do I
change my wallpaper?" or "walk me through exporting this video". Instead of
listing every step, Curio gives **one step at a time**:

1. It says step 1, flies to where you need to click, and the pill shows
   the step, e.g. "click this! (1/4)". It stays there until you click.
2. **Do the step** (click where it pointed). Your click tells Curio you're
   done. It takes a fresh screenshot and tells you step 2, based on what's
   on screen now.
3. This repeats until the last step.

Press **Esc** to stop a walkthrough, or Ctrl+Alt to ask something else. It
also gives up after 2 minutes without a click. Any left click counts as
"done", so avoid clicking elsewhere mid-walkthrough.

### 5. Stop everything

- Curio: tray icon → Quit (or Ctrl+C in its window).
- Tunnel: Ctrl+C in the tunnel window.
- **Server: `tmux kill-session -t curio`** on the workstation. Do this every
  time; the GPU is shared.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Ctrl+Alt does nothing | **An Administrator window has focus.** Windows hides keystrokes in admin windows from normal apps. Click a normal window first, and open your terminals without "Run as administrator". If it still does nothing, check that you're on the latest code: an older version got stuck after typing capital letters. |
| Triangle flashes red | The request failed. Usually the tunnel closed, the VPN dropped, or the server stopped. Look in `%LOCALAPPDATA%\Curio\Logs\curio.log`. |
| Log says `cannot reach LLM server at http://localhost:8000/v1` | Same as above: check the VPN, the tunnel window, and `tmux ls` on the server. |
| Tunnel window spams `channel 2: open failed: connect failed: Connection refused` | The tunnel is up but nothing is listening on the server's port. The server is still loading or crashed; check its log. |
| `bind: Address already in use` when opening the tunnel | Something on the laptop already uses 8000. Use `-L 8001:localhost:<PORT>` and set `llm_base_url = "http://localhost:8001/v1"`. |
| It mishears you | Try `whisper_model = "small.en"` (more accurate, but adds 2–5 s per question on CPU), check Windows → Privacy → Microphone, and make sure the right mic is the default. |
| The cursor points at the wrong spot | Check `point_coords` matches the model (`norm1000` for Qwen3-VL). Run `./test_vision.sh` on the server: if it passes, the problem is on the laptop side. |
| No sound | Check the volume and default output device. If Kokoro failed to load, the log says why and Curio uses the Windows voice instead. |
| Voice sounds robotic | That's the Windows voice: Kokoro is off (`tts_engine = "system"`) or failed to load (see the log). |
| It answers in one go instead of step by step | The question didn't sound like a how-to (often Whisper mishearing it). Start with "how do I…" or "walk me through…". The log line `walkthrough: waiting on step 1` confirms a walkthrough started. |
| Walkthrough doesn't move on | Curio waits for a **left** click after each step. A right-click doesn't count, so right-click as told, then left-click the menu item. |
| A red pill appears next to the triangle | Something failed; the pill says what to check (VPN, tunnel, API key, config). Details are in the log. |
| I don't want the triangle on screen all the time | Tray icon → untick **Show Curio**. It then appears only while you're using it and fades out a second after. |

Debug logging: set `log_level = "DEBUG"` in `config.toml`. **This also logs
every key you press**, so set it back to `INFO` afterwards and clear the log.

## Cloud mode (optional)

The original setup (Claude + AssemblyAI + ElevenLabs through a Cloudflare
Worker) still works with `backend = "cloud"`. It needs three API keys and a
deployed Worker; see the "Quick start" section of the main [README](../README.md).

## Hands-free mode (local backend)

Restart Curio to load the feature, then enable tray > **Hands-free: "Hey Curio"**.
It defaults to off; the tray choice persists in Windows QSettings, alongside
Show Curio. It requires `backend = "local"`, the existing local dependencies,
a working microphone and an installed Windows English SAPI speech recognizer.
There is no new Python package, service account, API charge or wake-model download.

1. Say **"Hey Curio"** ("Okay Curio" also works).
2. Pause until the listening waveform appears, then ask your question.
3. Stop speaking for about **1.2 seconds** to submit. If people or a TV are
   talking, say **"Curio, send"** (or "Curio, done") to submit explicitly.
   Say **"Curio, cancel"** to discard the recording. Curio uses its normal
   screenshot, model, voice and pointing pipeline.

Ctrl+Alt continues to work and takes over an active hands-free recording.
Esc cancels that recording. No question within five seconds cancels activation;
recordings are capped at 30 seconds. Disabling the tray option stops wake
listening and cancels a hands-free recording, but does not interrupt an answer
already processing or playing. Voice interruption during playback is not included;
use Ctrl+Alt instead.

Wake recognition uses a small Windows SAPI command grammar on its own thread.
Standby audio is processed locally by Windows, never queued for Whisper, saved or
uploaded by Curio. While recording, the native grammar switches to send/cancel
commands; the wake phrase is inactive. Native recognition is suspended while
transcribing, calling the model and speaking. Its worker waits without polling
while suspended; the endpoint timer also stops during processing/playback. After
an answer there is an 800 ms cooldown before wake listening resumes. Cancelled
hands-free audio is discarded without running Whisper. Turning hands-free off
closes its native recognizer; when never enabled, no wake thread is created.

This version deliberately uses **wake phrase, pause, question**. Speaking the
whole sentence without a pause can lose the beginning of the question. Endpoint
detection uses the Silero speech model already bundled with faster-whisper,
on a background worker with a one-second rolling window and a coalesced queue.
It runs only during hands-free capture and distinguishes speech from ordinary
non-speech noise. It cannot identify your voice separately from a TV or another
speaker: **use "Curio, send" in that environment**, or Ctrl+Alt. Test with
your actual microphone and environment. Keep
Windows' default recording device consistent with the microphone used by Curio.
The wake recognizer explicitly binds a Windows speech input token matching
Curio's PortAudio input name (including truncated device names). With one
speech input it uses that device. An ambiguous multi-device match fails visibly.
If native speech initialization fails, the toggle turns off and an error pill
explains what to check; push-to-talk remains available. The original cloud
backend retains push-to-talk because its streaming transcription can end turns
early during pauses.

Automated checks cover endpoint bounds, cancellation without inference, manual
takeover, idle PCM exclusion, stale wake events, playback gating and a mocked
end-to-end local turn with speech and POINT preserved. Optional native checks
verify the real Windows grammar, emulated and synthesized-audio recognition,
actual live microphone stream progress, worker shutdown and report process CPU time
(with Qt harness polling paused
during the measurement):

```powershell
$env:CURIO_TEST_SAPI = "1"
uv run pytest -q -s tests/test_hands_free_native.py
Remove-Item Env:CURIO_TEST_SAPI
```

These checks briefly open the local microphone without saving/uploading audio.
They do not measure real-person wake accuracy or full voice-response latency.
Before relying on it, test your own pronunciation, quiet/noisy conditions, headset
and speakers, restart persistence, Ctrl+Alt/Esc, and a packaged executable. CPU
overhead is small but not guaranteed zero; recognition is suspended during answers
to keep it out of the existing critical path.

If an older build's toggle is checked but nothing happens, restart Curio to load
the explicit microphone binding fix. The earlier `AudioInput=None` assignment
left in-process SAPI without an input on this host; simulated recognition still
passed despite zero live microphone frames. Logs now record the selected wake
microphone, recognizer readiness and wake activation, without recording ambient
speech. The new live-input check catches that failure.

## Pet settings

Open Settings from the tray and add/edit this top-level table, separate from
[local]. Restart after changing behavior settings; tray species selection is
immediate. No new runtime dependencies or asset downloads are needed.

```toml
[pet]
species = "fox"                 # fox, cat, red-panda, ferret
profile = "auto"                # auto, playful, reserved, relaxed, energetic
reduced_motion = false
playful_idle = true
jump_frequency = 1.0            # 0 disables; valid 0..5
jump_height = 0.0               # reserved 0..64 pixels; no effect on supplied sheets
jump_speed = 1.0                # multiplier, valid 0.25..4
sleep_after_seconds = 45.0     # valid 10..3600
```

The pet pauses briefly (0.25-0.65 seconds depending on profile), then walks toward
the latest cursor position. Far-away catch-up now accelerates more aggressively
and finishes within a five-second pursuit budget, including hesitation, for a
stationary cursor destination. Long chases can include occasional hops,
with cooldowns preventing continuous jumping. All four pets use their own jump
clips during pursuit and can play a single cute hop after arriving near the
cursor. Arrival hops never interrupt active AI interactions. Small cursor movements near an
arrived pet leave it resting. It may hop during pursuit or play while idle,
then settles into sleep after 45 seconds by default. Move the cursor or use
push-to-talk to wake it. POINT movement starts immediately.

If your existing config contains `sleep_after_seconds = 120`, it remains 120;
change it to 45 and restart to use the shorter sleep delay. Quit from the tray
and run `uv run python -m curio` again to load behavior updates.

Profiles work with any species; auto selects the species default. Reduced motion
uses static state frames and direct movement, disabling autonomous jumps and idle
play while preserving audio waveforms. Current artwork already contains vertical
motion, so no additional jump arc is applied. Concerned/error gestures are existing
animation fallbacks; automatic security-warning detection is not implemented.

### Pet verification

Run `uv run pytest` and `uv run ruff check .` from curio-py. New Qt tests use the
offscreen platform and need no microphone or GPU. For manual review, select each
pet, move the cursor, leave it idle, activate/cancel push-to-talk and request a
POINT. Verify click-through/no focus theft, monitor edges, negative origins,
mixed DPI, monitor unplug/reconnect and return from pointing. Confirm speaking
begins with audible playback rather than synthesis. Frozen executable startup
still needs manual verification; curio.spec includes the four sheets and metadata.

The initial implementation passed 138 tests with Python 3.13.5/PySide6 6.8.3.
The delayed-pursuit refinement now passes 156 tests on Python 3.12.15 using the
project environment. Continue using the documented Python 3.12 setup.
This host's newest Qt wheel failed with a DLL/procedure error; verification used
6.8.3. If Qt fails to import, rebuild the environment and check conflicting Qt
DLLs on PATH. No project interpreter requirement was changed.

## Continuous learning and memories

If pytest reports `PermissionError` for `Temp/pytest-of-<user>` or access-denied
warnings for `.pytest_cache`, use a fresh temporary directory and disable pytest's
cache for that run. From `curio-py` in PowerShell:

```powershell
$testTemp = Join-Path $env:TEMP ('curio-tests-' + [guid]::NewGuid().ToString('N'))
.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp "$testTemp"
```

This bypasses the inaccessible directories without changing their permissions or
deleting them. The unique path is intentional: pytest may clear an explicitly
supplied base directory. This command passed all 295 tests on this Windows host.

The memory window is available from tray > **Memories**. Memory defaults to off.
Enable persistent memory with its checkbox; settings are saved immediately and
stored records remain when disabling it. The default database is resolved by
`platformdirs.user_data_path("Curio") / "memory.sqlite3"` (normally under
Local AppData on Windows). This database is separate from the ten-turn session
conversation buffer and curated knowledge files.

Optional settings, also shown in config.example.toml:

```toml
[memory]
enabled = false
storage_mode = "local"        # "session" keeps records only for this process
automatic_learning = "off"    # "propose" permits repeated-signal proposals
# storage_path = "C:/Users/you/AppData/Local/Curio/memory.sqlite3"
# default_expiration_days = 90
```

The checkbox changes enabled state immediately. Restart after manually editing
other configuration values. Switching storage path/mode selects another store;
records are not migrated. The persistent-memory checkbox switches session mode
to local when checked. Disabling learning retains session and local records and
keeps management operations available. It does not clear current chat history.

Say `remember that I prefer short answers` (or `I prefer detailed answers`).
Open Memories, select the pending record, and click **Approve**. Pending, rejected
and expired entries are excluded from AI context. **Save edit** returns a memory
to pending; **Reject**, **Delete memory**, **Clear all memories**, search and export
are also available. Unsaved content must be saved before approval.

`Actually, I prefer detailed answers instead` proposes a correction. Approving
it retires conflicting approved preferences; the old preference remains active
until replacement approval. `recall Python` lists relevant approved memories and
their IDs. `forget memory <UUID>` validates the exact ID and deletes it in the
application, without asking the model to execute a deletion. Ambiguous deletion
requests explain the syntax. Ordinary conversation is not saved automatically.

With automatic policy `propose`, three distinct requests expressing the same
supported preference may create one pending suggestion. No automatic approval,
background screenshot archive or model training is performed.

The memory prompt allowance defaults to 512 conservative UTF-8 byte units,
including its labels/JSON. It is separate from response tokens and history.
Exact model token counters can be supplied through the runtime API; exact live
provider token counts are not currently measured. Retrieval failures/timeouts
omit memory and preserve a normal AI response.

### Memory verification still needed on a real desktop

1. Enable memory, remember a preference, approve it, quit normally and restart.
   Confirm the approved record is listed and a live model response reflects it.
2. Correct the preference and approve the replacement; confirm the old value is
   rejected. Delete a record, restart, and confirm it stays deleted.
3. Disable memory; confirm remember requests and repeated preference signals add
   no records, and subsequent requests contain no persistent memory block.
4. Test a normal push-to-talk screenshot turn, streaming, audible TTS, POINT and
   walkthrough; interrupt during retrieval and streaming and check recovery.
5. Check tray/window focus, dialogs, resizing, mixed-DPI displays and shutdown
   while management operations are in progress. Verify actual Groq/local model
   behavior and token consumption on the providers used for the demo.

Automated coverage includes separate-process persistence, real offscreen Qt/
qasync controls, mocked provider requests and the original voice/pointer tests.
It does not replace these live desktop/audio checks.
