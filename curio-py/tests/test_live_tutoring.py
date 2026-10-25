import asyncio

import pytest

from curio.live_tutoring import TutoringService, Unsupported
from curio.live_tutoring.checker import polynomial
from curio.live_tutoring.widget import TutoringWidget


def session():
    tutor = TutoringService()
    tutor.start("2*x*(x^2+1)^2")
    return tutor


def test_complete_sequence_and_understanding():
    tutor = session()
    for step in ("u=x^2+1", "du=2*x*dx", "I=u^2", "F=u^3/3+C"):
        assert tutor.submit(step).status == "confirmed"
    assert tutor.submit("F=(x^2+1)^3/3+C").status == "confirmed"
    assert tutor.check_understanding("2*x").status == "confirmed"
    assert tutor.check_understanding("x").status == "incorrect"
    assert len(tutor.attempts) == 5


def test_related_practice_requires_verified_completion_and_is_unassisted():
    tutor = session()
    with pytest.raises(Unsupported):
        tutor.start_practice()
    for step in ("u=x^2+1", "du=2*x*dx", "I=u^2", "F=u^3/3+C"):
        tutor.submit(step)
    assert tutor.practice_problem is None
    assert tutor.submit("F=(x^2+1)^3+C").status == "incorrect"
    assert tutor.practice_problem is None
    feedback = tutor.submit("F=(x^2+1)^3/3+C")
    assert "Related unassisted problem" in feedback.message
    assert polynomial(tutor.practice_problem) != tutor.integrand
    tutor.start_practice()
    assert tutor.unassisted and not tutor.complete
    assert tutor.attempts == [] and tutor.substitution is None
    assert "Unassisted practice" in tutor.help()
    assert tutor.submit("u=(x+1)^2+1").status == "needs_clarification"
    assert tutor.substitution is None
    assert tutor.submit("F=x+C").status == "incorrect"
    assert tutor.submit("F=((x+1)^2+1)^3/3+C").status == "confirmed"
    tutor.start("x")
    assert not tutor.unassisted and tutor.practice_problem is None


def test_guided_completion_does_not_establish_independent_understanding():
    tutor = session()
    for step in ("u=x^2+1", "du=2*x*dx", "I=u^2"):
        tutor.submit(step)
    tutor.help()
    tutor.help()
    tutor.help()  # A worked example cannot count as independent understanding.
    guided = tutor.submit("F=(x^2+1)^3/3+C")
    assert guided.completion_kind == "guided_completion"
    tutor.check_understanding("2*x")
    assert "has not yet been demonstrated" in tutor.progress_message
    assert len(tutor.completions) == 1
    original_record = tutor.completions[0]
    tutor.submit("F=(x^2+1)^3/3+C")
    assert len(tutor.completions) == 1  # Repeated answers do not inflate progress.
    tutor.start_practice()
    assert tutor.completion_kind is None
    assert "has not yet been demonstrated" in tutor.progress_message
    incorrect = tutor.submit("F=x+C")
    assert incorrect.completion_kind is None
    assert len(tutor.completions) == 1
    independent = tutor.submit("F=((x+1)^2+1)^3/3+C")
    assert independent.completion_kind == "independent_demonstration"
    assert "without in-app coaching" in tutor.progress_message
    assert len(tutor.completions) == 2
    assert tutor.completions[0] == original_record
    assert len(tutor.completions[1].attempts) == 2


def test_widget_offers_practice_and_preserves_completed_transcript(qt_application):
    widget = TutoringWidget()
    widget.problem.setText("2*x*(x^2+1)^2")
    widget.start_button.click()
    for step in ("u=x^2+1", "du=2*x*dx", "I=u^2", "F=(x^2+1)^3/3+C"):
        widget.step.setText(step)
        widget.submit_button.click()
    assert widget.practice_button.isEnabled()
    previous = widget.workspace.toPlainText()
    widget.practice_button.click()
    assert widget.workspace.toPlainText().startswith(previous)
    assert widget.service.unassisted
    assert not widget.help_button.isEnabled()
    assert not widget.voice_button.isEnabled()
    assert not widget.practice_button.isEnabled()
    widget.close()


def test_first_error_and_recovery():
    tutor = session()
    assert tutor.submit("I=u^2").status == "needs_clarification"
    tutor.submit("u=x^2+1")
    assert tutor.submit("du=x*dx").status == "incorrect"
    assert tutor.differential is None
    tutor.submit("du=2*x*dx")
    assert tutor.submit("I=2*u^2").status == "incorrect"
    assert tutor.transformed is None
    tutor.submit("I=u^2")
    assert tutor.submit("F=u^3+C").status == "incorrect"
    assert tutor.submit("F=u^3/3").status == "incorrect"
    assert tutor.primitive is None
    assert tutor.submit("F=u^3/3+C").status == "confirmed"
    tutor.submit("u=x")
    assert tutor.differential is tutor.transformed is tutor.primitive is None


@pytest.mark.parametrize(
    "text",
    ["sin(x)", "__import__('os')", "x^-1", "x/0", "x**1000", "x.y", "[x]", "2x", "x+u", "1.5*x"],
)
def test_unsupported_is_explicit(text):
    tutor = session()
    assert tutor.submit("u=" + text).status == "unsupported"
    assert tutor.substitution is None


def test_exact_rational_equivalence_and_bounds():
    assert polynomial("(x+1)^2") == polynomial("x*x+2*x+1")
    assert polynomial("x/3+x/6") == polynomial("x/2")
    with pytest.raises(Unsupported):
        polynomial("x" * 300)


