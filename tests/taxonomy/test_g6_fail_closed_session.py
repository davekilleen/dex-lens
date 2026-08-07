"""G6 fail-closed session tests (module M-C slice).

Gate source of truth: docs/handoff/sources/gates.md G6, fail-closed clause:
"Classifier unavailable or errors → all jobs treated as high-impact for
that session." Automation is the privilege that gets withdrawn, never the
safety.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from capability_exchange.evidence.states import EvidenceState
from capability_exchange.taxonomy.classifier import (
    ClassificationBasis,
    ImpactClassification,
    SessionClassifier,
    automated_adaptation_allowed,
)

BENIGN_JOB = "Summarize my meeting notes into action items"


def _exploding_classifier(
    description: object, contract_fields: Mapping[str, object] | None = None
) -> ImpactClassification:
    raise RuntimeError("classifier is down")


class TestClassifierErrorFailsClosedForTheSession:
    def test_error_yields_high_impact_not_an_exception(self) -> None:
        session = SessionClassifier(classify_fn=_exploding_classifier)
        result = session.classify("Send a status email")
        assert result.high_impact
        assert result.basis is ClassificationBasis.CLASSIFIER_UNAVAILABLE
        assert result.evidence_state is EvidenceState.NOT_ASSESSED
        assert not automated_adaptation_allowed(result)

    def test_after_one_error_all_jobs_are_high_impact_for_the_session(self) -> None:
        calls = {"n": 0}

        def flaky(
            description: object, contract_fields: Mapping[str, object] | None = None
        ) -> ImpactClassification:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("one-off failure")
            raise AssertionError("a failed session must never re-enter the classifier")

        session = SessionClassifier(classify_fn=flaky)
        first = session.classify("Send a status email")
        assert first.high_impact
        assert session.failed

        # Even a genuinely benign job is treated as high-impact now — and
        # the underlying classifier is not consulted again this session.
        for _ in range(3):
            later = session.classify(BENIGN_JOB)
            assert later.high_impact
            assert later.basis is ClassificationBasis.CLASSIFIER_UNAVAILABLE
            assert not automated_adaptation_allowed(later)
        assert calls["n"] == 1

    def test_wrong_typed_result_is_a_classifier_defect_and_fails_closed(self) -> None:
        def wrong_type(
            description: object, contract_fields: Mapping[str, object] | None = None
        ) -> ImpactClassification:
            return "benign"  # type: ignore[return-value]

        session = SessionClassifier(classify_fn=wrong_type)
        result = session.classify(BENIGN_JOB)
        assert result.high_impact
        assert result.basis is ClassificationBasis.CLASSIFIER_UNAVAILABLE
        assert session.failed

    def test_base_exceptions_are_not_swallowed(self) -> None:
        def interrupted(
            description: object, contract_fields: Mapping[str, object] | None = None
        ) -> ImpactClassification:
            raise KeyboardInterrupt

        session = SessionClassifier(classify_fn=interrupted)
        with pytest.raises(KeyboardInterrupt):
            session.classify(BENIGN_JOB)


class TestHealthySessionBehavior:
    def test_healthy_session_classifies_normally(self) -> None:
        session = SessionClassifier()
        assert not session.failed
        assert session.classify("Send a status email to the team").high_impact
        benign = session.classify(BENIGN_JOB)
        assert not benign.high_impact
        assert not session.failed

    def test_recovery_requires_a_new_session(self) -> None:
        broken = SessionClassifier(classify_fn=_exploding_classifier)
        broken.classify(BENIGN_JOB)
        assert broken.failed
        # The failed session never recovers in place; a fresh session does.
        fresh = SessionClassifier()
        assert not fresh.classify(BENIGN_JOB).high_impact
        assert broken.classify(BENIGN_JOB).high_impact
