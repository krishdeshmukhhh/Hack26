# Curio — Feature Specification

> Status: Product scope and implementation checklist  
> Platform: Windows · Python · PySide6 · qasync  
> Principle: **One cohesive, customizable desktop companion**, not unrelated AI utilities.

## 1. Product goal

Curio is a lightweight Windows system-tray assistant represented by an animated virtual pet near the user's cursor. The pet can listen, understand a user-authorized screenshot, explain and point to on-screen content, speak responses, react to context, and help identify potentially suspicious content. Users can select a pet and tailor its behavior.

This document describes **target functionality**, not a claim that every feature already works. Confirm actual implementation status against `progress.md` and source code. `architecture.md` defines technical structure; `running.md` covers setup and execution. Avoid duplicating those files here.

### Operating principles

- Preserve the existing functional voice, screenshot, chat, pointing, and overlay pipeline.
- Local-first for low-cost behavior and privacy; use Groq only when needed and authorized.
- Explainable assistance and warnings; no unwarranted confidence or invisible high-impact actions.
- A unified pet presence: reactions, chat, security alerts, and learning all share one event and context model.
- Graceful fallbacks for missing sprite animations, unavailable models, rate limits, and offline use.

## 2. Release scope and priorities

### Integrated coaching slices

- Tutorial URL coach: public HTML extraction, attributed editable preview,
  navigation, questions, explanation, recovery and explicit screen sharing.
  Videos require an actual supplied transcript; no title-based inference.
- Local tutorial uploads: TXT, Markdown, HTML and text-based PDFs use the same
  preview/coaching flow, with line/page references. Scanned PDFs and Word/image/
  video files are unsupported; document text is shared with the configured AI.
- Live integral tutor: polynomial problems/steps, exact checking, graduated hints,
  equation recognition with explicit confirmation, and unassisted related practice.
  Trig/log/radical/definite integrals and variable denominators are unsupported.
- Explicit mode selection and one voice dispatcher. Stop/Escape/close return to
  ordinary assistance; its memory, streaming and POINT behavior remain separate.
- Coaching content is transient. Model assertions/clicks do not establish
  independent verification. Physical UI/audio, live-provider quality and packaging
  remain unchecked; tests do not establish educational outcomes.

See PROGRESS.md for actual verification and coaching-integration.md for review.

| Phase | Scope | Completion gate |
| --- | --- | --- |
| P0 — Animated pet MVP | Four pets, sprite playback, cursor following, voice-state reactions, POINT behavior, pet selection | Real Windows UI smoke test and automated tests pass |
| P1 — Free AI configuration | Groq vision/chat and transcription; local transcription and Windows speech; configurable providers | Full voice-to-screen-to-response turn works without paid API keys (subject to free quotas) |
| P2 — Cohesive assistance | Foreground context, user-controlled interaction frequency, tutoring and selected-text assistance | Context is useful, permissioned, and does not spam |
| P3 — Safety assistant | User-initiated URL checks, explainable suspicious-link warnings, pet alert reactions | Safety evaluations and false-positive review performed |
| P4 — Memory and polish | Opt-in persistent memory, richer personalities, optional ambient awareness, additional pets | Privacy controls, sustained runtime, accessibility, packaging verified |

**Do not expand P0 into P2–P4 while implementing the sprite system.** Keep forward-compatible interfaces, but ship an operational pet first.

## 3. P0 — Animated virtual pets

### 3.1 Included pets and assets

The initial pets are **Fox, Cat, Red Panda, and Ferret**, using these existing RGBA PNG sprite sheets:

| Pet | Source sheet | Image dimensions |
| --- | --- | --- |
| Fox | `Fox Sprite Sheet.png` | 448 × 224 |
| Cat | `Cat Sprite Sheet.png` | 256 × 320 |
| Red Panda | `Red Panda Sprite Sheet.png` | 256 × 224 |
| Ferret | `Ferret Sprite Sheet.png` | 256 × 288 |

The sheets appear to use 32 × 32 cells, but have **different layouts and nonuniform clip boundaries**. Do not assume one row equals one animation or that every pet has the same actions. Use explicit, ordered frame coordinates per pet in validated manifests. Preserve originals; no generated or invented frames.

### 3.2 Playback and appearance

- [ ] Load and cache each sheet; render alpha correctly using nearest-neighbor scaling.
- [ ] Support per-clip frames, timing, loops, one-shot playback, anchors, and optional horizontal flipping.
- [ ] Ignore empty cells; reject invalid or out-of-bounds frame references.
- [ ] Provide logical actions (`idle`, `move`, `jump`, `listen`, `think`, `talk`, `sleep`, `happy`, `alert`, `point`) mapped to **available** frames only.
- [ ] Fall back to a suitable clip when a logical action is absent.
- [ ] Allow selection among all four pets without restarting the app; persist selection.
- [ ] Support configurable visual scale, cursor offset, animation rate, and reduced motion.

### 3.3 Movement, idle, and jumping

