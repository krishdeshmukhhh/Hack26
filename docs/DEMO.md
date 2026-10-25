# Recording the demo video

The pitch demo is a screen recording. Retakes are free, so the goal is clean,
honest footage: never edit what Curio says or where it points. Re-record instead.

## 1. Before recording

- [ ] GPU tunnel up (`docs/RUNNING.md`), app running: `cd curio-py && uv run python -m curio`
- [ ] `%APPDATA%\Curio\config.toml`: `llm_model` matches the served model
      (`Qwen/Qwen3-VL-30B-A3B-Instruct-FP8`), `llm_temperature = 0.2`
- [ ] Notifications off (Focus Assist), Discord/email closed. Window titles go into
      the prompt and are visible on screen.
- [ ] Clean desktop, neutral wallpaper, display scale fixed (100% or 125%) for every take
- [ ] Warm the model: ask one throwaway question before the first take
- [ ] Each scene passes in the eval (section 4) before you film it

## 2. Shot list (about 2–3 minutes)

| # | Scene | Setup | What to say | What should happen |
|---|---|---|---|---|
| 1 | Hook (~15 s) | — | Voice-over: the problem | — |
| 2 | Obstacle (~40 s) | Chrome **maximized** over the desktop | "how do I change my desktop background?" | "minimize it first" + points at minimize, then the rest step by step |
| 3 | Real task (~40 s) | Excel open with a small table (or Settings) | "how do I insert a pivot table?" | Multi-step walkthrough; each step checks the last one worked |
| 4 | Learning + crowd (~40 s) | Map server running, dashboard seeded, two laptops | Same question on laptop B | B is guided straight through; dashboard shows the stuck step; tray > Skills… shows mastery |
| 5 | How it works (~20 s) | Diagram | Voice-over | Laptop (Whisper, Kokoro, app) → SSH tunnel → lab GPU (Qwen3-VL) · LAN map server |
| 6 | Close | — | What's next | — |

For scene 4, complete the walkthrough once on laptop A first so a verified path exists.
Two-laptop setup is in `docs/map-sync.md`. In short:

```powershell
cd curio-py
uv run curio-map-server --host 0.0.0.0 --port 8765 --data map.json
uv run curio-map-seed --url http://<server-ip>:8765 --users 40 --delay 0.1
```

Both laptops need `sync_url = "http://<server-ip>:8765"` and `share_walkthroughs = true`
under `[learning]`, then a restart. Use a phone hotspot; campus Wi-Fi isolates clients.

## 3. Recording settings

- OBS, 1080p, 60 fps if the laptop keeps up. Mic and desktop audio on **separate tracks**.
- Add captions (both your question and Curio's answer). Judges often watch muted.
- Zoom in during editing on the pointer flight, the step badge and the dashboard numbers.
- If you cut waiting time, label it ("2×" / "sped up"), or show one uncut answer.
  The app logs `turn timings: ... first_audio=... total=...` at INFO for real numbers.

## 4. Tuning a scene with the eval

```powershell
cd curio-py
# arrange the screen for the scene, then:
uv run python -m curio.eval.capture --name bg-chrome-max --question "how do I change my desktop background?" --delay 5
# fill in "expected" in eval_cases/bg-chrome-max/case.json, then:
uv run python -m curio.eval.run --repeat 3 --label baseline
# after a prompt/model change:
uv run python -m curio.eval.run --repeat 3 --label after
uv run python -m curio.eval.run --compare eval_results/baseline-<timestamp>.json eval_results/after-<timestamp>.json
```

(PowerShell doesn't expand `*` for these arguments, so use the real file names the run prints.)

The before/after pass rate makes a good pitch slide. Details are in `curio-py/eval_cases/README.md`.

## 5. Reset after recording

- Stop the map server and delete `map.json`
- `Remove-NetFirewallRule -DisplayName "Curio map server"` if you added it
- Set `share_walkthroughs = false` if you don't want to keep sharing