def test_assessments_use_only_explicit_statuses():
    tutor = session()
    assert tutor.submit("").status == "needs_clarification"
    assert tutor.submit("u=").status == "needs_clarification"
    assert tutor.submit("I=u^2").status == "needs_clarification"
    assert tutor.submit("u=sin(x)").status == "unsupported"
    assert tutor.submit("u=x^2+1").status == "confirmed"
    assert tutor.submit("du=x*dx").status == "incorrect"
    assert {attempt.feedback.status.value for attempt in tutor.attempts} == {
        "confirmed",
        "incorrect",
        "needs_clarification",
        "unsupported",
    }


@pytest.mark.parametrize(
    "answer",
    [
        "(x^2+1)^3/3+C",
        "C+(x^6+3*x^4+3*x^2+1)/3",
        "(x^2+1)^3/3-C+7",
        "((x^2+1)^3+2*C)/3",
    ],
)
def test_equivalent_answers_and_free_constants(answer):
    tutor = session()
    for step in ("u=x^2+1", "du=2*x*dx", "I=u^2"):
        tutor.submit(step)
    assert tutor.submit("F=" + answer).status == "confirmed"
    assert tutor.complete


@pytest.mark.parametrize(
    "answer, status",
    [
        ("(x^2+1)^3/3+7", "incorrect"),
        ("(x^2+1)^3/3+C-C", "incorrect"),
        ("(x^2+1)^3/3+x*C", "unsupported"),
        ("(x^2+1)^3/3+1/x+C", "unsupported"),
        ("log(x)+C", "unsupported"),
    ],
)
def test_constants_and_domains_are_not_guessed(answer, status):
    tutor = session()
    for step in ("u=x^2+1", "du=2*x*dx", "I=u^2"):
        tutor.submit(step)
    assert tutor.submit("F=" + answer).status == status
    assert not tutor.complete
    assert "All real" in tutor.domain


def test_help_gradually_reveals_worked_steps():
    tutor = session()
    tutor.submit("u=x^2+1")
    assert "du=" not in tutor.help()
    assert "chain rule" in tutor.help()
    assert "du=" in tutor.help()
    tutor.submit("du=2*x*dx")
    assert "I=" not in tutor.help()
    tutor.help()
    assert "I=" in tutor.help()
    tutor.submit("I=u^2")
    assert "F=" not in tutor.help()
    tutor.help()
    assert "F=" in tutor.help()


def test_capture_confirmation_and_stale_completion():
    async def run():
        async def capture():
            return [b"image"]

        async def recognize(images):
            assert images == [b"image"]
            return "u=x^2+9"

        tutor = session()
        tutor.capture, tutor.recognize = capture, recognize
        await tutor.capture_equations()
        assert tutor.substitution is None and not tutor.attempts
        tutor.confirm_equation("u=x^2+1")
        assert tutor.substitution == polynomial("x^2+1")
        with pytest.raises(Unsupported):
            tutor.confirm_equation("du=2*x*dx")
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(images):
            entered.set()
            await release.wait()
            return "u=x"

        tutor.recognize = delayed
        task = asyncio.create_task(tutor.capture_equations())
        await entered.wait()
        tutor.start("x")
        release.set()
        assert await task is None
        assert tutor.pending is None

    asyncio.run(run())


def test_widget_retains_attempts_and_voice_is_question(qt_application):
    questions = []
    widget = TutoringWidget(voice_callback=lambda text, service: questions.append(text) or "Hint")
    widget.problem.setText("2*x*(x^2+1)^2")
    widget.start_button.click()
    widget.step.setText("u=x^2+1")
    widget.submit_button.click()
    widget.step.setText("du=x*dx")
    widget.submit_button.click()
    widget.submit_voice_question("Why is the two needed?")
    assert len(widget.service.attempts) == 2
    assert questions == ["Why is the two needed?"]
    text = widget.workspace.toPlainText()
    assert "Problem:" in text and "u=x^2+1" in text and "du=x*dx" in text
    assert "does not match" in text
    widget.service.pending = "du=2*x*dx"
    widget.recognized.setText(widget.service.pending)
    widget.confirm_button.setEnabled(True)
    widget.confirm_button.click()
    assert widget.service.differential == polynomial("2*x")
    widget.close()


def test_shared_provider_evidence_requests_and_cancellation():
    from curio.coaching_contract import (
        AssessmentStatus,
        CancellationToken,
        CoachingSession,
        Goal,
        RequestContext,
        SessionStatus,
        SubmittedWork,
    )
    from curio.live_tutoring.contract import TutoringProvider

    async def run():
        provider = TutoringProvider()
        events = []
        provider.subscribe_events(lambda event: 1 / 0)
        unsubscribe = provider.subscribe_events(events.append)
        initial = CoachingSession(id="s", goals=(Goal(id="g", description="Integrate"),))

        def context(request):
            return RequestContext(
                session_id="s", request_id=request, cancellation=CancellationToken()
            )

        first = context("open")
        provider.open(initial, "2*x", context=first)
        work = SubmittedWork(id="w", session_id="s", text="u=x^2")
        result = await provider.assess(provider.session, work, context=context("assess"))
        assert result.status == AssessmentStatus.CONFIRMED
        assert result.evidence[0].sources[0].uri == "work:w"
        assert first.cancellation.cancelled
        with pytest.raises(ValueError):
            await provider.assess(provider.session, work, context=context("duplicate"))
        provider.cancel()
        assert events[-1].payload.status == SessionStatus.CANCELLED
        assert events[-1].context.cancellation.cancelled
        unsubscribe()
        unsubscribe()

    asyncio.run(run())
