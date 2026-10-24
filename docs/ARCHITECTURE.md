# Architecture

Curio is a Python + PySide6 system-tray app. It uses `qasync` to run
asyncio on Qt's event loop, so network I/O never blocks the UI.

## One voice turn

```
 Ctrl+Alt down          release              transcript            answer streamed           done
──────┬────────────────────┬────────────────────────┬──────────────────────────┬───────────────┬──
 IDLE │ LISTENING          │ PROCESSING             │ RESPONDING               │ IDLE
      │ mic → PCM buffer   │ STT finishes           │ LLM streams text         │
      │ (waveform shown)   │ hide overlay           │ parse POINT tag          │
      │                    │ screenshot all screens │ fly cursor to target     │
      │                    │ load knowledge base    │ speak the answer         │
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
| `ui/companion_widget.py` | The cursor-following triangle, waveform and fly-to animation. |
| `ui/history_window.py`, `ui/tray_icon.py` | Transcript window and tray menu. |

### Backends (`backend` in config.toml)

| Job | `cloud` | `local` |
|---|---|---|
| Speech-to-text | `TranscriptionClient`: AssemblyAI streaming websocket | `WhisperTranscriptionClient`: buffers audio, transcribes on release with faster-whisper |
| LLM | `LLMClient`: Anthropic Messages SSE via the Worker | `OpenAICompatLLMClient`: any `/v1/chat/completions` server (vLLM) |
| Voice | `TTSClient`: ElevenLabs MP3 via the Worker | `SystemTTSClient`: Windows voices via QTextToSpeech |

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

## Model server

vLLM runs on one GPU of a lab workstation, bound to `127.0.0.1` with an API
key, reached from the laptop through `ssh -L 8000:localhost:8000`. See
[`server/README.md`](../server/README.md).

## Tests

```powershell
cd curio-py
uv run pytest        # 91 tests, no network or GPU needed
uv run ruff check .
```

The parsers, config validation, coordinate mapping, message conversion,
Whisper buffering and hotkey stuck-key handling are unit-tested. The UI, the
audio devices and live servers aren't.
