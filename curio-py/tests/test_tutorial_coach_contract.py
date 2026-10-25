import asyncio
import json
from types import SimpleNamespace

import pytest

from curio.coaching_contract import (
    AssessmentStatus,
    AssistanceLevel,
    CancellationToken,
    CoachingReply,
    EventKind,
    Evidence,
    EvidenceKind,
    ExtractedContent,
    RequestContext,
    SessionStatus,
    SourceReference,
    StepAssessment,
)
from curio.tutorial_coach import Coach, CoachError

from .test_tutorial_coach import Model, run
from .test_tutorial_coach_security import fetcher, page
from .test_tutorial_coach_session import prepared


def test_contract_extractor_and_provenance():
    async def scenario():
        service, _ = fetcher([page()])
        context = RequestContext(
            session_id="session", request_id="request", cancellation=CancellationToken()
        )
        result = await service.extract(
            SourceReference(id="source", uri="https://example.com"), context=context
        )
        assert "Open File" in result.text
        assert result.sources[1].uri == "https://example.com#open"
        assert result.sources[1].locator == "block 2"

        class Extractor:
            async def extract(self, source, *, context):
                context.cancellation.raise_if_cancelled()
                return ExtractedContent(
                    text="Open File menu; choose Export",
                    sources=(
                        SourceReference(
                            id="section", uri="https://example.com/ref", locator="section 2"
                        ),
                    ),
                )

        model = Model(
            json.dumps(
                {
                    "steps": [
                        {
                            "instruction": "Open File",
                            "expected": "Menu visible",
                            "sources": [1],
                        }
                    ]
                }
            )
        )
        coach = Coach(model, "local", extractor=Extractor())
        await coach.prepare("https://example.com")
        assert coach.session.steps[0].sources[0].locator == "section 2"

    run(scenario())


def test_shared_coaching_provider_levels_events_and_restart():
    async def scenario():
        coach, _ = await prepared()
        events = []
        remove = coach.subscribe_events(events.append)
        coach.subscribe_events(lambda event: 1 / 0)  # Broken listener is isolated.

        class Provider:
            async def coach(self, session, question, *, level, work, content, context):
                assert context.session_id == session.id == question.session_id
                assert question.step_id == session.steps[0].id
                assert work is None
                assert content.sources
                context.cancellation.raise_if_cancelled()
                return CoachingReply(text="Look for File", level=level, sources=content.sources)

        coach.coaching_provider = Provider()
        coach.start()
        session_id = coach.session.id
        await coach.ask("Where is the menu?")
        reply = events[-1]
        assert reply.kind == EventKind.REPLY_READY
        assert reply.payload.level == AssistanceLevel.HINT
        old_context = reply.context
        await coach.explain()
        assert old_context.cancellation.cancelled
        assert events[-1].payload.level == AssistanceLevel.EXPLANATION
        coach.pause()
        assert events[-1].payload.status == SessionStatus.PAUSED
        coach.stop()
        assert events[-1].payload.status == SessionStatus.CANCELLED
        assert events[-1].context.cancellation.cancelled
        coach.start()
        assert coach.session.id != session_id
        remove()
        remove()
        await coach.aclose()

    run(scenario())


@pytest.mark.parametrize("stale", [False, True])
def test_independent_verifier_receives_current_ephemeral_artifact(stale):
    async def scenario():
        async def capture():
            return [SimpleNamespace(jpeg_bytes=b"current image", label="screen 1")]

        coach, _ = await prepared(capture=capture)
        references = []

        class Verifier:
            async def assess(self, session, work, *, context):
                assert session.goals[0].success_criteria == ("File menu visible",)
                assert context.session_id == work.session_id == session.id
                ref = work.sources[0]
                assert coach.read_artifact(ref.uri).jpeg_bytes == b"current image"
                references.append(ref)
                return StepAssessment(
                    session_id=session.id,
                    work_id="old-work" if stale else work.id,
                    step_id=work.step_id,
                    status=AssessmentStatus.CONFIRMED,
                    rationale="Independent application-specific verifier observed the File menu.",
                    evidence=(
                        Evidence(
                            id="observation",
                            kind=EvidenceKind.VERIFIER_RESULT,
                            summary="Menu matches application-specific criteria",
                            sources=(ref,),
                        ),
                    ),
                )

        coach.verification_provider = Verifier()
        coach.start()
        if stale:
            with pytest.raises(CoachError, match="different work"):
                await coach.check_screen(authorized=True)
            assert coach.assessment is None
        else:
            result = await coach.check_screen(authorized=True)
            assert result.status == "verified"
            assert coach.last_assessment.status == AssessmentStatus.CONFIRMED
            coach.accept_verified()
            assert coach.completions == {0: "independently_verified"}
        with pytest.raises(KeyError):
            coach.read_artifact(references[0].uri)

    run(scenario())


def test_cancelled_capture_that_suppresses_cancellation_cannot_send_images():
    async def scenario():
        started = asyncio.Event()

        async def capture():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return [SimpleNamespace(jpeg_bytes=b"private", label="screen")]

        coach, model = await prepared(capture=capture)
        coach.start()
        task = asyncio.create_task(coach.check_screen(authorized=True))
        await started.wait()
        coach.stop()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(model.calls) == 1
        assert not coach._artifacts

    run(scenario())


def test_provider_failure_notification_has_no_private_error_text():
    async def scenario():
        coach, _ = await prepared()
        notices = []
        coach.subscribe_notifications(notices.append)

        class Provider:
            async def coach(self, *args, **kwargs):
                raise RuntimeError("private secret response")

        coach.coaching_provider = Provider()
        coach.start()
        with pytest.raises(CoachError) as error:
            await coach.ask("What next?")
        assert "private secret" not in str(error.value)
        assert notices[-1].code == "tutorial.request_failed"
        assert "private secret" not in notices[-1].message

    run(scenario())
