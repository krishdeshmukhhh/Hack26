"""[focus] config, tray entries and the app-level focus mode builder."""

from __future__ import annotations

import asyncio
from datetime import time, timedelta

import pytest

from curio.config import ConfigError, FocusSettings
from curio.focus_contract import BreakStyle, InterventionKind
from curio.focus_sensing import WindowsActivitySource
from curio.focus_session.wiring import build_focus_mode, policy_settings
from curio.ui.tray_icon import TrayIcon
from tests.test_focus_session_fakes import T0, Clock


def test_focus_settings_defaults_follow_the_research_doc():
    settings = FocusSettings.from_dict({})
    assert (settings.study_minutes, settings.break_minutes) == (25, 5)
    assert settings.break_style == "fixed" and settings.strict is False
    assert settings.max_check_ins_per_hour == 3
    assert settings.model_judgments is True and settings.enabled is True


def test_focus_settings_parse_and_validate():
    settings = FocusSettings.from_dict({
        "study_minutes": 50, "break_minutes": 10, "break_style": "self_paced",
        "strict": True, "quiet_hours": [["22:00", "07:30"]], "model_judgments": False,
        "drift_after_seconds": 120, "sample_seconds": 3,
    })
    assert settings.quiet_hours == (("22:00", "07:30"),)
    policy = policy_settings(settings)
    assert policy.max_spoken_per_hour == 3 and policy.snooze == timedelta(minutes=10)
    assert policy.quiet_hours[0].start == time(22, 0) and policy.quiet_hours[0].end == time(7, 30)
    for bad in (
        {"enabled": "yes"},
        {"study_minutes": 0},
        {"study_minutes": True},
        {"break_style": "pomodoro"},
        {"quiet_hours": [["25:00", "07:00"]]},
        {"quiet_hours": "22:00-07:00"},
        {"drift_after_seconds": 5},
    ):
        with pytest.raises(ConfigError):
            FocusSettings.from_dict(bad)
    with pytest.raises(ConfigError):
        FocusSettings.from_dict([])


def test_tray_focus_entries_swap_start_and_end():
    tray = TrayIcon()
    assert not tray._start_focus_action.isVisible()
    tray.set_focus_active(True)  # ignored while focus mode is off
    assert not tray._end_focus_action.isVisible()
    tray.set_focus_available(True)
    assert tray._start_focus_action.isVisible() and tray._focus_history_action.isVisible()
    emitted = []
    tray.start_focus_requested.connect(lambda: emitted.append("start"))
    tray.end_focus_requested.connect(lambda: emitted.append("end"))
    tray._start_focus_action.trigger()
    tray.set_focus_active(True)
    assert tray._end_focus_action.isVisible() and not tray._start_focus_action.isVisible()
    tray._end_focus_action.trigger()
    assert emitted == ["start", "end"]
    tray.hide()


def test_build_focus_mode_end_to_end_without_a_model(tmp_path):
    async def scenario():
        clock = Clock()
        spoken = []
        settings = FocusSettings.from_dict(
            {"study_minutes": 50, "break_minutes": 10, "strict": True, "model_judgments": False}
        )

        async def frequency():
            return 0.9

        mode = build_focus_mode(
            settings, llm=None, model="m", speak=spoken.append, pet_widget=None,
            interaction_frequency=frequency, clock=clock, data_dir=tmp_path,
            seen_variants=["check_in:0"],
        )
        assert isinstance(mode.runtime.source, WindowsActivitySource)
        assert mode.runtime.classifier.model_enabled is False
        assert "check_in:0" in mode.policy.seen_variants
        mode.start_panel.prefill("excel assignment", 30)
        assert mode.start_panel.strict.isChecked()
        assert mode.start_panel.break_style.currentData() == BreakStyle.FIXED
        mode.start_panel.start()
        assert mode.runtime.active
        plan = mode.runtime.plan
        assert (plan.study_minutes, plan.break_minutes, plan.strict) == (50, 10, True)
        for _ in range(10):
            await asyncio.sleep(0)
        assert mode.presenter.current.kind == InterventionKind.METACOGNITIVE
        assert spoken == [mode.presenter.current.message]
        assert mode.policy._frequency() == 0.9
        # With the planning card open, a spoken reply answers it.
        assert mode.integration.handle_transcript("open the data tab first")
        assert mode.policy.resume_note().next_action == "open the data tab first"
        assert mode.presenter.current is None
        summary = await mode.runtime.end()
        assert summary.goal == "excel assignment"
        await mode.aclose()
        assert (tmp_path / "focus_sessions.sqlite3").exists()  # nothing in the user's folder

    asyncio.run(scenario())


def test_open_start_prefills_from_voice_and_reopens_session_window(tmp_path):
    async def scenario():
        mode = build_focus_mode(
            FocusSettings(), llm=None, model="m", speak=None, pet_widget=None,
            clock=Clock(), data_dir=tmp_path,
        )
        assert mode.integration.handle_transcript("Curio, I'm doing my essay for 45 minutes")
        assert mode.start_panel.isVisible()
        assert mode.start_panel.goal.text() == "my essay"
        assert mode.start_panel.minutes.value() == 45
        mode.start_panel.start()
        mode.open_start()
        assert mode.session_window.isVisible() and not mode.start_panel.isVisible()
        await mode.aclose()

    asyncio.run(scenario())


def test_plan_started_at_comes_from_the_clock(tmp_path):
    async def scenario():
        mode = build_focus_mode(
            FocusSettings(), llm=None, model="m", speak=None, pet_widget=None,
            clock=Clock(), data_dir=tmp_path,
        )
        mode.open_start("essay", 25)
        mode.start_panel.start()
        assert mode.runtime.plan.started_at == T0
        await mode.aclose()

    asyncio.run(scenario())
