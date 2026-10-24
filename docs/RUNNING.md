# Running Curio

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
