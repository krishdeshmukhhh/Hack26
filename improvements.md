# Improvements: making Curio a winning HackOhio project

This doc proposes features and polish, ranked by how much each one moves the judging rubric for the time it costs. It assumes the current state in [docs/PROGRESS.md](docs/PROGRESS.md): voice → Whisper → Qwen3-VL on the lab H100 → Kokoro voice, Mac-style pointing, guided walkthroughs, animated pets, and per-app knowledge bases.

**Rubric:** Innovation · Curiosity · Communication · Project breadth and complexity · Impact · Growth mindset (navigating challenges)

---

## TL;DR: the five to build first

If there's only time for a few things, build these. Together they touch every rubric item.

| # | Feature | Main rubric hit | Effort |
|---|---------|-----------------|--------|
| 1 | **Grounded pointing:** snap the model's guess to a real UI element using Windows UI Automation | Innovation, Complexity | ~4–6 h |
| 2 | **Pointing accuracy benchmark:** a small eval set plus a script that scores models and settings | Curiosity, Growth mindset, Communication | ~3–4 h |
| 3 | **Click verification in walkthroughs:** "not quite, it's over here" when the user clicks the wrong thing | Innovation, Impact | ~2–3 h |
| 4 | **Campus demo:** a knowledge base and scripted walkthrough for OSU software (Carmen/Canvas, BuckeyeLink, or a lab tool) | Impact, Communication | ~2 h |
| 5 | **Live stats overlay + one-click start + fallback chain** so the demo can't die on stage | Communication, Growth mindset | ~3 h |

Everything below goes into more detail, grouped by rubric item. Most features count toward several items; each is listed under the one it helps most.

---

## The story to tell

Judges remember one sentence. Suggested framing:

> **"Curio is a private, on-campus AI tutor that sees your screen, talks you through any software, and physically points at what to click. No data ever leaves OSU."**

Three things to emphasize:
1. **Private by design.** Everything runs on a university GPU and the laptop. No API keys and no third-party cloud. That matters for FERPA, student data, and IT departments that can't send screenshots to OpenAI.
2. **It points; it doesn't just talk.** Most AI assistants describe where things are. Curio flies to the element, then checks that you clicked it.
3. **It's built to teach.** Walkthroughs, quizzes, and session notes, not just answers.

---

## 1. Innovation

### 1.1 Grounded pointing: vision + Windows UI Automation (top pick)
**Problem:** Qwen3-VL's coordinates are approximate. PROGRESS.md notes it sometimes says "bottom left" for a centered Start button, and small UI elements are easy to miss.

**Idea:** Windows exposes every button, menu, and text field (with name, role, and exact bounding box) through the **UI Automation (UIA)** accessibility tree. Combine the two:
- **Snap mode (easy):** after parsing `[POINT:x,y:label]`, query UIA for elements near `(x, y)`. Choose the best candidate by distance plus fuzzy match between the model's `label` and the element's `Name`, then fly to that element's true center.
- **Set-of-marks mode (stronger):** before the LLM call, list the visible interactive elements in the foreground window, number them, draw small numbered badges on the screenshot, and put the list in the prompt (`[12] Button "Export"`). The model replies `[POINT:#12]`, and we get pixel-perfect coordinates for free.
- **Fallback:** apps with no accessibility tree (games, canvas apps, some Electron apps) keep the current pure-vision path.

**Where:** new `curio/ui_automation.py` (use the `uiautomation` or `pywinauto` package, both pure Python on top of COM). Hook into `point_parser.py` / `point_mapper.py`, and into `screen_capture.py` for drawing badges.

**Why judges care:** it's a hybrid of vision-language grounding and OS accessibility APIs that few teams will have, and you can measure it (see 2.1).

### 1.2 Click verification and correction in walkthroughs
**Problem (known issue):** any left click counts as "step done", even a click somewhere unrelated.

**Idea:** `click_watcher.py` already sees the click. Compare it with the target:
- If the click lands inside the target element's UIA bounding box, or within about 40 px of the point, advance.
- If not, the pet shakes its head, says "close! it's a bit higher, right here", and flies back to the target. Don't advance.
- Optional: after the click, take a quick screenshot diff. If nothing on screen changed, the click probably missed.

This turns walkthroughs from "the AI talks at you" into "the AI watches you and corrects you", which is what a real tutor does.

### 1.3 Pointing synced to speech
**Today:** one `[POINT]` per answer, at the end.
**Idea:** allow several inline point tags (`"first open the file menu [POINT:..:file] then choose export [POINT:..:export]"`). Kokoro already speaks sentence by sentence, so fire each flight when TTS reaches that sentence. The pet tours the UI in step with the voice, the way a person gestures while explaining.
**Where:** `point_parser.py` (return a list with character offsets), `kokoro_tts_client.py` (emit a `sentence_started(index)` signal), `companion_manager.py` (queue the flights).

