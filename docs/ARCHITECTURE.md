# Architecture

Curio is a Python + PySide6 system-tray app. It uses `qasync` to run
asyncio on Qt's event loop, so network I/O never blocks the UI.

## One voice turn

```
 Ctrl+Alt down          release              transcript            answer streamed           done
──────┬────────────────────┬────────────────────────┬──────────────────────────┬───────────────┬──
 IDLE │ LISTENING          │ PROCESSING             │ RESPONDING               │ IDLE, or
      │ mic → PCM buffer   │ STT finishes           │ LLM streams into bubble  │ GUIDING if a
      │ (waveform shown)   │ hide overlays          │ parse STEP + POINT tags  │ walkthrough
      │                    │ screenshot all screens │ fly cursor to target     │ step is open
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
| `ui/response_bubble.py` | Speech bubble that follows the triangle: streamed answer, target/step title, errors. |
| `ui/window_effects.py` | Win32 setup shared by both overlays (click-through, no Windows 11 border or shadow). |
| `click_watcher.py` | Global left-click listener used to advance walkthroughs. |
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
   `response_annotated(label, k, N)` feeds the bubble's title.
2. If `k < N`, the manager stores the step, starts `ClickWatcher`, and after
   speaking enters **GUIDING**: the companion stays on the target.
3. The next left click → `PROCESSING` → wait 0.8 s for the UI to react →
   a normal turn with the text "i did step k. what's next?" and a **fresh
   screenshot**, so each step is grounded in the current screen.
4. It ends on the final step (`k == N`), an answer without a STEP tag,
   Esc, Ctrl+Alt, an error, or 2 minutes without a click.

The 30B model often skips the STEP tag if it's only described in the system
prompt. So requests for how-to questions (`is_howto_question`) and every
continuation get a one-line reminder (`walkthrough_reminder`) appended. The
reminder goes into that request only, not into the stored history. In live
tests this took first-step tagging from 1 in 3 runs to 4 in 4.

## Voice

`KokoroTTSClient` splits the answer into sentences and synthesises the next
one while the current one plays, so speech starts about 0.4 s after the
answer arrives. onnxruntime is limited to 8 threads with busy-wait spinning
off; with the defaults, synthesis was 6–9× slower once other threads were
busy. Model files download to `%LOCALAPPDATA%\Curio\models\kokoro` on
first use.

## Model server

vLLM runs on one GPU of a lab workstation, bound to `127.0.0.1` with an API
key, reached from the laptop through `ssh -L 8000:localhost:8000`. See
[`server/README.md`](../server/README.md).

## Tests

```powershell
cd curio-py
uv run pytest        # 110 tests, no network or GPU needed
uv run ruff check .
```

The parsers, config validation, coordinate mapping, message conversion,
Whisper buffering, hotkey stuck-key handling, the bubble's text wrapping,
Kokoro's chunking and fallback, and the full walkthrough flow (with fake
clients) are unit-tested. The overlay rendering, audio devices and live
servers aren't.
