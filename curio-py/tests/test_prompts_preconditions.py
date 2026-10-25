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


def test_checks_are_silent_and_openers_banned():
    prompt = build_system_prompt()
    assert "silently check" in prompt
    assert "never narrate a check that passed" in prompt
    assert "start every step with the action" in prompt
    assert "you're in the right place" in prompt  # listed as a banned opener
    assert "SAME number" in prompt
    assert "silently" in walkthrough_reminder()
    assert "silently" in walkthrough_reminder(2)
    assert "same step number" in walkthrough_reminder(2)


def test_walkthrough_examples_start_with_the_action():
    prompt = build_system_prompt()
    examples = prompt.split("multi-step examples:")[1].split("\n\n")[0]
    quoted = [line.split('"')[1] for line in examples.splitlines() if '"' in line]
    assert len(quoted) == 3
    for text in quoted:
        assert not text.startswith(("you're", "you are", "now", "great", "the desktop"))