### 1.4 Spotlight overlay
When pointing, dim the rest of the screen with a translucent click-through overlay and cut a soft hole around the target (using the UIA bounding box when available). It reads clearly on a projector, which helps the demo.

### 1.5 Proactive "stuck detector" (opt-in)
Watch for signs of struggle: a new error dialog (UIA `WindowOpened` event with a dialog role), repeated Ctrl+Z, or the cursor wandering for 20+ seconds without a click. The pet perks up and offers: "looks like that threw an error, want me to explain it?" Ctrl+Alt accepts. Keep it opt-in and rate-limited so it isn't annoying.

---

## 2. Curiosity

Curiosity is shown by asking questions and answering them with experiments. You've already done some of this informally (Whisper `small.en` vs `base.en`, Kokoro thread tuning). Make it formal and visible.

### 2.1 Pointing accuracy benchmark (top pick)
Build `eval/` with:
- **About 40 screenshots** across apps you care about (Windows Settings, File Explorer, VS Code, Carmen, Blender), each with a question and a ground-truth bounding box. Label quickly from the UIA tree, or by hand.
- **`eval/run_pointing_eval.py`**: sends each case through the app's real `OpenAICompatLLMClient` and records hit/miss (point inside the box), distance error, and latency.
- **Experiments to run and chart:**
  - 1280 px vs 1920 px screenshots (already on the "Next up" list)
  - `norm1000` vs `pixel` coordinates
  - pure vision vs UIA snap vs set-of-marks (feature 1.1)
  - Qwen3-VL-30B-A3B vs 32B dense, if a GPU frees up
- **Output:** a table and bar chart in `docs/EVAL.md`.

A slide that says "pointing accuracy went from 58% to 94% with UIA grounding" is the strongest single piece of evidence you can show judges. (Measure the real numbers; those are placeholders.)

### 2.2 Latency breakdown
Instrument each stage (hotkey release → transcript → first token → first audio → point flight) with `time.perf_counter()` and log one structured line per turn. Collect about 20 turns and report median and p90 per stage. You already have pieces of this (1.7 s first token, 0.4 s to speech); put it in one table.

### 2.3 Prompt-format experiments
PROGRESS.md found the model ignores step tags unless reminded. Turn that into a small study: N runs × prompt variants → tag compliance rate. Judges like a "we were surprised by X, so we measured it" story.

---

## 3. Communication

### 3.1 Live stats HUD (demo mode)
A small tray toggle that shows a corner overlay during the demo:
```
STT 0.8s · first token 1.7s · speech 0.4s · GPU: H100 (OSU lab) · 0 bytes to cloud
```
It shows judges the system is real, local, and fast, without you having to say so.
**Where:** new `curio/ui/stats_overlay.py`, fed by the timing events from 2.2.

### 3.2 Session notes export ("what I learned")
At the end of a session (tray > Export notes), write a markdown or HTML page with each question, the answer, and a **cropped screenshot of the pointed-at element** with a circle drawn on it. Students get a personal cheat sheet. It also makes a great demo closer: "and here's the study guide it made for you."
**Where:** extend `conversation_history.py` to keep a crop per turn; new `curio/notes_export.py`.

### 3.3 Demo assets
- **90-second video** recorded in advance as a backup. The GPU is shared and can be taken at any time (known issue), so don't bet the demo on it.
- **Hero GIF** at the top of the README: the pet flying to a button mid-sentence.
- **Architecture diagram** (one image): laptop (mic → Whisper → overlay → Kokoro) ⇄ SSH tunnel ⇄ H100 (vLLM, Qwen3-VL). Make the "nothing leaves campus" boundary visible.
- **Rewrite the README intro for the local-first version.** It still leads with Claude, ElevenLabs, and the Cloudflare Worker, so judges skimming the repo get the wrong story.

### 3.4 Demo script (3 minutes)
1. **Hook (15 s):** "Who here has watched a 20-minute YouTube video to find one button?"
2. **Basic question (30 s):** open Carmen or an unfamiliar app, ask "where do I submit my assignment?" The pet flies there.
3. **Walkthrough (60 s):** "how do I change my notification settings?" Click the wrong thing on purpose; Curio corrects you (1.2). Finish the task.
4. **Quiz mode (30 s):** "now you try: where would you go to see grades?" (4.1)
5. **Privacy + stats (30 s):** point at the HUD: H100 on campus, 0 bytes to the cloud, 2 s responses.
6. **Close (15 s):** the exported study notes, plus the accuracy chart from the benchmark.

---

## 4. Project breadth and complexity

