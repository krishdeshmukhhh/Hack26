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

A blue triangle appears next to your cursor and an icon in the system tray.

### 4. Use it

1. Click on a normal window (not an admin PowerShell).
2. **Hold Ctrl+Alt**; the triangle becomes a waveform.
3. Ask your question out loud, then **release**.
4. A bubble next to the triangle says "thinking…", then shows the answer as
   it's spoken. The triangle flies to whatever it's describing, and the
   bubble's title names it.

Press Ctrl+Alt while it's talking to interrupt. Tray menu → **History** has
the full transcript.

**Step-by-step walkthroughs.** Ask a how-to question, for example "how do I
change my wallpaper?" or "walk me through exporting this video". Instead of
listing every step, Curio gives **one step at a time**:

1. It says step 1, flies to where you need to click, and the bubble shows
   "step 1 of 4 · …".
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
| Walkthrough stops after the first step | The model gave a one-step answer (`[STEP:1/1]`) or no step tag. Ask "what's next?" with Ctrl+Alt, or rephrase as "walk me through…". |
| Bubble shows "something went wrong" | The message says what to check. It's also in the log. |

Debug logging: set `log_level = "DEBUG"` in `config.toml`. **This also logs
every key you press**, so set it back to `INFO` afterwards and clear the log.

## Cloud mode (optional)

The original setup (Claude + AssemblyAI + ElevenLabs through a Cloudflare
Worker) still works with `backend = "cloud"`. It needs three API keys and a
deployed Worker; see the "Quick start" section of the main [README](../README.md).
