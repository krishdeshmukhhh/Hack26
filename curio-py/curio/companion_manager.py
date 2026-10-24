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
from collections import deque
from collections.abc import AsyncGenerator, Callable
from typing import Any, Protocol

from PySide6.QtCore import QByteArray, QObject, QTimer, Signal

from curio.active_window import get_foreground_window_title
from curio.click_watcher import ClickWatcher
from curio.clients.kokoro_tts_client import KokoroTTSClient
from curio.clients.llm_client import LLMClient
from curio.clients.openai_llm_client import OpenAICompatLLMClient
from curio.clients.system_tts_client import SystemTTSClient
from curio.clients.transcription_client import TranscriptionClient
from curio.clients.tts_client import TTSClient
from curio.clients.whisper_transcription_client import WhisperTranscriptionClient
from curio.config import Config
from curio.conversation_history import ConversationHistory
from curio.hotkey import HotkeyMonitor
from curio.knowledge_base import load_kb_from_disk, match_app, select_content
from curio.mic_capture import MicCapture
from curio.point_mapper import map_point_to_screen
from curio.point_parser import StepTag, parse_point_tag, parse_step_tag
from curio.prompts import build_system_prompt, is_howto_question, walkthrough_reminder
from curio.screen_capture import ScreenshotImage
from curio.state import VoiceState

logger = logging.getLogger(__name__)