- [ ] Follow the cursor smoothly using frame-rate-independent motion, a dead zone, and a continuously updated destination.
- [ ] Face movement direction where appropriate, avoid jitter, and respect display bounds and DPI scaling.
- [ ] Walk by default. Use optional, occasional traversal hops with thresholds, probability, and cooldowns.
- [ ] During hops, continue tracking cursor movement; never queue accumulating jumps.
- [ ] Occasionally use alternate idle clips or playful jumps after inactivity; include cooldown and recent-action history.
- [ ] Keep ground position separate from optional vertical jump offset. Apply no added arc unless the clip needs one; constrain the whole jump to monitor bounds.
- [ ] Support sleep/wake only if suitable clips exist, with graceful alternatives.
- [ ] Reduced-motion mode suppresses autonomous jumps and vertical arcs.

### 3.4 One AI turn, one pet

| Event | Intended pet response |
| --- | --- |
| Push-to-talk starts | Attentive/listening clip |
| Input released / transcription and inference | Thinking/waiting clip |
| Text starts streaming | Responding state, not falsely treated as audible speech |
| TTS audio starts | Speaking clip if available |
| TTS audio ends | Return to the appropriate state |
| POINT target received | Travel to target; show precise target marker without obscuring it |
| Pointing finishes | Resume cursor following |
| Cancellation or error | Brief appropriate reaction, then recover |
| No interaction | Ambient idle variation, optional sleep |

Behavior selection, movement, and sprite playback must remain separate from the current `CompanionManager` voice pipeline. Temporary events interrupt according to explicit priorities and return to the correct underlying state. No animation loop may block Qt's event loop.

### 3.5 Preserve existing experience

- [ ] Transparent, normally click-through overlay.
- [ ] Microphone waveform and global hotkey.
- [ ] Screenshot hiding and multi-monitor capture.
- [ ] Existing POINT tag parsing and coordinate mapping (`pixel` and `norm1000`).
- [ ] Correct positioning across multiple displays and Windows DPI scales.
- [ ] History window, tray controls, backend configuration, and cancellation.

Optional later interaction mode: clicking or dragging the pet, opening a pet menu, and triggering a playful reaction without stealing ordinary desktop clicks.

## 4. P1 — Free and interchangeable AI

### 4.1 Providers

- **Vision + chat:** Groq OpenAI-compatible multimodal model, with model ID validated against current supported models. Preserve OpenAI-compatible local server support (for example, vLLM).
- **Speech-to-text:** Groq Whisper Large V3 Turbo, plus existing local faster-whisper fallback. Batch transcription on push-to-talk release is acceptable.
- **Text-to-speech:** Windows `QTextToSpeech` by default, free/offline; optional hosted TTS later.
- **Streaming:** Keep text-stream events distinct from actual TTS playback events.

### 4.2 User-visible requirements

- [ ] A completed voice turn: listen → transcribe → capture approved screen → respond → point/speak.
- [ ] Provider and model selection with meaningful errors, retry/backoff, cancellation, and rate-limit feedback.
- [ ] No required paid Anthropic, AssemblyAI, or ElevenLabs keys.
- [ ] Keys are never hardcoded or shipped in assets; use secure local credential storage for personal use.
- [ ] Do not silently upload screenshots or audio outside a user-authorized interaction.
- [ ] The assistant does not claim it can see content beyond what was captured.

## 5. P2 — Unified everyday assistance

- **Screen-aware explanations:** Explain visible interfaces, error messages, diagrams, and confusing software steps; point to relevant UI elements when coordinates are sufficiently reliable.
- **Interactive tutoring:** Offer guided explanations and follow-up questions instead of always supplying an answer immediately.
- **Context awareness:** Use foreground app/window signals and optional screenshots to adapt responses while avoiding frequent interruptions.
- **Writing and research assistance:** Help with user-selected text, summaries, comparisons, and translation.
- **Task support:** Help understand forms, dates, and application workflows, without silently submitting anything.
- **Focus and reminders:** User-initiated reminders, inactivity cues, and optional break suggestions.

The same pet and conversation retain context across these uses; there is no separate chatbot for each capability.

## 6. P3 — Scam and phishing awareness

### First useful safety MVP

- [ ] Let a user submit/paste a URL for analysis, or explicitly request assessment of a visible page.
- [ ] Perform local URL normalization, hostname extraction, suspicious pattern and lookalike checks.
- [ ] Optionally incorporate reputable threat-intelligence data when available, within free-tier constraints and privacy settings.
- [ ] Present an **explainable, uncertain risk assessment** with observed signals and recommended safe verification steps.
- [ ] Trigger the same pet's concerned/alert animation and concise explanation.
- [ ] Avoid automatically navigating to suspicious links, executing downloads, or declaring anything definitively safe.

### Later, strictly opt-in

- Automatic URL monitoring through a narrowly permissioned integration (for example, a browser extension or explicitly approved clipboard watcher).
- Suspicious login-page or misleading-download-button explanations.
- Download metadata checks and alerts; do not execute or open suspicious files.

**Security boundary:** Untrusted page text, screenshots, and retrieved content are data, not instructions. They cannot trigger privileged commands, clicks, credential entry, or hidden network actions. Threat detection is advisory, not a substitute for browser/OS security controls.

