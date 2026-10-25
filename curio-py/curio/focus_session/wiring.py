"""Build focus mode from ``[focus]`` settings: F1 sensing, F2 policy, F3 coach, F4 UI.

``app.py`` calls ``build_focus_mode`` once the companion manager exists (the
presenter speaks through ``manager.say``), attaches ``mode.integration`` to
the manager, and awaits ``mode.aclose()`` at shutdown. Construct on the Qt
thread; nothing touches disk or the model until a session or window needs it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QPoint

from curio.config import FocusSettings
from curio.focus_contract import BreakStyle
from curio.focus_policy import AdaptiveFocusPolicy, PolicySettings, QuietHours
from curio.focus_sensing import (
    DriftThresholds,
    RuleFirstClassifier,
    SQLiteCorrectionStore,
    ThresholdDriftTracker,
    WindowsActivitySource,
)
from curio.focus_sensing.activity import probe_windows, resolve_app
from curio.focus_session.history_window import FocusHistoryWindow
from curio.focus_session.integration import FocusIntegration
from curio.focus_session.presenter import FocusPresenter, PetWidgetActions
from curio.focus_session.runtime import FocusRuntime, build_model_call
from curio.focus_session.session_window import FocusSessionWindow
from curio.focus_session.start_panel import FocusStartPanel
from curio.focus_session.store import SqliteSessionStore
from curio.focus_session.summary_window import SessionSummaryWindow
from curio.study_coach import EvidenceBasedCoach, SqliteReviewScheduler, generate_review_items

logger = logging.getLogger(__name__)

# Foreground "apps" that mean the learner clicked the tray, not their work.
_NOT_WORK_APPS = {"", "explorer", "curio", "curio", "shellexperiencehost"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def foreground_work_app() -> str:
    """The foreground app to prefill as allowed, unless it's the shell or Curio."""
    try:
        app = resolve_app(probe_windows())
    except Exception:
        return ""
    return "" if app in _NOT_WORK_APPS else app


def policy_settings(settings: FocusSettings) -> PolicySettings:
    return PolicySettings(
        max_spoken_per_hour=settings.max_check_ins_per_hour,
        snooze=timedelta(minutes=settings.snooze_minutes),
        quiet_hours=tuple(
            QuietHours(start=time.fromisoformat(start), end=time.fromisoformat(end))
            for start, end in settings.quiet_hours
        ),
    )


@dataclass
class FocusMode:
    runtime: FocusRuntime
    presenter: FocusPresenter
    integration: FocusIntegration
    policy: AdaptiveFocusPolicy
    start_panel: FocusStartPanel
    session_window: FocusSessionWindow
    summary_window: SessionSummaryWindow
    history_window: FocusHistoryWindow
    _closers: list[Callable[[], Awaitable[object]]] = field(default_factory=list)
    _tasks: set[asyncio.Task] = field(default_factory=set)

    def open_start(self, goal: str = "", minutes: int | None = None) -> None:
        if self.runtime.active:
            self.session_window.show()
            self.session_window.raise_()
            return
        self.start_panel.prefill(goal, minutes)
        self.start_panel.show()
        self.start_panel.raise_()
        self.start_panel.activateWindow()

    def show_history(self) -> None:
        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()

    async def aclose(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        await self.runtime.aclose()
        self.session_window.dispose()
        self.summary_window.dispose()
        self.start_panel.close()
        self.history_window.close()
        self.presenter.clear()
        self.presenter.bubble.close()
        for close in self._closers:
            try:
                await close()
            except Exception:
                logger.exception("focus: closing a store failed")


def build_focus_mode(
    settings: FocusSettings,
    *,
    llm,
    model: str,
    speak: Callable[[str], object] | None,
    pet_widget,
    learning=None,
    interaction_frequency: Callable[[], Awaitable[float | None]] | None = None,
    seen_variants: Iterable[str] = (),
    clock: Callable[[], datetime] = _utc_now,
    data_dir: Path | None = None,
) -> FocusMode:
    """``llm`` is a dedicated client (not the voice one); None = templates and rules only.

    ``data_dir`` puts the three SQLite files somewhere else (tests); by default
    they live in the user's Curio data folder.
    """
    model_call = build_model_call(llm, model) if llm is not None else None

    def path(name: str, default: Path | None) -> Path | None:
        return data_dir / name if data_dir is not None else default

    corrections = SQLiteCorrectionStore(
        path("focus_corrections.sqlite3", SQLiteCorrectionStore.default_path())
    )
    classifier = RuleFirstClassifier(
        corrections, model=model_call, model_enabled=settings.model_judgments
    )
    tracker = ThresholdDriftTracker(
        DriftThresholds(drift_after_seconds=settings.drift_after_seconds)
    )
    policy = AdaptiveFocusPolicy(
        settings=policy_settings(settings), model=model_call, seen_variants=seen_variants
    )
    scheduler = SqliteReviewScheduler(path("study_reviews.sqlite3", None), clock=clock)
    coach = EvidenceBasedCoach(scheduler)
    store = SqliteSessionStore(path("focus_sessions.sqlite3", None))
    source = WindowsActivitySource(interval_seconds=settings.sample_seconds)

    def anchor() -> QPoint | None:
        if pet_widget is None or not pet_widget.isVisible():
            return None
        return QPoint(pet_widget.x() + 48, pet_widget.y())

    presenter = FocusPresenter(
        speak=speak,
        pet=PetWidgetActions(pet_widget) if pet_widget is not None else None,
        anchor=anchor,
    )

    async def generate_reviews(concepts, notes):
        return await generate_review_items(concepts, notes, model_call, now=clock())

    runtime = FocusRuntime(
        source=source,
        classifier=classifier,
        tracker=tracker,
        policy=policy,
        presenter=presenter,
        coach=coach,
        store=store,
        generate_reviews=generate_reviews,
        model_call=model_call,
        clock=clock,
    )
    start_panel = FocusStartPanel(
        suggest=runtime.suggest_if_then,
        foreground_app=foreground_work_app,
        clock=clock,
        study_minutes=settings.study_minutes,
        break_minutes=settings.break_minutes,
        break_style=BreakStyle(settings.break_style),
        strict=settings.strict,
    )
    start_panel.plan_ready.connect(runtime.start)
    session_window = FocusSessionWindow(runtime, clock=clock)
    summary_window = SessionSummaryWindow(runtime, speak=speak, clock=clock)
    history_window = FocusHistoryWindow(
        store, clear_extra=(corrections.clear, scheduler.clear)
    )
    mode: FocusMode
    integration = FocusIntegration(
        runtime, presenter, coach=coach, learning=learning,
        open_start=lambda goal, minutes: mode.open_start(goal, minutes), clock=clock,
    )
    mode = FocusMode(
        runtime=runtime,
        presenter=presenter,
        integration=integration,
        policy=policy,
        start_panel=start_panel,
        session_window=session_window,
        summary_window=summary_window,
        history_window=history_window,
        _closers=[store.close, corrections.close, scheduler.close],
    )

    if interaction_frequency is not None:

        async def refresh_frequency() -> None:
            try:
                value = await interaction_frequency()
            except Exception:
                logger.exception("focus: no interaction frequency from memory")
                return
            if value is not None:
                policy.set_interaction_frequency(max(0.0, min(1.0, float(value))))

        def on_started(_plan) -> None:
            task = asyncio.ensure_future(refresh_frequency())
            mode._tasks.add(task)
            task.add_done_callback(mode._tasks.discard)

        runtime.session_started.connect(on_started)
    return mode
