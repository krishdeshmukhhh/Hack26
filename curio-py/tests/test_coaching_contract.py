"""Checks for the safety boundaries shared by both coaching features."""

import unittest

from curio.coaching_contract import (
    AssessmentStatus,
    CancellationToken,
    CoachingSession,
    Evidence,
    EvidenceKind,
    OperationCancelled,
    SessionStatus,
    SourceReference,
    StepAssessment,
    TutorialStep,
)


class CoachingContractTests(unittest.TestCase):
    def test_navigation_and_claims_cannot_establish_correctness(self):
        for status in (AssessmentStatus.CONFIRMED, AssessmentStatus.INCORRECT):
            for kind in (EvidenceKind.CLICK, EvidenceKind.MODEL_CLAIM, EvidenceKind.USER_CLAIM):
                with self.subTest(status=status, kind=kind), self.assertRaises(ValueError):
                    StepAssessment(
                        session_id="s",
                        work_id="w",
                        status=status,
                        rationale="claim",
                        evidence=(
                            Evidence(
                                id="e",
                                kind=kind,
                                summary="claim",
                                sources=(SourceReference(id="r", uri="artifact:1"),),
                            ),
                        ),
                    )

    def test_verdict_requires_traceable_evidence(self):
        with self.assertRaises(ValueError):
            StepAssessment(
                session_id="s",
                work_id="w",
                status=AssessmentStatus.CONFIRMED,
                rationale="no evidence",
            )
        with self.assertRaises(ValueError):
            StepAssessment(
                session_id="s",
                work_id="w",
                status=AssessmentStatus.CONFIRMED,
                rationale="no source",
                evidence=(Evidence(id="e", kind=EvidenceKind.OBSERVATION, summary="observed"),),
            )
        assessment = StepAssessment(
            session_id="s",
            work_id="w",
            status=AssessmentStatus.CONFIRMED,
            rationale="matches criterion",
            evidence=(
                Evidence(
                    id="e",
                    kind=EvidenceKind.VERIFIER_RESULT,
                    summary="checked result",
                    sources=(SourceReference(id="r", uri="artifact:result", locator="line 2"),),
                ),
            ),
        )
        self.assertEqual(assessment.work_id, "w")
        for status in (AssessmentStatus.UNSUPPORTED, AssessmentStatus.NEEDS_CLARIFICATION):
            StepAssessment(session_id="s", work_id="w", status=status, rationale="cannot tell")

    def test_steps_do_not_complete_sessions_and_terminal_states_cannot_resume(self):
        session = CoachingSession(
            id="s",
            goals=(),
            steps=(TutorialStep(id="step", goal_id="g", instruction="click next"),),
        )
        self.assertEqual(session.status, SessionStatus.CREATED)
        active = session.transition(SessionStatus.ACTIVE)
        self.assertEqual(
            active.transition(SessionStatus.PAUSED).transition(SessionStatus.ACTIVE).status,
            SessionStatus.ACTIVE,
        )
        for terminal in (SessionStatus.CANCELLED, SessionStatus.COMPLETED, SessionStatus.FAILED):
            with self.subTest(terminal=terminal), self.assertRaises(ValueError):
                active.transition(terminal).transition(SessionStatus.ACTIVE)
        self.assertEqual(session.status, SessionStatus.CREATED)

    def test_cancellation_is_idempotent_and_checked_by_providers(self):
        token = CancellationToken()
        token.raise_if_cancelled()
        token.cancel()
        token.cancel()
        with self.assertRaises(OperationCancelled):
            token.raise_if_cancelled()
