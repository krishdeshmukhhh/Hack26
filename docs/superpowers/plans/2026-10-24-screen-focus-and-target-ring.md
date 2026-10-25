# Screen Focus and Target Ring Implementation Plan

> For agentic workers: Read this entire plan and AGENTS.md before starting. Use superpowers:executing-plans for your assigned task. Tasks A, B, and C run in separate terminals; Task D runs after they finish. Do not delegate further unless requested.

**Goal:** Let users hold Ctrl+Alt and left-drag a persistent focus box, ask questions about its contents, and see an animated light blue circle at the pet's pointing target.

**Architecture:** Keep selection input, focused image preparation, and target animation in separate modules. One integration task owns application wiring and conversation changes so the parallel tasks do not edit the same files.

**Tech Stack:** Python 3.12, PySide6, pynput, existing MSS/Pillow screen capture, pytest, Ruff.

## Proposed behavior and constraints

- User confirmed: hold Ctrl+Alt and left-drag to create the focus box. Finish on left-button release. An ordinary left click clears it.
- Ctrl+Alt without a mouse drag retains the existing voice behavior. Once selection starts, cancel any voice recording begun by that chord; modifier release must not submit it. A later fresh voice chord asks about the selected region.
- Selection remains across questions until cleared or replaced. Capture fresh contents for each question; do not reuse the image from when the box was drawn.
- Proposed v1 choice: constrain a selection to the display where the drag started. Normalize reverse drags, reject boxes smaller than 8 by 8 physical pixels, and support monitors with negative origins and mixed DPI.
- A modified selection click must not advance a guided walkthrough. An ordinary clearing click may also perform its usual application/walkthrough action.
- Proposed selection appearance: blue border and subtle translucent fill, always on top, no focus stealing. Its persistent overlay is click-through.
- Proposed target appearance: light blue (#87CEFA), expanding and fading concentric rings at the actual POINT coordinate, beginning when pointing is requested. Three pulses over about 1.5 seconds; a new target replaces the previous animation.
- The target marker is separate from the pet's position, which is intentionally offset from the target.
- Hide selection and target overlays during screenshots and restore previous visibility afterward, including on failure. Never capture their pixels into the model image.
- No new dependencies or changes to Worker/server APIs. Preserve ordinary screenshot and pointing behavior when there is no selection.
- These are implementation defaults, not additional user-confirmed preferences.

## Shared interfaces: all terminals must use these names

Coordinates crossing module boundaries use PHYSICAL global desktop pixels, matching MSS screenshot metadata and map_point_to_screen. Qt widgets must convert explicitly to/from logical desktop coordinates; do not assume a single global devicePixelRatio. Background listeners must marshal work to the Qt thread.

Task A creates `curio/focus_selection.py`:

```python
@dataclass(frozen=True)
class FocusRegion:
    left: int
    top: int
    width: int
    height: int

class FocusSelectionController(QObject):
    selection_started = Signal()
    region_changed = Signal(object)  # FocusRegion | None

    @property
    def region(self) -> FocusRegion | None: ...
    @property
    def selecting(self) -> bool: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def clear(self) -> None: ...
    def hide_for_capture(self) -> None: ...
    def restore_after_capture(self) -> None: ...
```

The controller owns its global gesture listener and selection overlay. It recognizes Ctrl+Alt regardless of the configured voice binding. It does not wire itself to CompanionManager or alter hotkey.py; integration owns input arbitration. `selection_started` fires on the modified left-button press, before the drag finishes, even if the final box is too small.

Task B creates `curio/focus_capture.py`:

```python
def focus_screenshots(
    screenshots: list[ScreenshotImage], region: FocusRegion | None
) -> list[ScreenshotImage]: ...
```

Return original screenshots unchanged with no selection. With selection, return one cropped screenshot from its display, with accurate physical origin, display size, encoded dimensions, scale, and label. Existing map_point_to_screen must map image-local model coordinates back to the selected desktop region correctly. A missing display or no intersection falls back to the original screenshots, not a crash or an empty model request. Avoid importing Task A at runtime purely for annotations (TYPE_CHECKING is fine).

Task C creates `curio/ui/target_ring.py`:

```python
class TargetRingOverlay(QWidget):
    def pulse_at(self, x: int, y: int) -> None: ...
    def clear(self) -> None: ...
    def hide_for_capture(self) -> None: ...
    def restore_after_capture(self) -> None: ...
```

`pulse_at` receives physical global desktop pixels. No app wiring or edits to existing companion widgets in this task. No focus activation or input interception. Capture hiding must not resurrect a finished animation.

## Review focus

- Selection chord starts recording before mouse down: recording is cancelled and no transcript is submitted on chord release.
- Selection drag while guiding: does not count as completing the current walkthrough step.
- Mixed DPI / negative monitor origins: border, crop, model coordinates, ring center all identify the same target.
- Overlay visibility after cancelled/failed screenshot: restore prior state; do not show an expired ring or cleared selection.
- User clears/replaces selection during a request: capture and point mapping use a consistent snapshot for that request; stale results follow existing cancellation rules.

## Task A — Selection gesture and rectangle overlay (Terminal 1)

**Own only:**
- Create `curio-py/curio/focus_selection.py`.
- Create `curio-py/curio/ui/focus_overlay.py`.
- Create `curio-py/tests/test_focus_selection.py`.

**Read:** `hotkey.py`, `click_watcher.py`, `screen_capture.py`, `ui/window_effects.py`, and existing overlay/widget tests.

- [ ] Write failing tests for normalized drags in all directions, minimum size, ordinary-click clearing, replacement, modifier release during drag, Escape cancellation, lifecycle cleanup, and physical/logical conversions including negative origins and mixed DPI.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement the shared controller and overlay. Keep listener callbacks independent of widget operations. Use a clear coordinate conversion boundary. Ensure release that completes selection does not clear it. Escape cancels an in-progress drag without leaving a stuck listener or overlay. Start/stop are idempotent.
- [ ] Prevent the selection drag from accidentally dragging/clicking the underlying application: intercept only the selection gesture on Windows, never all normal mouse activity. Document any platform behavior requiring a manual test.
- [ ] Run focused tests and Ruff on owned files. Manually verify the drag on Windows if available.
- [ ] Report files changed, tests, and the precise event ordering the integrator should expect. Do not modify app.py, hotkey.py, click_watcher.py, companion_manager.py, or capture modules.

## Task B — Focused screenshots and coordinate mapping (Terminal 2)

**Own only:**
- Create `curio-py/curio/focus_capture.py`.
- Create `curio-py/tests/test_focus_capture.py`.

**Read:** `screen_capture.py`, `point_mapper.py`, `point_parser.py`, `tests/test_point_mapper.py`, and `tests/test_screen_capture_labels.py`.

- [ ] Write failing tests using synthetic images with identifiable regions. Cover no selection, resized source images, clipping to display, negative origins, missing displays, image labels, and point mapping in both pixel and norm1000 modes.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement focus_screenshots. Crop from already encoded screenshots using their actual dimensions and physical bounds; account for rounding from existing downscaling. Maintain metadata so the existing mapper needs no changes. Do not add a second image with an ambiguous coordinate space.
- [ ] Label the returned image as the user's selected focus area, including its encoded image dimensions. Keep model request changes for Task D.
- [ ] Run focused tests and existing point-mapper/screen-label tests; run Ruff on owned files.
- [ ] Report interface behavior and any resolution tradeoff from cropping the existing downscaled capture. Do not modify screen_capture.py, point_mapper.py, app.py, companion_manager.py, or prompts.py.

## Task C — Animated target circle (Terminal 3)

**Own only:**
- Create `curio-py/curio/ui/target_ring.py`.
- Create `curio-py/tests/test_target_ring.py`.

**Read:** `ui/window_effects.py`, `ui/companion_widget.py`, `ui/pet_widget.py`, and existing widget tests.

- [ ] Write failing tests for animation lifecycle, replacement target, clear, capture hiding/restoration, expiration during capture, and target positioning on negative-origin/mixed-DPI monitors.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement the shared TargetRingOverlay with a bounded animation and no input/focus interception. Use Qt painting/timers/animation; clean up timers on close. Keep the exact ring center at the target even when the pet sits beside it.
- [ ] Run focused tests and Ruff on owned files. If possible, visually verify pulses over another app and click-through behavior.
- [ ] Report the API and tests. Do not modify pet_widget.py, companion_widget.py, app.py, or companion_manager.py.

## Task D — Integrate after A, B, and C finish (one terminal)

**Own:** `curio-py/curio/app.py`, `hotkey.py`, `click_watcher.py`, `companion_manager.py`, `prompts.py` if needed, `ui/companion_widget.py`, `ui/pet_widget.py`, integration tests, and user documentation. Inspect current code before deciding whether each file actually needs changes.

- [ ] Read all three implementations and reconcile their shared interfaces before wiring anything.
- [ ] Write a failing integration test for selection cancelling an already-started voice chord, no submit on modifier release, fresh voice chord after selection, focused model request, and clearing back to normal capture.
- [ ] Write a failing integration test proving modified selection clicks do not advance walkthroughs while ordinary clicks retain normal behavior. Arbitrate at the input source, before listener event ordering can race a queued selection signal.
- [ ] Run tests and confirm expected failures.
- [ ] Wire selection start to cancel voice recording and suppress the rest of that chord. Use a public method/explicit signal contract instead of application code reaching into private manager internals. Preserve hotkey cancellation, right_ctrl binding, and hands-free behavior.
- [ ] Snapshot selection for each request. Apply focus_screenshots after hiding all overlays and capturing. Make the prompt identify the selected region as the subject of the question. Preserve the cropped screenshot list used for point-coordinate mapping through that answer.
- [ ] Instantiate TargetRingOverlay once per companion. Trigger it from all fly_to implementations, including PetCompanionWidget's override and triangle fallback, without double pulses. Cover ordinary answers, walkthrough steps, and any current TA-hint pointing path.
- [ ] Integrate ring hiding/restoration into companion capture lifecycle. Include selection visibility in every screenshot path that could show its border; inspect the separate capture path in app.py too. Use try/finally restoration.
- [ ] Connect selection lifecycle to startup/shutdown; ensure input listeners and overlays close cleanly. Avoid changing pet wandering/idle behavior.
- [ ] Add integration coverage for ring triggering, no-point answers, replacement, cancellation, screen capture failures, and correct cropped-coordinate mapping. Preserve existing fake controller compatibility or update relevant fakes deliberately.
- [ ] From curio-py run `uv run pytest` and `uv run ruff check .`; investigate failures before claiming completion.
- [ ] Manually verify on Windows: plain voice chord, draw/reverse draw, voice question while box remains, normal-click clear, walkthrough selection, repeated target pulses, screen edges, and two monitors with different scaling.
- [ ] Update `docs/RUNNING.md` with the gesture and clearing behavior. Report automated results separately from manual checks not performed.

## Running the terminals

Use separate Git worktrees/branches from the same main commit, named `feat/focus-selection`, `feat/focus-capture`, and `feat/target-ring`. Each terminal should implement only its assigned task and commit only owned files. Do not have multiple terminals switch branches in the same working directory.

After all three finish, use one integration branch and cherry-pick their commits, then execute Task D. The parent checkout may have unrelated untracked files; do not stage or remove them. If repository permissions block worktree creation/commits, report the exact failure; do not bypass restrictions.

## Copy/paste prompts

### Terminal 1

Read AGENTS.md and docs/superpowers/plans/2026-10-24-screen-focus-and-target-ring.md. Implement Task A only on feat/focus-selection in an isolated worktree. Follow the shared interfaces and file ownership exactly. Write and run failing tests before implementation, then verify the finished task. Do not wire the app or edit another task's files. Commit your owned changes and report the commit hash, tests, and event ordering.

### Terminal 2

Read AGENTS.md and docs/superpowers/plans/2026-10-24-screen-focus-and-target-ring.md. Implement Task B only on feat/focus-capture in an isolated worktree. Follow the shared interfaces and file ownership exactly. Task A may not exist yet; avoid runtime imports solely for annotations and use test fixtures exposing the documented region fields. Verify actual cropped pixels and existing point mapping. Commit your owned changes and report the commit hash and tests.

### Terminal 3

Read AGENTS.md and docs/superpowers/plans/2026-10-24-screen-focus-and-target-ring.md. Implement Task C only on feat/target-ring in an isolated worktree. Follow the shared interfaces and file ownership exactly. Write and run failing tests before implementation, then verify the finished task. Do not wire the app or edit companion widgets. Commit your owned changes and report the commit hash, tests, and any manual visual checks performed.

### Integration terminal, after the three tasks finish

Read AGENTS.md and docs/superpowers/plans/2026-10-24-screen-focus-and-target-ring.md. Locate the completed Task A/B/C commits on feat/focus-selection, feat/focus-capture, and feat/target-ring; inspect and combine them on an integration branch. Implement Task D, respecting all documented behavior and coordinate contracts. Run the full Python test suite and Ruff, and report manual Windows checks separately. Do not push or merge into main unless the user requests it.