The project already spans a Qt desktop app, async audio, local ML on CPU, a vLLM server on a GPU workstation, SSH networking, a Cloudflare Worker, and sprite animation. These features widen it in meaningful directions.

### 4.1 Quiz / teach-back mode
Learning research favors active recall over passive instruction. After a walkthrough, or on request ("quiz me"), Curio asks "where would you click to export a video?" and waits for a click. It checks the click against the target (reusing 1.2), then praises or hints. Track a small score per app. This turns Curio from an assistant into a tutor.

### 4.2 Retrieval over knowledge bases (RAG)
**Today:** every markdown file in the matched KB folder goes into the system prompt. That doesn't scale past a few pages and costs prompt tokens (latency).
**Upgrade:** chunk the KB, embed it with a small local model (`bge-small` via `fastembed` or `sentence-transformers` on CPU), and retrieve the top-k chunks for the transcript. Add a script that turns a docs website or PDF into a KB folder automatically.
**Where:** `knowledge_base.py`.

### 4.3 Recordable lessons: "teach Curio once, replay for everyone"
A TA or IT staffer runs a walkthrough while recording: each step's instruction, the UIA element identity (automation ID + name + role), and a screenshot crop are saved to `lessons/<name>.json`. Students replay the lesson; Curio finds each element by its UIA identity (so it works at any resolution) and only asks the LLM when something doesn't match. This is a real product direction (campus IT, onboarding), and replay is instant because it needs no model calls.

### 4.4 Multilingual tutoring
Whisper's multilingual models detect the spoken language, Qwen3-VL answers in it, and Kokoro has voices for several languages (Spanish, French, Hindi, Japanese, Mandarin, and others). Answer in the user's language while pointing at English UI. International students are a large, real audience.
**Where:** `whisper_transcription_client.py` (drop `.en`, read `info.language`), `prompts.py` ("reply in {language}"), `kokoro_tts_client.py` (voice per language).

### 4.5 Privacy redaction
Before a screenshot leaves the laptop, black out password fields (UIA `IsPassword`) and an optional user-defined list of windows (for example a password manager or banking site). Show a small "redacted 2 regions" indicator. This makes the privacy story concrete, and it's very little code once 1.1 exists.

### 4.6 Hands-free mode
An optional wake word ("hey curio") using `openWakeWord` (runs on CPU), plus voice activity detection to end the turn. This helps users who can't comfortably hold two keys (see 5.2).

---

## 5. Impact

### 5.1 Pick a real audience and show it
"Anyone learning software" is too broad to be memorable. Choose one or two and build the demo around them:
- **OSU students on campus systems** (Carmen/Canvas, BuckeyeLink, Workday): build a KB, and test with a few real students during the hackathon. Even three quotes ("I've never found that page before") is strong evidence.
- **Older adults and first-time computer users:** a patient voice that points is exactly what they need, and family members currently do this over the phone.
- **IT help desks:** every "where's the button" ticket Curio handles saves staff time, and the on-premises setup satisfies data rules.

### 5.2 Accessibility settings
- Larger pointer and pill text, a high-contrast theme, and slower flights (`design_system.py`; the pets already have reduced motion).
- A configurable hotkey for one-handed use, plus the hands-free mode from 4.6.
- Adjustable speech rate (Kokoro supports speed).

### 5.3 Robustness is impact
A tutor that silently does nothing is worse than no tutor. Fix the known issues users would hit first:
- **Config errors only show in the log:** surface them as a red pill (PROGRESS.md says the bubble does this, but confirm it covers every startup path).
- **Duplicate LLM error reports:** dedupe in `companion_manager.py`.
- **GPU taken away:** see 6.1.

### 5.4 Run it with real users and measure
Run a tiny user study: 5 people, one unfamiliar task each, half with Curio and half with web search. Time them. "Median 48 s with Curio vs 3 min 10 s with Google, n=5" on a slide is small but concrete. Be honest that the sample is small.

---

## 6. Growth mindset (navigating challenges)

You already have excellent material here; it's buried in PROGRESS.md. Surface it, and build features that show you learned from it.

### 6.1 Automatic fallback chain
The shared-GPU problem is a story about resilience. Build the answer to it:
1. Lab H100 (vLLM, Qwen3-VL-30B)
2. → a small vision model on the laptop (for example Qwen2.5-VL-3B through `llama.cpp` or Ollama): slower and less accurate, but it works offline
3. → the cloud Worker (Claude), only if the user opted in

Health-check the current backend every few seconds, switch automatically, show which one is active in the tray and on the HUD, and have the pet say "switching to backup brain" once. Add `server/` health endpoint polling and a `fallback_order` config key.