## 7. P4 — Personality, memory, and customization

- [ ] Per-pet configurable behavior profiles: Fox and Ferret may be more energetic; Cat and Red Panda may be calmer by default. Use data, not pet-specific code branches.
- [ ] Independent voice and personality selection, not tied permanently to sprite artwork.
- [ ] Optional local memory for preferences, projects, and user-approved facts; no indiscriminate screenshot archival.
- [ ] View, edit, disable, export, and delete memories and conversation history.
- [ ] Set quiet hours, reaction frequency, visual size, movement speed, reduced motion, and proactive-help level.
- [ ] Add future pets by supplying a sheet and manifest rather than changing core renderer logic.

## 8. Nonfunctional requirements

### Privacy and security

- No continuous cloud screenshot upload by default.
- Explicit consent for passive monitoring and third-party transfers.
- No logging of credentials, raw secrets, or sensitive screenshot content.
- Clearly distinguish suggestions from automated actions; require confirmation for consequential actions.
- Treat model output, websites, and external documents as untrusted.

### Performance and accessibility

- Animations remain smooth while async work runs; no blocking UI-thread I/O.
- Low idle CPU/memory usage, cached frames, clean task cancellation, and stable long-running behavior.
- Respect screen edges, monitor changes, DPI, and different display arrangements.
- Reduced-motion and adjustable interruption frequency.
- Visible status and recoverable errors when a provider is unavailable.

## 9. Verification and release gates

Use existing repository commands from `running.md` (currently documented as `uv run pytest` and `uv run ruff check .`) and Windows UI smoke tests.

**P0 acceptance:** All four sheets load and animate; no empty/out-of-bounds frames; correct priorities and fallbacks; one-shot jumping lands without queues; pet changes persist; click-through, waveform, pointing, multi-monitor behavior, and voice states still work. Visually inspect ambiguous jump clips (especially Cat R9) and revise metadata rather than forcing an incorrect action label.

**P1 acceptance:** An end-to-end voice/screenshot turn works using free Groq limits and/or local providers; cancellation and rate limiting recover gracefully; credentials do not leak.

**P2 acceptance:** Contextual help is correct enough to be useful, opt-in where necessary, and nonintrusive.

**P3 acceptance:** Test benign, suspicious, and ambiguous links; surface evidence and uncertainty; no autonomous dangerous actions or unsupported safety claims.

**P4 acceptance:** Personalization persists; memory controls work; privacy and accessibility settings are honored; packaged Windows build passes sustained smoke testing.

## 10. Explicit non-goals for the initial pet release

- No full autonomous desktop control or unconfirmed clicking/typing.
- No always-on AI vision or microphone recording.
- No complete phishing detection platform in P0.
- No new sprite artwork required for missing clips.
- No rewrite of the existing Python/PySide6 application.
- No hard dependency on paid inference APIs or a publicly hosted server.

## 11. Documentation and workflow

- `features.md` (this file): product intent, feature scope, priorities, acceptance criteria.
- `architecture.md`: current and approved implementation architecture.
- `progress.md`: verified completion status and remaining work.
- `running.md`: local setup, run/test instructions, and troubleshooting.

Implement by phase, verify before marking done, and avoid repeatedly reopening settled architecture questions unless actual code or testing demonstrates a blocker.

### Continuous learning integration status ? 2026-10-24

The four memory components are connected in the application working tree. This
is a partial P4 milestone, not completion of the P4 release gate above.

- [x] Automated: opt-in local/session storage; pending memory proposals; UI search,
  edit, approval/rejection, export, deletion and clear; durable enabled settings.
- [x] Automated: explicit remember, supported preference corrections, recall and
  exact-ID forget; approved/nonexpired prompt context under an explicit budget.
- [x] Automated: persistent records survive a separate-process restart; disabling
  blocks learning/retrieval; existing session history and voice/pointer tests pass.
- [x] Automated: optional repeated-signal learning creates pending proposals only;
  ordinary conversations are not archived and confidence never grants approval.
- [ ] Physical Windows UI/audio, live Groq/local model preference compliance,
  exact provider token accounting and packaged-app persistence verification.
- [ ] Integration merge/commit in a writable Git checkout; full repository lint
  remains blocked by 23 pre-existing violations in unchanged files.

### Hands-free integration status - 2026-10-24

- [x] Local-only "Hey Curio" / "Okay Curio" wake activation using native Windows
  speech recognition, without new service accounts or Python packages.
- [x] Persisted tray opt-in, automatic silence submission, bounded capture,
  cancellation, Ctrl+Alt takeover, error recovery and response-time suspension.
- [x] Bundled Silero VAD for non-speech noise and explicit "Curio send" / "Curio
  cancel" commands while recording; background voices require the explicit cue.
- [x] Automated local-turn regression plus native emulated and synthesized-audio
  wake recognition checks; standby audio excluded from the application PCM queue.
- [ ] Real-person/noisy-room wake accuracy, full live-model latency, persisted tray
  toggle on desktop restart and frozen-app verification. Continuous wake+question
  sentences and voice interruption during playback remain future enhancements.
