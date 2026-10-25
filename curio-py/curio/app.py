"""Curio QApplication bootstrap.

Resolves the config file path via platformdirs, ensures the file exists
(creating from config.example.toml on first run), loads it, and holds
the resulting Config for downstream components to read.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

import qasync
from platformdirs import user_config_dir, user_log_dir
from PySide6.QtCore import QEvent, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from curio.clients.kokoro_tts_client import KokoroTTSClient
from curio.clients.llm_client import LLMClient
from curio.clients.openai_llm_client import OpenAICompatLLMClient
from curio.clients.system_tts_client import SystemTTSClient
from curio.clients.transcription_client import TranscriptionClient
from curio.clients.tts_client import TTSClient
from curio.clients.whisper_transcription_client import WhisperTranscriptionClient
from curio.coaching_runtime import CoachingMode, CoachingRuntime
from curio.companion_manager import CompanionManager
from curio.config import Config, ConfigError, save_share_walkthroughs
from curio.hands_free import HandsFreeController
from curio.hotkey import HotkeyMonitor
from curio.learning_events import (
    FallbackDifficulty,
    LearningServices,
    NullMapSync,
    SqliteEventLog,
    default_event_log_path,
)
from curio.logging_config import configure_logging
from curio.map_sync.client import HttpMapSync
from curio.memory_runtime import MemoryRuntime
from curio.mic_capture import MicCapture
from curio.pet_config import PetSettings, save_pet_selection
from curio.screen_capture import capture_all
from curio.skills import ConceptGraph, SqliteSkillModel
from curio.skills.widget import SkillsWidget
from curio.task_map import SqliteTaskMap
from curio.ui.coaching_window import CoachingWindow
from curio.ui.history_window import HistoryWindow
from curio.ui.memory_window import MemoryWindow
from curio.ui.pet_widget import PetCompanionWidget
from curio.ui.tray_icon import TrayIcon

APP_NAME = "Curio"
APP_AUTHOR = "Curio"

logger = logging.getLogger(__name__)


def _configured_llm(config: Config):
    """Separate clients keep coaching deltas out of the ordinary voice stream."""
    if config.local is not None:
        return OpenAICompatLLMClient(
            base_url=config.local.llm_base_url, api_key=config.local.llm_api_key
        )
    return LLMClient(worker_url=config.worker_url)


def _build_learning(config: Config) -> LearningServices | None:
    """Walkthrough learning, or None when ``[learning] enabled = false``.

    Map sync talks to a server only when ``sync_url`` is set; pushes also need
    the sharing toggle. Pulling sends nothing about the user.
    """
    if not config.learning.enabled:
        return None
    task_map = SqliteTaskMap()
    sync_url = config.learning.sync_url
    map_sync = HttpMapSync(sync_url) if sync_url else NullMapSync()
    skill_model = SqliteSkillModel(
        graph=ConceptGraph.load(),
        difficulty=FallbackDifficulty(map_sync, task_map.local_difficulty),
    )
    return LearningServices(
        event_log=SqliteEventLog(default_event_log_path()),
        task_map=task_map,
        skill_model=skill_model,
        map_sync=map_sync,
        share_walkthroughs=config.learning.share_walkthroughs,
    )


@dataclass
class BootstrapResult:
    app: QApplication
    config: Config | None
    config_error: ConfigError | None
    was_first_run: bool
    config_path: Path
    log_dir: Path


def _example_config_path() -> Path:
    # config.example.toml sits next to the curio package directory
    # (i.e. inside curio-py/, alongside curio/).
    return Path(__file__).resolve().parent.parent / "config.example.toml"


def bootstrap(argv: list[str] | None = None) -> BootstrapResult:
    # Qt 6 sets PROCESS_PER_MONITOR_DPI_AWARE_V2 internally during
    # QApplication init — calling SetProcessDpiAwareness ourselves is
    # redundant and raises "Access is denied" if Qt gets there first.
    # mss captures at raw physical pixels regardless, so no explicit call
    # is needed.

    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_AUTHOR)
    app.setQuitOnLastWindowClosed(False)  # tray app — closing panel must not quit

    # Pass appauthor=False so platformdirs does NOT nest a redundant
    # second "Curio" folder inside the first (which happens when
    # appname == appauthor on Windows). We want %APPDATA%\Curio\config.toml,
    # not %APPDATA%\Curio\Curio\config.toml.
    config_dir = Path(user_config_dir(APP_NAME, appauthor=False, roaming=True))
    config_path = config_dir / "config.toml"
    log_dir = Path(user_log_dir(APP_NAME, appauthor=False))

    was_first_run = Config.ensure_exists(config_path, _example_config_path())

    try:
        config = Config.from_path(config_path)
        config_error = None
    except ConfigError as exc:
        config = None
        config_error = exc

    return BootstrapResult(
        app=app,
        config=config,
        config_error=config_error,
        was_first_run=was_first_run,
        config_path=config_path,
        log_dir=log_dir,
    )


def run() -> int:
    """Start the Curio tray app and run the Qt event loop.

    Wires together the tray icon, floating panel, global hotkey
    monitor, and CompanionManager. Blocks until the user quits
    via the tray menu.
    """
    result = bootstrap()

    log_level = result.config.log_level if result.config else "INFO"
    configure_logging(result.log_dir, log_level)

    if result.was_first_run:
        logger.info("first run: created config at %s", result.config_path)

    if result.config_error is not None:
        logger.warning("config error: %s", result.config_error)

    tray_icon = TrayIcon()
    tray_icon.set_hands_free_available(False)
    companion = PetCompanionWidget(settings=result.config.pet if result.config else PetSettings())
    tray_icon.set_selected_pet(companion.settings.species)
    tray_icon.set_learning_available(False)  # enabled once learning is built

    def select_pet(species: str) -> None:
        try:
            save_pet_selection(result.config_path, species)
        except (OSError, ValueError) as exc:
            logger.error("cannot save pet selection: %s", exc)
            tray_icon.set_selected_pet(companion.settings.species)
            companion.flash_error(str(exc))
            return
        companion.select_pet(species)

    tray_icon.pet_selected.connect(select_pet)
    history = HistoryWindow()

    mic = MicCapture()

    mic.error.connect(lambda msg: logger.error("mic error: %s", msg))


    # Tray menu → settings / history
    tray_icon.show_settings_requested.connect(
        lambda: os.startfile(result.config_path)
    )
    tray_icon.show_history_requested.connect(history.show)
    tray_icon.show_history_requested.connect(history.raise_)

    # ------------------------------------------------------------------
    # Hotkey monitor
    # ------------------------------------------------------------------
    hotkey_binding = result.config.hotkey if result.config is not None else "ctrl+alt"
    hotkey_monitor = HotkeyMonitor(binding=hotkey_binding)

    # ------------------------------------------------------------------
    # CompanionManager (only when config loaded successfully)
    # ------------------------------------------------------------------
    transcription: TranscriptionClient | WhisperTranscriptionClient | None = None
    tts: TTSClient | SystemTTSClient | KokoroTTSClient | None = None
    memory_runtime = None
    memory_window = None
    learning = None
    skills_window = None
    hands_free = None
    coaching_runtime = None
    coaching_window = None
    if result.config is not None:
        memory_runtime = MemoryRuntime(result.config.memory, config_path=result.config_path)
        memory_window = MemoryWindow(
            memory_runtime, settings=memory_runtime.settings,
            save_settings=memory_runtime.save_settings, events=memory_runtime,
        )
        tray_icon.show_memory_requested.connect(memory_window.show)
        tray_icon.show_memory_requested.connect(memory_window.raise_)
        tray_icon.show_memory_requested.connect(memory_window.activateWindow)
        memory_window.settings_changed.connect(memory_window.set_settings)
        local = result.config.local
        llm = _configured_llm(result.config)
        if local is not None:
            logger.info("local backend: %s at %s", local.llm_model, local.llm_base_url)
            transcription = WhisperTranscriptionClient(
                model_name=local.whisper_model, device=local.whisper_device
            )
            if local.tts_engine == "kokoro":
                tts = KokoroTTSClient(voice=local.tts_voice, fallback=SystemTTSClient())
            else:
                tts = SystemTTSClient(voice=local.tts_voice)
        else:
            transcription = TranscriptionClient(worker_url=result.config.worker_url)
            tts = TTSClient(worker_url=result.config.worker_url)
        learning = _build_learning(result.config)
        if learning is not None:
            skills_window = SkillsWidget(learning.skill_model)
            tray_icon.show_skills_requested.connect(skills_window.refresh)
            tray_icon.show_skills_requested.connect(skills_window.show)
            tray_icon.show_skills_requested.connect(skills_window.raise_)
            tray_icon.show_skills_requested.connect(skills_window.activateWindow)
            tray_icon.set_share_walkthroughs(learning.share_walkthroughs)

            def toggle_sharing(enabled: bool) -> None:
                try:
                    save_share_walkthroughs(result.config_path, enabled)
                except (OSError, ConfigError) as exc:
                    logger.error("cannot save sharing setting: %s", exc)
                    tray_icon.set_share_walkthroughs(learning.share_walkthroughs)
                    companion.flash_error(str(exc))
                    return
                learning.share_walkthroughs = enabled
                logger.info("learning: sharing %s", "on" if enabled else "off")

            tray_icon.share_walkthroughs_toggled.connect(toggle_sharing)
            sync_url = result.config.learning.sync_url
            tray_icon.set_learning_available(True, map_server=bool(sync_url))
            tray_icon.open_stuck_map_requested.connect(
                lambda: QDesktopServices.openUrl(QUrl(f"{sync_url}/"))
            )
        manager = CompanionManager(
            config=result.config,
            mic=mic,
            hotkey=hotkey_monitor,
            transcription=transcription,
            llm=llm,
            tts=tts,
            screen_capture_fn=capture_all,
            panel_visibility_controller=companion,
            memory=memory_runtime.conversation,
            learning=learning,
        )
        if local is not None:
            hands_free = HandsFreeController(manager, mic, hotkey_monitor)
            tray_icon.set_hands_free_available(True)
            tray_icon.hands_free_toggled.connect(hands_free.set_enabled)
            hands_free.enabled_changed.connect(tray_icon.set_hands_free_enabled)
            hands_free.error.connect(companion.show_error)
            hands_free.error.connect(lambda msg: logger.warning("hands-free: %s", msg))

        capture_lock = asyncio.Lock()

        async def capture_for_coaching():
            # Only the feature's explicit share-screen button calls this adapter.
            async with capture_lock:
                mode = coaching_runtime.mode
                visible = [w for w in (coaching_window, history, memory_window)
                           if w is not None and w.isVisible()]
                companion.hide_for_capture()
                for window in visible:
                    window.hide()
                try:
                    await asyncio.sleep(0.05)
                    return await asyncio.to_thread(capture_all)
                finally:
                    companion.restore_after_capture()
                    for window in visible:
                        if window is not coaching_window or coaching_runtime.mode == mode:
                            window.show()

        coaching_runtime = CoachingRuntime(
            _configured_llm(result.config), result.config.default_model,
            capture=capture_for_coaching,
        )
        coaching_window = CoachingWindow(coaching_runtime)
        manager.attach_coaching(coaching_runtime)
        tray_icon.show_tutorial_requested.connect(
            lambda: coaching_window.open_mode(CoachingMode.TUTORIAL)
        )
        tray_icon.show_tutor_requested.connect(
            lambda: coaching_window.open_mode(CoachingMode.TUTORING)
        )
        tray_icon.assistant_requested.connect(coaching_runtime.stop_session)
        result.app.aboutToQuit.connect(coaching_runtime.interrupt)

        # State → companion
        manager.state_changed.connect(companion.set_state)
        manager.response_delta.connect(companion.text_started)
        manager.speaking_changed.connect(companion.set_speaking)
        manager.security_warning.connect(companion.security_warning)

        # Audio level → companion waveform
        manager.audio_level.connect(companion.set_audio_level)

        # Transcription → log
        manager.final_transcript.connect(
            lambda text: logger.info("final transcript: %s", text)
        )

        # LLM response → log
        manager.response_complete.connect(
            lambda text: logger.info("response complete: %s", text[:400])
        )

        # Errors → log + companion
        manager.error.connect(
            lambda msg: logger.error("error: %s", msg)
        )
        manager.error.connect(companion.show_error)

        # Transcription → history window
        manager.interim_transcript.connect(history.append_interim)
        manager.final_transcript.connect(history.set_final)

        # LLM response → history window
        manager.response_delta.connect(history.append_delta)
        manager.response_complete.connect(history.commit_turn)

        # Errors → history window
        manager.error.connect(history.show_error)

    hotkey_monitor.start()
    tray_icon.show()
    # Tray "Show Curio" toggle (persisted).
    tray_icon.show_cursor_toggled.connect(companion.set_cursor_enabled)
    if tray_icon.show_cursor:
        companion.start()  # fade in, then "hey! i'm curio"
    else:
        companion.set_cursor_enabled(False)
    if result.config_error is not None:
        # Without a valid config nothing else works; say so on screen.
        companion.show()
        companion.show_error(f"config problem: {result.config_error}")

    # Ensure the pynput listener thread is stopped before the app exits,
    # otherwise Python may hang on interpreter shutdown waiting for it
    # (pynput's helper thread is not always daemonic on Windows).
    result.app.aboutToQuit.connect(hotkey_monitor.stop)
    result.app.aboutToQuit.connect(companion.hide)

    # Use qasync to bridge the Qt event loop with asyncio so that
    # asyncio.create_task / ensure_future work inside Qt signal handlers.
    loop = qasync.QEventLoop(result.app)
    asyncio.set_event_loop(loop)

    # Allow Ctrl+C to quit cleanly — qasync swallows SIGINT by default.
    signal.signal(signal.SIGINT, lambda *_: result.app.quit())

    with loop:
        if hands_free is not None:
            hands_free.set_enabled(tray_icon.hands_free_enabled)
        # Load local models up front so the first question isn't slow.
        if isinstance(transcription, WhisperTranscriptionClient):
            loop.create_task(transcription.preload())
        if isinstance(tts, KokoroTTSClient):
            loop.create_task(tts.preload())
        if learning is not None:
            loop.create_task(learning.start())
        loop.run_forever()
        if hands_free is not None:
            hands_free.close()
        mic.stop()
        if learning is not None:
            if skills_window is not None:
                skills_window.close()
            loop.run_until_complete(learning.aclose())
        if coaching_window is not None:
            loop.run_until_complete(coaching_window.aclose())
        if coaching_runtime is not None:
            manager.detach_coaching()
            loop.run_until_complete(coaching_runtime.aclose())
            result.app.aboutToQuit.disconnect(coaching_runtime.interrupt)
            coaching_window.deleteLater()
            coaching_runtime.deleteLater()
            result.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if memory_window is not None:
            memory_window.close()
        if memory_runtime is not None:
            loop.run_until_complete(memory_runtime.close())
    return 0
