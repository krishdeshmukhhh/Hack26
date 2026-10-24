# Animated Pets Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to execute; isolated supporting tasks may be delegated. Track verified milestones in docs/PROGRESS.md.

**Goal:** Deliver four selectable animated desktop pets while retaining voice and pointing behavior.
**Architecture:** Keep CompanionWidget and backend contracts; separate pure sprite timing and behavior from Qt rendering. Profiles and mappings are data.
**Tech Stack:** Python 3.12, PySide6, qasync, pytest.
**Spec:** docs/ARCHITECTURE.md, approved animated-pet section.

## Global Constraints
- No new rendering framework. Preserve click-through, waveform, capture visibility and pointing.
- Latest destination during jumps; no jump queue. Zero additional arc for supplied sheets.
- Configuration persistence preserves unrelated settings. No repeated approval pauses.

## Review Focus
- Cancellation and stale TTS events cannot override a new listening turn.
- Screen geometry may have negative origins, gaps, or mixed DPI.
- Missing assets must preserve working triangle fallback.
- New config must accept old config files and preserve comments/secrets.
- Jump playback must finish once with timing matching movement state.

## Task 1: Catalog/player and controller
Files: curio/pets.py, assets/pets, tests/test_pets.py.
Interfaces: SpriteCatalog, SpritePlayer, BehaviorController with time-based update and independent state inputs.
- [x] Write and run failing pure tests for timing, cooldown, latest destination, bounds, reduced motion and priority.
- [x] Implement catalog and deterministic controller, then run tests.

## Task 2: Settings and selection
Files: curio/pet_config.py, config.py, ui/tray_icon.py, config.example.toml, tests/test_pet_config.py.
- [x] Write failing validation and non-destructive persistence tests.
- [x] Implement PetSettings, [pet] parsing, selection persistence and tray submenu; run tests.

## Task 3: Overlay and interaction integration
Files: ui/companion_widget.py, app.py, companion_manager.py, clients/*tts_client.py, curio.spec.
- [x] Test overlay fallback, frame painting, waveform states, selection, pointing return, capture hiding and cancellation where dependencies permit.
- [x] Wire controller/player with cached sprites, preserve triangle fallback and waveforms.
- [x] Wire text, actual TTS start/end and warning input; guard stale task completions.
- [x] Include package assets in frozen builds.

## Task 4: Verification and documentation
- [x] Run full existing/new tests and scoped lint; inspect Qt rendering when possible.
- [x] Review complete implementation and fix important findings.
- [x] Update ARCHITECTURE, PROGRESS and RUNNING with implemented behavior and precise verification limits.

Ruling: Execute immediately under the user's explicit authorization; do not add a plan approval gate. Remain on the already requested feature branch. Supporting agents own disjoint files; main agent integrates and verifies.

Verification: 138 tests passed; scoped Ruff passes; 24 actual Qt states rendered and inspected. Physical-desktop and frozen-build acceptance remain manual.
Ruling: Added targeted CRLF normalization after original parser tests failed on Windows. Kept target marker at arrival, preserving existing pointing without an extra floating window.

## Follow-up: whimsical pursuit (user authorized)
- [x] Parallel motion task: finite non-restarting hesitation, bounded pursuit,
  latest destination, eased arrival and hysteresis with deterministic tests.
- [x] Parallel behavior task: profile delays/speeds, more noticeable idle play,
  traversal hops, AI priority, sleep/wake and regression tests.
- [x] Integration task: faster default sleep, explicit settings preserved,
  actual widget timer tests, Qt snapshots and existing documentation updates.
- [x] Verify complete suite on project Python 3.12.15: 156 pass; scoped lint clean.
Read-only integration review found no important defects. Existing optional-action
playback can lead its behavior clock by one timer tick; no new jump displacement
or queued movement was introduced.
