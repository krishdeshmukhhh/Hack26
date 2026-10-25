"""CompanionManager — orchestration state machine for Curio.

Owns the hotkey → mic → transcription → screen-capture → LLM pipeline and
emits high-level Qt signals that the UI layer (panel, tray) can bind to
without knowing the plumbing details.

Replaces the ad-hoc closure wiring in ``app.py``.  In Task 4.9 the
application entry point will be refactored to instantiate a
``CompanionManager`` and delegate to it.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from PySide6.QtCore import QByteArray, QObject, QTimer, Signal

from curio import ui_automation
from curio.active_window import get_foreground_window_title
from curio.click_watcher import ClickWatcher
from curio.clients.kokoro_tts_client import KokoroTTSClient
from curio.clients.llm_client import LLMClient
from curio.clients.openai_llm_client import OpenAICompatLLMClient
from curio.clients.system_tts_client import SystemTTSClient
from curio.clients.transcription_client import TranscriptionClient
from curio.clients.tts_client import TTSClient
from curio.clients.whisper_transcription_client import WhisperTranscriptionClient
from curio.coaching_runtime import CoachingMode, CoachingRuntime
from curio.config import Config
from curio.conversation_history import ConversationHistory
from curio.focus_capture import focus_screenshots
from curio.focus_selection import FocusRegion, FocusSelectionController
from curio.hands_free import strip_finish_command
from curio.hotkey import HotkeyMonitor
from curio.key_finish_watcher import KeyFinishWatcher
from curio.knowledge_base import load_kb_from_disk, match_app, select_content
from curio.learning_contract import AssistanceLevel, StepEvent, StepOutcome, app_key, task_key
from curio.learning_events import (
    LearningServices,
    PendingStep,
    WalkthroughRecorder,
    element_from_point,
)
from curio.memory_conversation import ConversationMemory
from curio.mic_capture import MicCapture
from curio.point_mapper import map_point_to_screen
from curio.point_parser import (
    PointTag,
    StepTag,
    find_point_tag,
    parse_concepts_tag,
    parse_point_tag,
    parse_step_tag,
)
from curio.prompts import build_system_prompt, is_howto_question, walkthrough_reminder
from curio.screen_capture import ScreenshotImage, cursor_position, grab_probe
from curio.settle import SETTLE_MASK_RADIUS_PX, SETTLE_MAX_SECONDS, wait_for_settle
from curio.speech_chunker import SpeechChunker
from curio.state import VoiceState
from curio.ui_automation import SnapResult, snap_point
from curio.window_context import describe_windows

if TYPE_CHECKING:
    from curio.focus_session.integration import FocusIntegration

logger = logging.getLogger(__name__)

_CONCEPTS_DONE_RE = re.compile(r"\[CONCEPTS:[^\]]*\]")

# After the user's click, wait at most this long for the app to react (menus
# open, dialogs appear) before taking the next step's screenshot. The wait ends
# early once the screen changed and went still (see curio.settle).
WALKTHROUGH_SETTLE_SECONDS = SETTLE_MAX_SECONDS
# Give up waiting for the user to do a step after this long.
WALKTHROUGH_TIMEOUT_MS = 120_000


class CaptureVisibilityController(Protocol):
    """Protocol for hiding/restoring UI during screen capture."""

    def hide_for_capture(self) -> None:
        """Temporarily hide during screen capture."""
        ...

    def restore_after_capture(self) -> None:
        """Restore after screen capture."""
        ...

    def fly_to(
        self, x: int, y: int, *, hold: bool = False, step: tuple[int, int] | None = None
    ) -> None:
        """Fly the companion to a screen point and point at it.

        ``hold`` keeps it there (walkthrough step waiting for a click);
        ``step`` is (index, total) for the pointer pill.
        """
        ...


class SpotlightHost(Protocol):
    """Protocol for the point-target spotlight (see ``curio.ui.spotlight``)."""

    def point_started(self, x: int, y: int, *, hold: bool = False) -> None: ...

    def hide(self) -> None: ...

    def hide_for_capture(self) -> None: ...

    def restore_after_capture(self) -> None: ...


class CompanionManager(QObject):
    """Orchestration state machine for the voice companion pipeline.

    Coordinates hotkey detection, microphone capture, transcription,
    screen capture, and LLM streaming into a single coherent lifecycle
    with cancellation support.
    """

    # ---- Qt signals ----
    state_changed = Signal(VoiceState)
    audio_level = Signal(float)
    interim_transcript = Signal(str)
    final_transcript = Signal(str)
    response_delta = Signal(str)
    response_complete = Signal(str)
    success_turn_completed = Signal()
    error = Signal(str)
    # Once per answer: what the companion points at ("" if nothing) and the
    # walkthrough step / total (0, 0 outside a walkthrough).
    response_annotated = Signal(str, int, int)
    walkthrough_ended = Signal()
    # Only when the model finishes a walkthrough (not Esc, cancel, timeout or error).
    walkthrough_completed = Signal()
    speaking_changed = Signal(bool)
    security_warning = Signal(str)

    def __init__(
        self,
        config: Config,
        mic: MicCapture,
        hotkey: HotkeyMonitor,
        transcription: TranscriptionClient | WhisperTranscriptionClient,
        llm: LLMClient | OpenAICompatLLMClient,
        tts: TTSClient | SystemTTSClient | KokoroTTSClient,
        screen_capture_fn: Callable[[], list[ScreenshotImage]],
        panel_visibility_controller: CaptureVisibilityController,
        click_watcher: ClickWatcher | None = None,
        key_watcher: KeyFinishWatcher | None = None,
        parent: QObject | None = None,
        *,
        memory: ConversationMemory | None = None,
        learning: LearningServices | None = None,
        spotlight: SpotlightHost | None = None,
    ) -> None:
        super().__init__(parent)

        # Dims the screen around the point target; None when [ui] spotlight = false.
        self._spotlight = spotlight
        self._memory = memory
        # Walkthrough learning: None when [learning] enabled = false.
        self._learning = learning
        self._recording: WalkthroughRecorder | None = None
        self._coaching: CoachingRuntime | None = None
        # Focus/study session hooks (curio.focus_session.integration); None = off.
        self._focus: FocusIntegration | None = None
        self._config = config
        self._mic = mic
        self._hotkey = hotkey
        self._transcription = transcription
        self._llm = llm
        self._tts = tts
        self._screen_capture_fn = screen_capture_fn
        self._panel_visibility_controller = panel_visibility_controller
        self._focus_selection: FocusSelectionController | None = None
        self._capture_lock = asyncio.Lock()
        self._selection_cancelled = False
        self._transcription_waiting = False
        self._transcription_stops: set[asyncio.Task] = set()

        # Internal state
        self._state: VoiceState = VoiceState.IDLE
        self._current_task: asyncio.Task[None] | None = None
        self._history = ConversationHistory()
        self._knowledge_dir = config.knowledge_dir  # Path | None
        self._current_model: str = config.default_model
        self._cancel_flag: bool = False
        self._current_screenshots: list[ScreenshotImage] = []
        self._speak_task: asyncio.Task[None] | None = None
        self._generation = 0
        # Sentence-chunked speech while the LLM streams (None when the TTS
        # client can't stream or no turn is streaming).
        self._speech: tuple[SpeechChunker, asyncio.Queue[str | None]] | None = None
        # Per-turn timing marks (time.monotonic), logged when speech ends.
        self._marks: dict[str, float] = {}
        self._hands_free_recording = False
        self._strip_hands_free_command = False
        # Early flight: the [POINT] tag is acted on as soon as it streams in.
        self._stream_text = ""
        self._stream_point_active = False
        self._early_flight: PointTag | None = None
        self._early_task: asyncio.Task[None] | None = None
        self._keep_spotlight = False
        # (x, y, label) -> SnapResult | None; replaceable in tests.
        self._snap_fn: Callable[..., Any] = snap_point
        self._warmed_up = False
        self._settle_seconds: float | None = None
        self._settle_mask_center: tuple[int, int] | None = None
        # Async () -> ProbeFrame | None for the adaptive settle; None = default grab.
        self._settle_grab: Callable[[], Any] | None = None

        # Guided walkthrough: the step the user is currently doing, if any.
        self._walkthrough: StepTag | None = None
        self._click_watcher = click_watcher or ClickWatcher(self)
        self._click_watcher.clicked.connect(self._on_walkthrough_click)
        # Typing steps finish from the keyboard; taps the hotkey's existing hook.
        if key_watcher is None and hasattr(hotkey, "typing_enter"):
            key_watcher = KeyFinishWatcher(hotkey, self)
        self._key_watcher = key_watcher
        if self._key_watcher is not None:
            self._key_watcher.finished.connect(self._on_walkthrough_click)
        self._walkthrough_timeout = QTimer(self)
        self._walkthrough_timeout.setSingleShot(True)
        self._walkthrough_timeout.setInterval(WALKTHROUGH_TIMEOUT_MS)
        self._walkthrough_timeout.timeout.connect(self._on_walkthrough_timeout)

        # PCM deque bridge — same pattern as app.py.  Replaced on every
        # hotkey-press cycle so a stale generator cannot leak chunks.
        self._pcm: dict[str, Any] = {
            "deque": deque(),
            "event": asyncio.Event(),
            "done": False,
        }

        # ---- Signal wiring ----
        hotkey.pressed.connect(self._on_hotkey_pressed)
        hotkey.released.connect(self._on_hotkey_released)
        hotkey.cancelled.connect(self._on_hotkey_cancelled)
        hotkey.escape_pressed.connect(self._on_escape)

        mic.audio_level.connect(self.audio_level)
        mic.pcm_chunk.connect(self._on_pcm_chunk)

        transcription.interim_transcript.connect(self.interim_transcript)
        transcription.final_transcript.connect(self._on_final_transcript)
        transcription.error.connect(self._on_error)

        llm.delta.connect(self._on_llm_delta)
        llm.error.connect(self._on_error)

        tts.error.connect(self._on_error)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_model(self, model_id: str) -> None:
        """Update the model used for LLM requests."""
        self._current_model = model_id
        if self._coaching is not None:
            self._coaching.set_model(model_id)

    def attach_focus_selection(self, selection: FocusSelectionController) -> None:
        """Attach the selection owner without changing legacy fake input contracts."""
        self._focus_selection = selection
        if hasattr(self._click_watcher, "set_click_source"):
            self._click_watcher.set_click_source(selection)

    def cancel_for_selection(self) -> None:
        """Cancel this voice chord and keep the pending walkthrough step intact."""
        self._selection_cancelled = True
        self._on_hotkey_cancelled(preserve_walkthrough=True)

    async def capture_screenshots(self) -> list[ScreenshotImage]:
        """Fresh focused capture shared by ordinary turns and explicit coaching capture."""
        region = self._focus_selection.region if self._focus_selection is not None else None
        return await self._capture_screenshots(region)

    async def _capture_screenshots(self, region: FocusRegion | None) -> list[ScreenshotImage]:
        # Serialize ALL screenshot paths so one cannot restore another's overlays.
        async with self._capture_lock:
            controllers = [self._panel_visibility_controller]
            if self._spotlight is not None:
                controllers.append(self._spotlight)
            if self._focus_selection is not None:
                controllers.append(self._focus_selection)
            hidden = []
            try:
                for controller in controllers:
                    hidden.append(controller)
                    controller.hide_for_capture()
                await asyncio.sleep(0.05)
                task = asyncio.create_task(asyncio.to_thread(self._screen_capture_fn))
                try:
                    shots = await asyncio.shield(task)
                except asyncio.CancelledError:
                    # Cancelling to_thread does not stop native capture. Keep overlays
                    # hidden until the worker really finishes, even on cancellation.
                    while not task.done():
                        try:
                            await asyncio.shield(task)
                        except asyncio.CancelledError:
                            continue
                        except Exception:
                            break
                    with suppress(Exception):
                        task.result()
                    raise
                return focus_screenshots(shots, region)
            finally:
                for controller in reversed(hidden):
                    controller.restore_after_capture()

    async def warm_up_llm(self) -> None:
        """Best-effort one-token request to the local model; never raises, runs once."""
        if self._config.point_snap:
            ui_automation.prewarm()
        warm = getattr(self._llm, "warm_up", None)
        if warm is None or self._warmed_up:
            return
        self._warmed_up = True
        started = time.monotonic()
        try:
            await warm(self._current_model)
            logger.info("llm warm-up done in %.2fs", time.monotonic() - started)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("llm warm-up skipped: %s", exc)

    async def aclose(self) -> None:
        """Retire asynchronous work and walkthrough timers before Qt shuts down."""
        self._generation += 1
        self._cancel_flag = True
        self._selection_cancelled = True
        self._click_watcher.stop()
        if self._key_watcher is not None:
            self._key_watcher.stop()
        self._hide_spotlight()
        self._walkthrough_timeout.stop()
        self._mic.stop()
        self._stop_pcm_bridge()
        self._stop_speaking()
        if isinstance(self._transcription, WhisperTranscriptionClient):
            self._transcription.cancel_stream()
        else:
            self._queue_transcription_stop()
        tasks = [t for t in (self._current_task, self._speak_task)
                 if t is not None and not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*tuple(self._transcription_stops), return_exceptions=True)
        async with self._capture_lock:
            pass  # A previously cancelled turn may still be retiring native capture.

    def attach_coaching(self, runtime: CoachingRuntime) -> None:
        """Attach exactly one router; it is the sole coaching transcript consumer."""
        if self._coaching is not None:
            raise ValueError("Coaching is already attached")
        self._coaching = runtime
        runtime.mode_changed.connect(self._on_coaching_mode_changed)
        runtime.interrupted.connect(self._stop_speaking)
        runtime.response_ready.connect(self._on_coaching_reply)
        runtime.error.connect(self.error)

    def attach_focus(self, focus: FocusIntegration | None) -> None:
        """Focus sessions: card replies, start/end by voice and tutor directives."""
        self._focus = focus

    def say(self, text: str) -> bool:
        """Speak a short focus-session line, only when nothing else is happening.

        Never interrupts listening, thinking or an answer being spoken; the
        caller still shows its text. Goes through the normal state machine so
        hands-free standby stays suspended while it plays.
        """
        if not text or self._state not in (VoiceState.IDLE, VoiceState.GUIDING):
            return False
        self._set_state(VoiceState.RESPONDING)
        self._speak_task = asyncio.ensure_future(self._speak(text, self._generation))
        return True

    def _on_coaching_mode_changed(self, _mode: str) -> None:
        self._on_hotkey_cancelled()

    def detach_coaching(self) -> None:
        if self._coaching is None:
            return
        runtime = self._coaching
        self._on_hotkey_cancelled()
        runtime.mode_changed.disconnect(self._on_coaching_mode_changed)
        runtime.interrupted.disconnect(self._stop_speaking)
        runtime.response_ready.disconnect(self._on_coaching_reply)
        runtime.error.disconnect(self.error)
        self._coaching = None

    def _on_coaching_reply(self, text: str) -> None:
        if self._coaching is None or self._coaching.mode == CoachingMode.ASSISTANT:
            return
        self._stop_speaking()
        self._cancel_flag = False
        self._set_state(VoiceState.RESPONDING)
        self.response_complete.emit(text)
        # Coaching replies are display/speech only, never POINT actions, memory
        # evidence or entries in the ordinary assistant's conversation buffer.
        self._speak_task = asyncio.ensure_future(self._speak(text, self._generation))

    async def _run_coaching_turn(self, text: str, generation: int) -> None:
        try:
            if generation != self._generation or self._cancel_flag:
                return
            self.final_transcript.emit(text)
            await self._coaching.ask(text)
        except asyncio.CancelledError:
            if generation == self._generation:
                self._set_state(VoiceState.IDLE)
        except Exception:
            if generation == self._generation:
                message = "Coaching request failed. Check the session and connection, then retry."
                self._coaching.error.emit(message)
                self._set_state(VoiceState.IDLE)

    # ------------------------------------------------------------------
    # PCM deque bridge
    # ------------------------------------------------------------------

    def _on_pcm_chunk(self, chunk: QByteArray) -> None:
        if self._state != VoiceState.LISTENING:
            return
        self._pcm["deque"].append(chunk)
        self._pcm["event"].set()

    async def _pcm_async_generator(self) -> AsyncGenerator[QByteArray, None]:
        """Async generator that yields QByteArray chunks from the deque.

        Snapshots the deque and event refs at first iteration.  The ``done``
        flag is read from the live dict — stale generators from a previous
        session are terminated via ``task.cancel()`` in ``_on_hotkey_pressed``,
        not via the done flag.
        """
        dq: deque[QByteArray] = self._pcm["deque"]
        ev: asyncio.Event = self._pcm["event"]
        while True:
            await ev.wait()
            ev.clear()
            while dq:
                yield dq.popleft()
            if self._pcm["done"]:
                return

    def _reset_pcm_bridge(self) -> None:
        """Replace the PCM bridge state for a fresh session."""
        self._pcm["deque"] = deque()
        self._pcm["event"] = asyncio.Event()
        self._pcm["done"] = False

    def _stop_pcm_bridge(self) -> None:
        """Signal the PCM generator to terminate."""
        self._pcm["done"] = True
        self._pcm["event"].set()

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _set_state(self, new_state: VoiceState) -> None:
        self._state = new_state
        self.state_changed.emit(new_state)

    # ------------------------------------------------------------------
    # Hotkey handlers
    # ------------------------------------------------------------------

    def _on_hotkey_pressed(self) -> None:
        logger.debug("hotkey pressed (state=%s)", self._state)
        self._hands_free_recording = False
        self._strip_hands_free_command = False
        self._selection_cancelled = False

        self._generation += 1
        if self._coaching is not None:
            self._coaching.interrupt()
        self.speaking_changed.emit(False)

        # Pause until a transcript confirms this is a question. Ctrl+Alt may
        # instead become a selection gesture; that must retain the current step.
        self._click_watcher.stop()
        if self._key_watcher is not None:
            self._key_watcher.stop()
        self._walkthrough_timeout.stop()
        self._hide_spotlight()
        self._stop_speaking()

        # Interrupt any in-flight turn OR lingering stream task.
        if self._state != VoiceState.IDLE:
            self._cancel_flag = True
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()

        # Reset PCM bridge for a fresh session.
        self._reset_pcm_bridge()

        # Transition to LISTENING, start mic, start transcription.
        self._set_state(VoiceState.LISTENING)
        self._mic.start()

        self._transcription_waiting = True
        self._current_task = asyncio.ensure_future(self._start_transcription(
            self._generation, tuple(self._transcription_stops)
        ))

    async def _start_transcription(self, generation: int, cleanup: tuple) -> None:
        # A cancelled remote stop can still emit a final transcript. Drain it
        # before opening the new session, with transcript acceptance paused.
        if cleanup:
            await asyncio.shield(asyncio.gather(*cleanup, return_exceptions=True))
        if generation != self._generation:
            return
        self._transcription_waiting = False
        await self._transcription.start_stream(self._pcm_async_generator())

    def _queue_transcription_stop(self) -> None:
        task = asyncio.ensure_future(self._transcription.stop_stream())
        self._transcription_stops.add(task)
        task.add_done_callback(self._transcription_stops.discard)

    def _on_hotkey_released(self) -> None:
        if self._hands_free_recording or self._selection_cancelled:
            return
        logger.debug("hotkey released")
        self._set_state(VoiceState.PROCESSING)
        self._mic.stop()
        self._stop_pcm_bridge()
        self._queue_transcription_stop()

    def _on_hotkey_cancelled(self, *, preserve_walkthrough: bool = False) -> None:
        logger.debug("hotkey cancelled")
        hands_free = self._hands_free_recording
        self._hands_free_recording = False
        self._generation += 1
        if self._coaching is not None:
            self._coaching.interrupt()
        self._hide_spotlight()
        if not preserve_walkthrough:
            self._end_walkthrough()
        self._cancel_flag = True
        self._speech = None
        self._tts.stop()
        self.speaking_changed.emit(False)
        if self._speak_task is not None and not self._speak_task.done():
            self._speak_task.cancel()
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
        self._mic.stop()
        self._stop_pcm_bridge()
        if (hands_free or preserve_walkthrough) and isinstance(
            self._transcription, WhisperTranscriptionClient
        ):
            self._transcription.cancel_stream()
        else:
            self._queue_transcription_stop()
        # Transition to IDLE directly — the transcription client may not
        # emit a final_transcript if the session never fully started.
        if preserve_walkthrough and self._walkthrough is not None:
            self._click_watcher.start()
            if self._key_watcher is not None:
                self._key_watcher.start()
            self._walkthrough_timeout.start()
            self._set_state(VoiceState.GUIDING)
        else:
            self._set_state(VoiceState.IDLE)

    def begin_hands_free(self) -> None:
        """Start the same recording pipeline as push-to-talk, without a key."""
        if self._state not in (VoiceState.IDLE, VoiceState.GUIDING):
            return
        self._on_hotkey_pressed()
        self._hands_free_recording = True

    def finish_hands_free(self, *, strip_command: bool = False) -> None:
        if self._hands_free_recording and self._state == VoiceState.LISTENING:
            self._strip_hands_free_command = strip_command
            self._hands_free_recording = False
            self._on_hotkey_released()

    def cancel_hands_free(self) -> None:
        if self._hands_free_recording:
            self._on_hotkey_cancelled()

    # ------------------------------------------------------------------
    # Transcription handler
    # ------------------------------------------------------------------

    def _on_final_transcript(self, text: str) -> None:
        if self._selection_cancelled or self._transcription_waiting:
            return
        if self._strip_hands_free_command:
            text = strip_finish_command(text)
            self._strip_hands_free_command = False
        if self._state == VoiceState.IDLE:
            # The press was cancelled (or errored) before this transcript
            # arrived — don't start a turn nobody asked for.
            logger.debug("ignoring transcript received while idle")
            return
        if not text:
            # User pressed and released without speaking enough.
            self._end_walkthrough()
            self._set_state(VoiceState.IDLE)
            return

        self._end_walkthrough()

        # Reset cancel flag here (not in _run_turn) so a rapid
        # press between task assignment and coroutine start cannot
        # have its cancellation silently undone.
        self._cancel_flag = False
        coaching = self._coaching is not None and self._coaching.mode != CoachingMode.ASSISTANT
        if not coaching and self._focus is not None and self._focus.handle_transcript(text):
            # A reply to a focus card, or starting/ending a session: no assistant turn.
            self.final_transcript.emit(text)
            self._set_state(VoiceState.IDLE)
            return
        if coaching:
            self._current_task = asyncio.ensure_future(
                self._run_coaching_turn(text, self._generation)
            )
        else:
            self._current_task = asyncio.ensure_future(self._run_turn(text, self._generation))

    # ------------------------------------------------------------------
    # LLM delta relay (only when not cancelled)
    # ------------------------------------------------------------------

    def _on_llm_delta(self, text: str) -> None:
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        if task is not None and task is not self._current_task:
            return
        if not self._cancel_flag:
            self._mark("first_token")
            self.response_delta.emit(text)
            if self._speech is not None:
                chunker, queue = self._speech
                for chunk in chunker.feed(text):
                    queue.put_nowait(chunk)
            if self._stream_point_active and self._early_flight is None:
                self._maybe_fly_early(text)

    # ------------------------------------------------------------------
    # Error handler
    # ------------------------------------------------------------------

    def _on_error(self, msg: str) -> None:
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        sender = self.sender()
        streaming = self._speech is not None and self._state == VoiceState.PROCESSING
        if sender is self._tts and streaming:
            # Streamed speech failed while the model is still answering: the
            # turn is over, so stop it instead of leaving it half-spoken.
            self._stop_speaking()
            if self._current_task is not None and self._current_task is not task:
                self._cancel_flag = True
                self._current_task.cancel()
        elif sender in (self._llm, self._tts):
            if self._state != VoiceState.RESPONDING:
                return
            if task is not None and task not in (self._current_task, self._speak_task):
                return
        logger.error("companion error: %s", msg)
        self._end_walkthrough()
        self.speaking_changed.emit(False)
        self.error.emit(msg)
        self._set_state(VoiceState.IDLE)

    # ------------------------------------------------------------------
    # Guided walkthroughs
    # ------------------------------------------------------------------

    def _mark(self, name: str) -> None:
        """Record when a turn milestone first happened (for the timing log)."""
        self._marks.setdefault(name, time.monotonic())

    def _log_timings(self) -> None:
        start = self._marks.get("start")
        if start is None:
            return
        parts = []
        if self._settle_seconds is not None:
            parts.append(f"settle={self._settle_seconds:.2f}s")
        parts += [f"{k}={self._marks[k] - start:.2f}s" for k in
                  ("captured", "first_token", "first_audio", "fly", "llm_done")
                  if k in self._marks]
        logger.info("turn timings: %s total=%.2fs", " ".join(parts), time.monotonic() - start)
        self._marks = {}
        self._settle_seconds = None

    def _maybe_fly_early(self, delta: str) -> None:
        """Fly to the POINT target the moment its tag is complete in the stream.

        The tag normally precedes [STEP]/[CONCEPTS], so wait until one of those
        has also completed (or the stream ends) to know the hold/step semantics.
        Anything unparseable falls back to the end-of-reply flight.
        """
        self._stream_text += delta
        if "]" not in delta:
            return
        text = self._stream_text
        point = find_point_tag(text)
        if point is None:
            return
        _, step = parse_step_tag(text)
        if step is None and not _CONCEPTS_DONE_RE.search(text):
            return
        self._early_flight = point
        coords = map_point_to_screen(point, self._current_screenshots, self._config.point_coords)
        if coords is None:
            return
        self._mark("fly")
        if not self._config.point_snap:
            self._fly(coords, step, "POINT (early)", point.label)
            return
        self._early_task = asyncio.ensure_future(
            self._snap_then_fly(coords, step, "POINT (early)", point.label, self._generation)
        )

    async def _snap_then_fly(
        self,
        coords: tuple[int, int],
        step: StepTag | None,
        tag: str,
        label: str,
        generation: int,
    ) -> None:
        """Snap the model's point onto a real UI element, then fly once."""
        coords = await self._snap(coords, label)
        if generation != self._generation:
            return  # the turn was cancelled or superseded while snapping
        self._fly(coords, step, tag, label)

    async def _snap(self, coords: tuple[int, int], label: str) -> tuple[int, int]:
        """Return the UIA-snapped coords, or the model's own when unsure (never raises)."""
        if not self._config.point_snap:
            return coords
        try:
            result: SnapResult | None = await self._snap_fn(coords[0], coords[1], label)
        except Exception as exc:  # noqa: BLE001
            logger.info("POINT snap failed: %s", exc)
            return coords
        return (result.x, result.y) if result is not None else coords

    def _fly(
        self, coords: tuple[int, int], step: StepTag | None, tag: str, label: str
    ) -> None:
        if self._spotlight is not None:
            self._spotlight.point_started(coords[0], coords[1], hold=step is not None)
        self._panel_visibility_controller.fly_to(
            coords[0],
            coords[1],
            hold=step is not None,
            step=(step.index, step.total) if step is not None else None,
        )
        logger.info("%s: (%d, %d) label=%s", tag, coords[0], coords[1], label)

    def _hide_spotlight(self) -> None:
        if self._spotlight is not None and not self._keep_spotlight:
            self._spotlight.hide()

    def _stop_speaking(self) -> None:
        self._speech = None
        self._tts.stop()
        if self._speak_task is not None and not self._speak_task.done():
            self._speak_task.cancel()

    def _update_walkthrough(self, step: StepTag | None) -> None:
        """Called once per answer with the answer's [STEP:k/n] tag, if any.

        Any STEP tag keeps the walkthrough going: after the user's click we
        ask for the next step, and it ends when the model answers without a
        tag (task finished). The model's step total is unreliable (the 30B
        model often says 1/1 for multi-click tasks), so it's display-only.
        """
        if step is not None:
            self._walkthrough = step
            self._click_watcher.start()
            if self._key_watcher is not None:
                self._key_watcher.start()
            self._walkthrough_timeout.start()
            logger.info(
                "walkthrough: waiting on step %d (model estimate: %d)", step.index, step.total
            )
        else:
            if self._walkthrough is not None:
                logger.info("walkthrough: model says the task is finished")
            self._end_walkthrough(StepOutcome.SUCCEEDED, completed=True)

    def _end_walkthrough(
        self, outcome: StepOutcome = StepOutcome.ABANDONED, *, completed: bool = False
    ) -> None:
        """Stop waiting for clicks. ``outcome`` settles the step being recorded;
        the default covers Esc, a new push-to-talk question and errors."""
        self._hide_spotlight()
        self._finish_recording(outcome, completed=completed)
        was_active = self._walkthrough is not None
        self._walkthrough = None
        self._click_watcher.stop()
        if self._key_watcher is not None:
            self._key_watcher.stop()
        self._walkthrough_timeout.stop()
        if was_active:
            logger.info("walkthrough ended")
            self.walkthrough_ended.emit()
            if completed and outcome == StepOutcome.SUCCEEDED:
                self.walkthrough_completed.emit()
        if self._state == VoiceState.GUIDING:
            self._set_state(VoiceState.IDLE)

    def _on_walkthrough_click(self) -> None:
        step = self._walkthrough
        if step is None or self._state not in (VoiceState.RESPONDING, VoiceState.GUIDING):
            return
        logger.info("walkthrough: step %d done, fetching the next one", step.index)
        self._hide_spotlight()
        # One click per step; the next answer re-arms the watcher.
        self._click_watcher.stop()
        if self._key_watcher is not None:
            self._key_watcher.stop()
        self._walkthrough_timeout.stop()
        self._stop_speaking()
        self._set_state(VoiceState.PROCESSING)
        self._cancel_flag = False
        self._current_task = asyncio.ensure_future(self._continue_walkthrough(step))

    async def _settle_probe(self) -> Any:
        """One cheap grab of the monitor the step was on (off the UI thread)."""
        shots = self._current_screenshots
        left, top = (shots[0].monitor_left, shots[0].monitor_top) if shots else (0, 0)
        return await asyncio.to_thread(
            grab_probe, left, top,
            mask_center=self._settle_mask_center,
            mask_radius_px=SETTLE_MASK_RADIUS_PX,
        )

    async def _continue_walkthrough(self, step: StepTag) -> None:
        try:
            if WALKTHROUGH_SETTLE_SECONDS > 0:
                try:
                    self._settle_mask_center = cursor_position()
                except Exception:  # noqa: BLE001
                    self._settle_mask_center = None
                self._settle_seconds = await wait_for_settle(
                    self._settle_grab or self._settle_probe,
                    max_seconds=WALKTHROUGH_SETTLE_SECONDS,
                )
                logger.debug("walkthrough settle: %.2fs", self._settle_seconds)
        except asyncio.CancelledError:
            self._set_state(VoiceState.IDLE)
            return
        await self._run_turn(f"i did step {step.index}. what's next?", continuing_step=step.index)

    def _on_escape(self) -> None:
        if self._coaching is not None and self._coaching.mode != CoachingMode.ASSISTANT:
            self._coaching.stop_session()
            return
        self._hide_spotlight()
        if self._walkthrough is None and self._state != VoiceState.GUIDING:
            return
        self._stop_speaking()
        if self._current_task is not None and not self._current_task.done():
            self._cancel_flag = True
            self._current_task.cancel()
        self._end_walkthrough()
        self._set_state(VoiceState.IDLE)

    def _on_walkthrough_timeout(self) -> None:
        if self._walkthrough is not None and self._state == VoiceState.GUIDING:
            logger.info("walkthrough timed out waiting for a click")
            self._end_walkthrough(StepOutcome.TIMED_OUT)

    # ------------------------------------------------------------------
    # Walkthrough learning
    # ------------------------------------------------------------------

    def _step_assistance(self, point_tag: PointTag | None) -> AssistanceLevel:
        """How much help this step's answer gave.

        Hands-free voice activation still leaves actions to the user. DID_IT is
        reserved for a future action executor and is never inferred from input mode.
        """
        return AssistanceLevel.POINTED if point_tag is not None else AssistanceLevel.HINTED

    def _record_step_answer(
        self,
        step: StepTag,
        spoken_text: str,
        point_tag: PointTag | None,
        concepts: tuple[str, ...],
        *,
        window_title: str,
        task: str,
    ) -> None:
        if self._learning is None:
            return
        if self._recording is None:
            # The opening answer: the walkthrough is keyed on its question.
            self._recording = WalkthroughRecorder(app=app_key(window_title), task=task)
        element = None
        if point_tag is not None:
            element = element_from_point(
                point_tag, self._current_screenshots, self._config.point_coords, window_title
            )
        settled = self._recording.step_answered(
            PendingStep(
                step_index=step.index,
                instruction=spoken_text,
                assistance=self._step_assistance(point_tag),
                element=element,
                concepts=concepts,
            )
        )
        if settled is not None:
            self._record_settled(settled)

    def _record_settled(self, settled: StepEvent) -> None:
        self._learning.record_step(settled)
        if self._focus is not None:
            # Walkthrough outcomes are the study coach's attempt/stuck events.
            self._focus.step_settled(settled)

    def _finish_recording(self, outcome: StepOutcome, *, completed: bool) -> None:
        recording, self._recording = self._recording, None
        if recording is None or self._learning is None:
            return
        # STEP/DONE is model output, never a user confirmation or verifier.
        settled, summary = recording.finish(
            outcome, completed=completed,
            evidence_basis="model_inferred" if completed else "unknown",
        )
        if settled is not None:
            self._record_settled(settled)
        self._learning.finish_walkthrough(summary)
        if self._focus is not None:
            self._focus.walkthrough_finished(recording.task, completed)

    async def _learning_prompt(
        self, text: str, window_title: str, continuing_step: int | None
    ) -> str | None:
        """Recorded path and estimated skill advice for how-to requests; None otherwise."""
        if self._learning is None:
            return None
        recording = self._recording
        if continuing_step is not None and recording is not None:
            app, task = recording.app, recording.task
            pending = recording.pending
            concepts = pending.concepts if pending is not None else ()
        elif continuing_step is None and is_howto_question(text):
            app, task, concepts = app_key(window_title), task_key(text), ()
        else:
            return None
        shot = self._current_screenshots[0] if self._current_screenshots else None
        return await self._learning.prompt_text(
            app=app,
            task=task,
            concepts=concepts,
            point_coords=self._config.point_coords,
            image_size=(shot.image_width_px, shot.image_height_px) if shot else (0, 0),
        )

    # ------------------------------------------------------------------
    # TTS playback (async, fire-and-forget)
    # ------------------------------------------------------------------

    @staticmethod
    async def _queue_chunks(queue: asyncio.Queue[str | None]) -> AsyncIterator[str]:
        while (item := await queue.get()) is not None:
            yield item

    async def _speak(
        self,
        text: str,
        generation: int | None = None,
        *,
        chunks: AsyncIterator[str] | None = None,
    ) -> None:
        """Speak text via TTS. State stays RESPONDING during playback.

        With ``chunks`` the speech is streamed while the LLM is still answering
        (state is still PROCESSING when the first sentence starts playing).
        """
        generation = self._generation if generation is None else generation
        if generation != self._generation:
            return
        live_states = (VoiceState.RESPONDING,)
        if chunks is not None:
            live_states = (VoiceState.RESPONDING, VoiceState.PROCESSING)

        def started():
            self._mark("first_audio")
            if generation == self._generation and self._state in live_states:
                self.speaking_changed.emit(True)

        def finished():
            if generation == self._generation:
                self.speaking_changed.emit(False)

        self._tts.playback_started.connect(started)
        self._tts.playback_finished.connect(finished)
        try:
            if chunks is not None:
                await self._tts.speak_stream(chunks)
            else:
                await self._tts.speak(text)
        except asyncio.CancelledError:
            logger.debug("TTS cancelled")
        except Exception as exc:  # noqa: BLE001
            logger.error("TTS error: %s", exc)
            if generation == self._generation:
                self.error.emit(str(exc))
        finally:
            self._tts.playback_started.disconnect(started)
            self._tts.playback_finished.disconnect(finished)
            if generation == self._generation:
                self.speaking_changed.emit(False)
                self._log_timings()
            # Only leave RESPONDING if this is still the current turn and we're
            # still in it (a new hotkey press or walkthrough click may have
            # already moved on).
            if generation == self._generation and self._state == VoiceState.RESPONDING:
                waiting = self._walkthrough is not None
                self._set_state(VoiceState.GUIDING if waiting else VoiceState.IDLE)

    # ------------------------------------------------------------------
    # Turn pipeline (async)
    # ------------------------------------------------------------------

    async def _run_turn(
        self, text: str, generation: int | None = None, *, continuing_step: int | None = None
    ) -> None:
        """Execute the full turn: screen capture → LLM request → history.

        This coroutine becomes ``_current_task`` and supports cancellation
        via ``_cancel_flag`` (cooperative) and ``task.cancel()`` (hard).
        """
        generation = self._generation if generation is None else generation
        focus_region = self._focus_selection.region if self._focus_selection is not None else None
        try:
            # Yield control so stop_stream (which is still draining after
            # the recv loop emitted final_transcript synchronously) can
            # finish before we do any work that pumps the Qt event loop
            # (hide_for_capture calls processEvents, which would re-enter
            # the stop_stream task and trigger a RuntimeError).
            await asyncio.sleep(0)
            if generation != self._generation:
                return
            self._marks = {"start": time.monotonic()}
            if continuing_step is None:
                self._settle_seconds = None
            self._stream_text = ""
            self._stream_point_active = False
            self._early_flight = None

            # Emit the final transcript so the UI can display it.
            self.final_transcript.emit(text)

            local_reply = None
            window_title = ""
            if self._memory is not None and continuing_step is None:
                local_reply = await self._memory.handle_intent(text)
            if generation != self._generation or self._cancel_flag:
                return
            if local_reply is not None:
                full_text = local_reply
            else:
                # Hide the panel so it doesn't appear in the screenshot.
                # The async sleep lets qasync process the Qt opacity change
                # AND lets pending asyncio tasks (stop_stream cleanup) settle
                # — avoids re-entrancy that processEvents() would cause.
                self._hide_spotlight()
                screenshots = await self._capture_screenshots(focus_region)
                if generation != self._generation or self._cancel_flag:
                    return
                self._current_screenshots = screenshots
                self._mark("captured")

                # Build image content blocks. The window list (~1 ms of Win32 calls,
                # so inline is fine) rides in this request only, never in history.
                image_blocks: list[dict[str, Any]] = []
                windows_text = describe_windows()
                if windows_text:
                    image_blocks.append({"type": "text", "text": windows_text})
                for screenshot in screenshots:
                    b64 = base64.b64encode(screenshot.jpeg_bytes).decode("ascii")
                    image_blocks.append({"type": "text", "text": screenshot.label})
                    image_blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        }
                    )

                # Build messages from conversation history. Walkthrough reminders
                # go only into this request, not into the stored history.
                # Detect active app; learned paths and the KB are both keyed on it.
                window_title = get_foreground_window_title()
                # In a study session, the coach decides how much help this turn
                # gives. Never on walkthrough continuations: those keep the STEP flow.
                directive = None
                if continuing_step is None and self._focus is not None:
                    directive = await self._focus.directive_for(
                        text, app=app_key(window_title), task=task_key(text)
                    )
                    if generation != self._generation or self._cancel_flag:
                        return
                request_text = text
                if screenshots and "selected focus area" in screenshots[0].label:
                    image_blocks.append({
                        "type": "text",
                        "text": "The user selected this focus area as the subject of the question. "
                                "Use the fresh selected image, and give POINT coordinates within "
                                "this image using its stated dimensions and coordinate mode.",
                    })
                if continuing_step is not None:
                    request_text = f"{text}\n{walkthrough_reminder(continuing_step + 1)}"
                elif is_howto_question(text) and (
                    directive is None or directive.allow_walkthrough
                ):
                    request_text = f"{text}\n{walkthrough_reminder()}"
                if directive is not None:
                    request_text = f"{request_text}\n{directive.line}"
                if self._memory is not None:
                    selection = await self._memory.select(text)
                    if selection.prompt_text:
                        image_blocks.insert(0, {"type": "text", "text": selection.prompt_text})
                # Like the reminder, learned context goes into this request only.
                learned = await self._learning_prompt(text, window_title, continuing_step)
                if learned:
                    image_blocks.insert(0, {"type": "text", "text": learned})
                messages = self._history.messages_for_request(
                    current_user_text=request_text,
                    current_images=image_blocks,
                )

                kb_content = None
                app_name = None
                if self._knowledge_dir is not None:
                    apps = load_kb_from_disk(self._knowledge_dir)
                    matched = match_app(window_title, apps)
                    if matched is not None:
                        app_name = matched.name
                        kb_content = select_content(matched, text)
                        logger.info("KB loaded: %s (%d chars)", app_name, len(kb_content))
                    else:
                        logger.debug("no KB match for window: %s", window_title)

                system_prompt = build_system_prompt(
                    kb_content, app_name, point_coords=self._config.point_coords
                )

                if generation != self._generation:
                    return

                # Stay in PROCESSING (spinner) while the model answers, as the
                # macOS app does; RESPONDING starts when there's something to say.
                # If the TTS client can stream, start speaking finished
                # sentences while the rest of the answer is still arriving.
                if hasattr(self._tts, "speak_stream"):
                    queue: asyncio.Queue[str | None] = asyncio.Queue()
                    self._speech = (SpeechChunker(), queue)
                    self._speak_task = asyncio.ensure_future(
                        self._speak("", generation, chunks=self._queue_chunks(queue))
                    )
                # Fly to the [POINT] target as soon as its tag has streamed in.
                self._stream_point_active = True
                try:
                    full_text = await self._llm.send(
                        messages,
                        system=system_prompt,
                        model=self._current_model,
                    )
                except BaseException:
                    self._stream_point_active = False
                    # Cancelled or failed mid-answer: drop any queued audio.
                    if generation == self._generation and self._speech is not None:
                        self._stop_speaking()
                    raise
                self._stream_point_active = False
                self._mark("llm_done")

            # Only commit to history and emit completion if not cancelled.
            # Peek only: self._speech stays set until the queue is closed below,
            # so the outer handlers can stop the speech if anything raises first.
            speech = self._speech if generation == self._generation else None
            if self._cancel_flag or generation != self._generation:
                if speech is not None:
                    self._stop_speaking()
            else:
                self.response_complete.emit(full_text)
                self.success_turn_completed.emit()

                # Strip STEP and POINT tags from the spoken text, fly the
                # companion to the target, and track walkthrough progress.
                concepts: tuple[str, ...] = ()
                if local_reply is not None:
                    # Recall payloads are data: never parse their POINT/STEP tags.
                    spoken_text, point_tag, step = full_text, None, None
                else:
                    without_step, step = parse_step_tag(full_text)
                    without_concepts, concepts = parse_concepts_tag(without_step)
                    spoken_text, point_tag = parse_point_tag(without_concepts)
                # Store the answer without tags, like the macOS app, so old
                # coordinates don't confuse later turns.
                self._history.append(text, spoken_text)
                self._set_state(VoiceState.RESPONDING)
                self.response_annotated.emit(
                    point_tag.label if point_tag is not None else "",
                    step.index if step is not None else 0,
                    step.total if step is not None else 0,
                )
                if step is not None:
                    self._record_step_answer(
                        step, spoken_text, point_tag, concepts,
                        window_title=window_title, task=task_key(text),
                    )
                # An early flight already showed the spotlight; keep it.
                flew_early = self._early_flight is not None
                self._keep_spotlight = flew_early
                try:
                    self._update_walkthrough(step)
                finally:
                    self._keep_spotlight = False
                if step is not None and self._focus is not None:
                    self._focus.walkthrough_step(step.index, spoken_text, concepts)
                # POINT:none (or an unmappable point) means no spotlight.
                if not flew_early:
                    self._hide_spotlight()
                if point_tag is not None and not flew_early:
                    coords = map_point_to_screen(
                        point_tag, screenshots, self._config.point_coords
                    )
                    if coords is not None:
                        coords = await self._snap(coords, point_tag.label)
                        if generation == self._generation:
                            self._fly(coords, step, "POINT", point_tag.label)

                if speech is not None:
                    # Already speaking sentence by sentence: queue the tail and close.
                    chunker, queue = speech
                    for chunk in chunker.finish(full_text):
                        queue.put_nowait(chunk)
                    queue.put_nowait(None)
                    self._speech = None
                    if self._speak_task is not None and self._speak_task.done():
                        # The speech already ended (e.g. a TTS error while the model
                        # was still answering): finish the turn here instead.
                        self.speaking_changed.emit(False)
                        self._set_state(
                            VoiceState.GUIDING if self._walkthrough is not None
                            else VoiceState.IDLE
                        )
                else:
                    self._speak_task = asyncio.ensure_future(self._speak(spoken_text, generation))
                if self._memory is not None and local_reply is None and continuing_step is None:
                    await self._memory.learn_from_turn(text, spoken_text, source_id=str(uuid4()))

        except asyncio.CancelledError:
            logger.debug("turn cancelled")
            if generation == self._generation:
                if self._speech is not None:
                    self._stop_speaking()
                self._set_state(VoiceState.IDLE)

        except Exception as exc:  # noqa: BLE001
            logger.error("turn pipeline error: %s", exc)
            if generation == self._generation:
                if self._speech is not None:
                    self._stop_speaking()
                self._end_walkthrough()
                self.error.emit(str(exc))
                self._set_state(VoiceState.IDLE)

        # On success, stay in RESPONDING so the response text remains
        # visible until the next hotkey press resets to LISTENING.
