# Running Curio

Step-by-step guide to running Curio against the lab GPU server, from a
cold start. For first-time server setup see [`server/README.md`](../server/README.md);
for how the pieces fit together see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## What runs where

| Piece | Runs on | Model |
|---|---|---|
| Curio app (hotkey, mic, screenshots, cursor overlay) | Your Windows laptop | — |
| Speech-to-text | Laptop CPU | Whisper via faster-whisper (`whisper_model`) |
| Vision + answer | Lab GPU server, through an SSH tunnel | Qwen3-VL-30B-A3B-Instruct-FP8 via vLLM |
| Voice | Laptop | Windows built-in voices (`tts_voice`) |

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
   creates `%APPDATA%\Curio\config.toml`. Edit it:
   ```toml
   backend = "local"

   [local]
   llm_base_url = "http://localhost:8000/v1"
   llm_model = "Qwen/Qwen3-VL-30B-A3B-Instruct-FP8"   # must match SERVED_MODEL_NAME on the server
   llm_api_key = "<contents of the server's api_key file>"
   point_coords = "norm1000"                         # Qwen3-VL's coordinate format
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
4. It answers out loud, and the pet moves to the target, briefly marks it, then resumes following.

Tray menu → **History** shows what it heard and what it said. Press Ctrl+Alt
while it's talking to interrupt.

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
| It mishears you | Use a better Whisper model (`whisper_model = "small.en"`), check Windows → Privacy → Microphone, and make sure the right mic is the default. |
| The cursor points at the wrong spot | Check `point_coords` matches the model (`norm1000` for Qwen3-VL). Run `./test_vision.sh` on the server: if it passes, the problem is on the laptop side. |
| No sound | Check the volume and default output device. Windows voices live in Settings → Time & language → Speech. |

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
sleep_after_seconds = 120.0     # valid 10..3600
```

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

The agent verified 138 tests with Python 3.13.5/PySide6 6.8.3 because Python 3.12
was unavailable on this host. Continue using the documented Python 3.12 setup.
This host's newest Qt wheel failed with a DLL/procedure error; verification used
6.8.3. If Qt fails to import, rebuild the environment and check conflicting Qt
DLLs on PATH. No project interpreter requirement was changed.
