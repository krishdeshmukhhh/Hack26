# Architecture

Curio is a Python + PySide6 system-tray app. It uses `qasync` to run
asyncio on Qt's event loop, so network I/O never blocks the UI.

## One voice turn

```
 Ctrl+Alt down          release              transcript            answer streamed           done
──────┬────────────────────┬────────────────────────┬──────────────────────────┬───────────────┬──
 IDLE │ LISTENING          │ PROCESSING             │ RESPONDING               │ IDLE, or
      │ mic → PCM buffer   │ STT finishes           │ parse STEP + POINT tags  │ GUIDING if a
      │ (waveform shown)   │ hide overlay           │ fly to target + pill     │ walkthrough
      │                    │ screenshot all screens │ speak the answer         │ step is open
      │                    │ LLM answers (spinner)  │                          │
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
| `ui/companion_widget.py` | The buddy, matching macOS Curio: triangle (idle/speaking), waveform (listening), spinner (thinking), arc flights, point-and-return, launch greeting, transient show/hide. |
| `ui/flight.py` | Pure geometry for flights: bezier arc, duration, rotation, scale, follow and landing offsets. |
| `ui/pointer_bubble.py` | Small blue pill typed out letter by letter ("right here!", "hey! i'm curio"), red for errors. |
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
   The companion flies there with `hold=True` and a "(k/N)" suffix on its pill.
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

## Matching macOS Curio

The overlay follows the original's `OverlayWindow.swift` and
`CompanionManager.swift`:

| Behaviour | Value |
|---|---|
| Follow offset from cursor | +35, +25 px |
| Answer text on screen | none: spinner while thinking, then speech only |
| Flight | quadratic bezier bowing up by min(20% of distance, 80 px); smoothstep easing; 0.6–1.4 s (distance/800); triangle faces its travel direction and swells to 1.3× mid-flight |
| Landing | target +8, +12 px |
| Pointer pill | random phrase from "right here!", "this one!", "over here!", "click this!", "here it is!", "found it!"; typed 30–60 ms per character; pops in from 0.5× with a glow; holds 3 s, fades 0.5 s, flies back |
| Return flight | cancelled if the mouse moves >100 px; snaps back to following |
| Launch | fade in over 2 s, then "hey! i'm curio" for 2 s |
| Show Curio off | appears on push-to-talk, hides 1 s after speech and pointing finish |
| History | last 10 exchanges, tags stripped |
| Colour | `#3380FF` |

Deliberate differences: errors show a short red pill (the original speaks a
canned message), and walkthrough steps hold at the target until clicked.
The onboarding video, email capture, analytics and permissions panel aren't
ported.

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
Whisper buffering, hotkey stuck-key handling, flight geometry, pill text,
Kokoro's chunking and fallback, and the full walkthrough flow (with fake
clients) are unit-tested. The overlay rendering, audio devices and live
servers aren't.
