# Curio

**A voice-powered AI tutor for Windows that watches your screen, answers your questions, and points at what it's talking about.**

Curio is a Windows desktop assistant for voice questions and on-screen guidance.

Built for Windows developers, creatives, and anyone learning unfamiliar software by doing instead of watching tutorials.

## How it works

1. Launch Curio. A small blue triangle appears near your cursor.
2. Open whatever software you're learning — DaVinci Resolve, Blender, Wild Apricot, anything.
3. Hold **Ctrl+Alt** and ask your question out loud.
4. Release. Curio screenshots your screen(s), sends them to Claude along with your transcribed speech, and speaks the answer back to you.
5. The companion cursor flies to the UI element Claude is describing, so your eyes go right to it.
6. Follow up with another question — Curio remembers the conversation.

## Features

- **Push-to-talk voice input** via Ctrl+Alt with live waveform visualization
- **Multi-monitor screen capture** sent to Claude for visual context
- **Text-to-speech responses** via ElevenLabs with real-time output waveform
- **Cursor guidance** — companion flies to UI elements Claude references
- **Knowledge base injection** — curated markdown docs loaded per-app based on active window, so Claude gives authoritative answers for niche software
- **Conversation memory** — 20-turn history so follow-up questions have full context
- **Interrupt support** — press Ctrl+Alt mid-response to cut the audio and ask something new
- **History window** — optional scrollable transcript accessible from the tray menu

## Prerequisites

- **Windows 10/11**
- **Python 3.12** — [download](https://www.python.org/downloads/)
- **uv** package manager — [install](https://docs.astral.sh/uv/getting-started/installation/)
- **Node.js 18+** — for deploying the Cloudflare Worker
- **Cloudflare account** (free tier) — [sign up](https://dash.cloudflare.com/sign-up)
- **API keys:**
  - [Anthropic](https://console.anthropic.com) (Claude)
  - [AssemblyAI](https://www.assemblyai.com) (speech-to-text)
  - [ElevenLabs](https://elevenlabs.io) (text-to-speech)

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/krishdeshmukhhh/Hack26.git
cd curio/curio-py
uv sync
```

### 2. Deploy the Cloudflare Worker

The Worker is a tiny proxy that holds your API keys. The app talks to the Worker, the Worker talks to the APIs. Your keys never ship in the app.

```bash
cd ../worker
npm install
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put ASSEMBLYAI_API_KEY
npx wrangler secret put ELEVENLABS_API_KEY
npx wrangler deploy
```

Copy the deployed URL (e.g. `https://your-worker.your-subdomain.workers.dev`).

### 3. Configure and run

```bash
cd ../curio-py
uv run python -m curio
```

On first run, Curio creates `%APPDATA%\Curio\config.toml`. Open it and paste your Worker URL:

```toml
worker_url = "https://your-worker.your-subdomain.workers.dev"
```

Restart Curio. The blue triangle should appear near your cursor. Hold Ctrl+Alt and start talking.

### 4. Permissions

- **Microphone:** Windows Settings > Privacy > Microphone — ensure access is enabled
- **SmartScreen:** If Windows shows a warning on first run, click "More info" then "Run anyway"

## Build a standalone exe

```bash
cd curio-py
uv run pyinstaller curio.spec
```

Output: `dist/curio/Curio.exe` — runs without Python installed.

## Configuration

Edit `%APPDATA%\Curio\config.toml`:

| Field | Default | Description |
|-------|---------|-------------|
| `worker_url` | *(required)* | Your deployed Cloudflare Worker URL |
| `hotkey` | `ctrl+alt` | Push-to-talk binding. Also supports `right_ctrl` |
| `default_model` | `claude-sonnet-4-6` | Claude model for responses |
| `log_level` | `INFO` | DEBUG, INFO, WARNING, or ERROR |
| `knowledge_dir` | `%APPDATA%/Curio/knowledge/` | Path to knowledge base folder |

## Running without API keys

Set `backend = "local"` in `config.toml` to skip the Worker entirely:

- **LLM:** any OpenAI-compatible server with a vision model (for example vLLM serving Qwen3-VL), configured under `[local]`
- **Speech-to-text:** faster-whisper on your PC (`uv sync --extra local`)
- **Voice:** the built-in Windows voices

See [`server/README.md`](server/README.md) for running the model on a remote GPU cluster over SSH, and `config.example.toml` for every `[local]` option.

## Knowledge base

Curio can inject curated documentation into Claude's context based on which app is in the foreground. This turns it from a general-purpose assistant into an expert trainer for specific software.

### Setting up a KB

Create a folder per app inside your knowledge directory:

```
%APPDATA%/Curio/knowledge/
  └── wild_apricot/
      ├── _meta.toml      # maps window titles to this KB
      ├── overview.md      # always included — app overview
      ├── events.md        # topic-specific docs
      ├── membership.md
      └── email.md
```

The `_meta.toml` file tells Curio when to load this KB:

```toml
name = "Wild Apricot"
window_titles = ["Wild Apricot", "wildapricot.org"]
```

When the foreground window title contains any of the `window_titles` strings, all markdown files in that folder are injected into Claude's system prompt as authoritative reference documentation.

### Authoring KB content

Any source of markdown works. We recommend [NotebookLM](https://notebooklm.google.com/) for distilling large doc sets:

1. Upload the software's documentation, help articles, or video transcripts to NotebookLM
2. Ask it to produce focused markdown per topic area
3. Drop the `.md` files into the app's KB folder
4. Write a `_meta.toml` with window title matchers

No restart required — Curio loads KB content fresh on every turn.

## Architecture

Python + PySide6 system tray app using asyncio (via qasync). All three APIs are proxied through a shared Cloudflare Worker.

```
curio-py/               # Python source
  curio/                   # Package
    companion_manager.py      # Central state machine
    ui/companion_widget.py    # Cursor-following overlay
    clients/                  # LLM, transcription, TTS clients
    knowledge_base.py         # Per-app KB with window title matching
  tests/                    # 73 tests
  curio.spec               # PyInstaller build spec
worker/                   # Cloudflare Worker proxy
  src/index.ts              # Routes: /chat, /tts, /transcribe-token
docs/                     # PRDs and implementation plans
```

**State flow:** IDLE → LISTENING (Ctrl+Alt held) → PROCESSING (screenshots + Claude) → RESPONDING (TTS + cursor guidance) → IDLE

## Tests

```bash
cd curio-py
uv run pytest
uv run ruff check .
```