# After the user's click, give the app a moment to react (menus open,
# dialogs appear) before taking the next step's screenshot.
WALKTHROUGH_SETTLE_SECONDS = 0.8
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._config = config
        self._mic = mic
        self._hotkey = hotkey
        self._transcription = transcription
        self._llm = llm
        self._tts = tts
        self._screen_capture_fn = screen_capture_fn
        self._panel_visibility_controller = panel_visibility_controller

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

        # Guided walkthrough: the step the user is currently doing, if any.
        self._walkthrough: StepTag | None = None
        self._click_watcher = click_watcher or ClickWatcher(self)
        self._click_watcher.clicked.connect(self._on_walkthrough_click)
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

    # ------------------------------------------------------------------
    # PCM deque bridge
    # ------------------------------------------------------------------

    def _on_pcm_chunk(self, chunk: QByteArray) -> None:
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

        self._generation += 1
        self.speaking_changed.emit(False)

        # A new question ends any walkthrough in progress.
        self._end_walkthrough()
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

        self._current_task = asyncio.ensure_future(
            self._transcription.start_stream(self._pcm_async_generator())
        )

    def _on_hotkey_released(self) -> None:
        logger.debug("hotkey released")
        self._set_state(VoiceState.PROCESSING)
        self._mic.stop()
        self._stop_pcm_bridge()
        asyncio.ensure_future(self._transcription.stop_stream())

    def _on_hotkey_cancelled(self) -> None:
        logger.debug("hotkey cancelled")
        self._generation += 1
        self._cancel_flag = True
        self._tts.stop()
        self.speaking_changed.emit(False)
        if self._speak_task is not None and not self._speak_task.done():
            self._speak_task.cancel()
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
        self._mic.stop()
        self._stop_pcm_bridge()
        asyncio.ensure_future(self._transcription.stop_stream())
        # Transition to IDLE directly — the transcription client may not
        # emit a final_transcript if the session never fully started.
        self._set_state(VoiceState.IDLE)

    # ------------------------------------------------------------------
    # Transcription handler
    # ------------------------------------------------------------------

    def _on_final_transcript(self, text: str) -> None:
        if self._state == VoiceState.IDLE:
            # The press was cancelled (or errored) before this transcript
            # arrived — don't start a turn nobody asked for.
            logger.debug("ignoring transcript received while idle")
            return
        if not text:
            # User pressed and released without speaking enough.
            self._set_state(VoiceState.IDLE)
            return

        # Reset cancel flag here (not in _run_turn) so a rapid
        # press between task assignment and coroutine start cannot
        # have its cancellation silently undone.
        self._cancel_flag = False
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
            self.response_delta.emit(text)

    # ------------------------------------------------------------------
    # Error handler
    # ------------------------------------------------------------------

    def _on_error(self, msg: str) -> None:
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        sender = self.sender()
        if sender in (self._llm, self._tts):
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

    def _stop_speaking(self) -> None:
        self._tts.stop()
        if self._speak_task is not None and not self._speak_task.done():
            self._speak_task.cancel()

    def _update_walkthrough(self, step: StepTag | None) -> None:
        """Called once per answer with the answer's [STEP:k/n] tag, if any."""
        if step is not None and step.has_more:
            self._walkthrough = step
            self._click_watcher.start()
            self._walkthrough_timeout.start()
            logger.info("walkthrough: waiting on step %d of %d", step.index, step.total)
        else:
            # Final step given, or the model stopped guiding.
            self._end_walkthrough()

    def _end_walkthrough(self) -> None:
        was_active = self._walkthrough is not None
        self._walkthrough = None
        self._click_watcher.stop()
        self._walkthrough_timeout.stop()
        if was_active:
            logger.info("walkthrough ended")
            self.walkthrough_ended.emit()
        if self._state == VoiceState.GUIDING:
            self._set_state(VoiceState.IDLE)

    def _on_walkthrough_click(self) -> None:
        step = self._walkthrough
        if step is None or self._state not in (VoiceState.RESPONDING, VoiceState.GUIDING):
            return
        logger.info("walkthrough: step %d done, fetching the next one", step.index)
        # One click per step; the next answer re-arms the watcher.
        self._click_watcher.stop()
        self._walkthrough_timeout.stop()
        self._stop_speaking()
        self._set_state(VoiceState.PROCESSING)
        self._cancel_flag = False
        self._current_task = asyncio.ensure_future(self._continue_walkthrough(step))

    async def _continue_walkthrough(self, step: StepTag) -> None:
        try:
            await asyncio.sleep(WALKTHROUGH_SETTLE_SECONDS)
        except asyncio.CancelledError:
            self._set_state(VoiceState.IDLE)
            return
        await self._run_turn(f"i did step {step.index}. what's next?", continuing_step=step.index)

    def _on_escape(self) -> None:
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
            self._end_walkthrough()

    # ------------------------------------------------------------------
    # TTS playback (async, fire-and-forget)
    # ------------------------------------------------------------------

    async def _speak(self, text: str, generation: int | None = None) -> None:
        """Speak text via TTS. State stays RESPONDING during playback."""
        generation = self._generation if generation is None else generation
        if generation != self._generation:
            return

        def started():
            if generation == self._generation and self._state == VoiceState.RESPONDING:
                self.speaking_changed.emit(True)

        def finished():
            if generation == self._generation:
                self.speaking_changed.emit(False)

        self._tts.playback_started.connect(started)
        self._tts.playback_finished.connect(finished)
        try:
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
        try:
            # Yield control so stop_stream (which is still draining after
            # the recv loop emitted final_transcript synchronously) can
            # finish before we do any work that pumps the Qt event loop
            # (hide_for_capture calls processEvents, which would re-enter
            # the stop_stream task and trigger a RuntimeError).
            await asyncio.sleep(0)
            if generation != self._generation:
                return

            # Emit the final transcript so the UI can display it.
            self.final_transcript.emit(text)

            # Hide the panel so it doesn't appear in the screenshot.
            # The async sleep lets qasync process the Qt opacity change
            # AND lets pending asyncio tasks (stop_stream cleanup) settle
            # — avoids re-entrancy that processEvents() would cause.
            self._panel_visibility_controller.hide_for_capture()
            await asyncio.sleep(0.05)
            try:
                screenshots = await asyncio.to_thread(self._screen_capture_fn)
                self._current_screenshots = screenshots
            finally:
                self._panel_visibility_controller.restore_after_capture()

            # Build image content blocks.
            image_blocks: list[dict[str, Any]] = []
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
            request_text = text
            if continuing_step is not None:
                request_text = f"{text}\n{walkthrough_reminder(continuing_step + 1)}"
            elif is_howto_question(text):
                request_text = f"{text}\n{walkthrough_reminder()}"
            messages = self._history.messages_for_request(
                current_user_text=request_text,
                current_images=image_blocks,
            )

            # Detect active app and load KB
            window_title = get_foreground_window_title()
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
            full_text = await self._llm.send(
                messages,
                system=system_prompt,
                model=self._current_model,
            )

            # Only commit to history and emit completion if not cancelled.
            if not self._cancel_flag and generation == self._generation:
                self.response_complete.emit(full_text)
                self.success_turn_completed.emit()

                # Strip STEP and POINT tags from the spoken text, fly the
                # companion to the target, and track walkthrough progress.
                without_step, step = parse_step_tag(full_text)
                spoken_text, point_tag = parse_point_tag(without_step)
                # Store the answer without tags, like the macOS app, so old
                # coordinates don't confuse later turns.
                self._history.append(text, spoken_text)
                self._set_state(VoiceState.RESPONDING)
                self.response_annotated.emit(
                    point_tag.label if point_tag is not None else "",
                    step.index if step is not None else 0,
                    step.total if step is not None else 0,
                )
                self._update_walkthrough(step)
                if point_tag is not None:
                    coords = map_point_to_screen(
                        point_tag, self._current_screenshots, self._config.point_coords
                    )
                    if coords is not None:
                        self._panel_visibility_controller.fly_to(
                            coords[0],
                            coords[1],
                            hold=step is not None and step.has_more,
                            step=(step.index, step.total) if step is not None else None,
                        )
                        logger.info(
                            "POINT: (%d, %d) label=%s",
                            coords[0], coords[1], point_tag.label,
                        )

                self._speak_task = asyncio.ensure_future(self._speak(spoken_text, generation))

        except asyncio.CancelledError:
            logger.debug("turn cancelled")
            if generation == self._generation:
                self._set_state(VoiceState.IDLE)

        except Exception as exc:  # noqa: BLE001
            logger.error("turn pipeline error: %s", exc)
            if generation == self._generation:
                self.error.emit(str(exc))
                self._set_state(VoiceState.IDLE)

        # On success, stay in RESPONDING so the response text remains
        # visible until the next hotkey press resets to LISTENING.
