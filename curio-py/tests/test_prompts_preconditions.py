from curio.prompts import build_system_prompt, walkthrough_reminder


def test_system_prompt_mentions_open_windows_and_preconditions():
    prompt = build_system_prompt()
    assert "list of open windows" in prompt
    assert "window titles" in prompt
    assert "before step 1" in prompt
    assert "desktop background" in prompt
    assert "[STEP:1/N]" in walkthrough_reminder()


def test_reminders_ask_for_screen_checks():
    assert "in the way" in walkthrough_reminder()
    assert "popped up" in walkthrough_reminder(2)
    assert "[STEP:2/N] [CONCEPTS:...]" in walkthrough_reminder(2)