### 6.2 One-click start (`start.ps1`)
Already planned (#2 in "Next up"). Open the SSH tunnel, poll `/v1/models` until vLLM is ready, then launch the app. Show the steps in a small console UI. This reduces demo-day risk and is easy to show off.

### 6.3 A "challenges we hit" page
Write `docs/CHALLENGES.md` (and one slide) from what's already in PROGRESS.md. For each challenge: problem → how you diagnosed it → fix → what you'd do differently.
- **Slurm assumption was wrong:** the lab machines turned out to be standalone workstations, so the job script was rewritten.
- **H200 crash:** DeepGEMM needed nvcc 12.9+ and the box had 12.8; fixed with `VLLM_USE_DEEP_GEMM=0`.
- **Disk:** `/local/scratch` looked like 92 GB free but only 20 GB was usable because of root-reserved blocks; weights moved to the home drive.
- **CUDA 12.5 driver vs a cu128 wheel:** worked through minor-version compatibility, with transformers pinned.
- **Ctrl+Alt stopped working:** two causes, admin-window input isolation and a Shift+I case-mismatch stuck-key bug, fixed with virtual-key codes, `GetAsyncKeyState`, and regression tests.
- **Model ignored the step format:** measured it, then fixed it with a targeted reminder (4/4 compliance).
- **Whisper `small.en` was slower and no more accurate:** measured and reverted. Show that you'll undo your own change when the data says so.
- **Merging two rewrites** (Mac-parity overlay and pets) by adding explicit hooks instead of patching internals.

Judges often ask "what went wrong?" Having this ready, with tests that lock in each fix, is the best possible answer.

### 6.4 Show the engineering discipline
Mention the 167 tests, the regression test per bug, the CLAUDE.md agent workflow (dev / reviewer / tester agents), and the fake-`nvidia-smi` test that found two script bugs. Show one CI badge: add a GitHub Actions workflow that runs `pytest` and `ruff` on Windows.

---

## Rubric coverage matrix

| Feature | Innov. | Curios. | Comm. | Breadth | Impact | Growth |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| 1.1 UIA grounded pointing | ●● | ● | | ●● | ● | |
| 1.2 Click verification | ●● | | ● | ● | ●● | |
| 1.3 Speech-synced pointing | ●● | | ● | ● | | |
| 1.4 Spotlight overlay | ● | | ●● | | ● | |
| 1.5 Stuck detector | ●● | ● | | ● | ● | |
| 2.1 Pointing benchmark | | ●● | ●● | ● | | ●● |
| 2.2 Latency breakdown | | ●● | ● | | | ● |
| 3.1 Stats HUD | | | ●● | | | ● |
| 3.2 Session notes export | ● | | ●● | ● | ●● | |
| 4.1 Quiz mode | ●● | ● | ● | ● | ●● | |
| 4.2 KB retrieval (RAG) | | ● | | ●● | ● | |
| 4.3 Recordable lessons | ●● | | ● | ●● | ●● | |
| 4.4 Multilingual | ● | | | ● | ●● | |
| 4.5 Privacy redaction | ● | | ● | ● | ●● | |
| 5.4 Mini user study | | ●● | ●● | | ●● | ● |
| 6.1 Fallback chain | ● | | | ●● | ● | ●● |
| 6.3 Challenges page | | ● | ●● | | | ●● |

---

## Suggested order and owners

Following the CLAUDE.md workflow (frontend-dev owns `curio-py/`, backend-dev owns `server/` and `worker/`; reviewer and tester check every feature):

**Phase 1: demo-critical (do first, in parallel)**
- frontend-dev A: `ui_automation.py` + UIA snap in the point pipeline (1.1, snap mode)
- frontend-dev B: stats HUD + per-stage timing (3.1, 2.2)
- backend-dev: `start.ps1` + vLLM health endpoint polling (6.2, part of 6.1)
- Human: record the backup demo video now, while the GPU works

**Phase 2: the "wow" layer**
- Click verification (1.2): depends on 1.1
- Pointing benchmark (2.1): run it before and after 1.1 to get the headline chart
- Campus KB + rehearsed walkthrough (5.1)

**Phase 3: if time allows**
- Quiz mode (4.1), session notes (3.2), spotlight (1.4), speech-synced pointing (1.3), laptop fallback model (6.1)

**Phase 4: polish for judging (last 3 hours, no new features)**
- README rewrite + hero GIF + architecture diagram (3.3)
- `docs/CHALLENGES.md` + `docs/EVAL.md` (6.3, 2.1)
- Rehearse the 3-minute script twice, with the backup video ready

**Leave alone during the hackathon:** cloud-mode turn splitting (the demo uses local mode), Qwen3-VL-32B (only if a whole GPU frees up), and any new pet species.
