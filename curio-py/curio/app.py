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
from PySide6.QtWidgets import QApplication

from curio.clients.llm_client import LLMClient
from curio.clients.openai_llm_client import OpenAICompatLLMClient
from curio.clients.system_tts_client import SystemTTSClient
from curio.clients.transcription_client import TranscriptionClient
from curio.clients.tts_client import TTSClient
from curio.clients.whisper_transcription_client import WhisperTranscriptionClient
from curio.companion_manager import CompanionManager
from curio.config import Config, ConfigError
from curio.hotkey import HotkeyMonitor
from curio.logging_config import configure_logging
from curio.mic_capture import MicCapture
from curio.output_capture import OutputCapture
from curio.pet_config import PetSettings, save_pet_selection
from curio.screen_capture import capture_all
from curio.state import VoiceState
from curio.ui.history_window import HistoryWindow
from curio.ui.pet_widget import PetCompanionWidget
from curio.ui.tray_icon import TrayIcon

APP_NAME = "Curio"
APP_AUTHOR = "Curio"

logger = logging.getLogger(__name__)


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
    companion = PetCompanionWidget(settings=result.config.pet if result.config else PetSettings())
    tray_icon.set_selected_pet(companion.settings.species)

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
    output_capture = OutputCapture()

    mic.error.connect(lambda msg: logger.error("mic error: %s", msg))

    # Output loopback → companion waveform during RESPONDING
    output_capture.audio_level.connect(companion.set_output_level)

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
    if result.config is not None:
        local = result.config.local
        if local is not None:
            logger.info("local backend: %s at %s", local.llm_model, local.llm_base_url)
            transcription = WhisperTranscriptionClient(
                model_name=local.whisper_model, device=local.whisper_device
            )
            llm = OpenAICompatLLMClient(
                base_url=local.llm_base_url, api_key=local.llm_api_key
            )
            tts = SystemTTSClient(voice=local.tts_voice)
        else:
            transcription = TranscriptionClient(worker_url=result.config.worker_url)
            llm = LLMClient(worker_url=result.config.worker_url)
            tts = TTSClient(worker_url=result.config.worker_url)
        manager = CompanionManager(
            config=result.config,
            mic=mic,
            hotkey=hotkey_monitor,
            transcription=transcription,
            llm=llm,
            tts=tts,
            screen_capture_fn=capture_all,
            panel_visibility_controller=companion,
        )

        # State → companion
        manager.state_changed.connect(companion.set_state)
        manager.response_delta.connect(companion.text_started)
        manager.speaking_changed.connect(companion.set_speaking)
        manager.security_warning.connect(companion.security_warning)

        # Start/stop output loopback capture based on state
        def _manage_output_capture(state: VoiceState) -> None:
            if state == VoiceState.RESPONDING:
                output_capture.start()
            else:
                output_capture.stop()

        manager.state_changed.connect(_manage_output_capture)

        # Audio level → companion waveform
        manager.audio_level.connect(companion.set_audio_level)

        # Transcription → log
        manager.final_transcript.connect(
            lambda text: logger.info("final transcript: %s", text)
        )

        # LLM response → log
        manager.response_complete.connect(
            lambda text: logger.info("response complete: %s", text[:120])
        )

        # Errors → log + companion
        manager.error.connect(
            lambda msg: logger.error("error: %s", msg)
        )
        manager.error.connect(companion.flash_error)

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
    companion.show()

    # Ensure the pynput listener thread is stopped before the app exits,
    # otherwise Python may hang on interpreter shutdown waiting for it
    # (pynput's helper thread is not always daemonic on Windows).
    result.app.aboutToQuit.connect(hotkey_monitor.stop)
    result.app.aboutToQuit.connect(companion.hide)
    result.app.aboutToQuit.connect(output_capture.stop)

    # Use qasync to bridge the Qt event loop with asyncio so that
    # asyncio.create_task / ensure_future work inside Qt signal handlers.
    loop = qasync.QEventLoop(result.app)
    asyncio.set_event_loop(loop)

    # Allow Ctrl+C to quit cleanly — qasync swallows SIGINT by default.
    signal.signal(signal.SIGINT, lambda *_: result.app.quit())

    with loop:
        if isinstance(transcription, WhisperTranscriptionClient):
            # Load Whisper up front so the first question isn't slow.
            loop.create_task(transcription.preload())
        loop.run_forever()
    return 0
