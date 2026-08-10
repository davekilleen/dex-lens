from datetime import UTC, datetime

import pytest

from capability_exchange.pilot.redteam import (
    REQUIRED_REDTEAM_GATES,
    REQUIRED_REDTEAM_TESTS,
    RedTeamCase,
    RedTeamOutcome,
    evaluate_redteam,
)

COMMIT = "a" * 40


def case(gate: str, outcome: RedTeamOutcome = RedTeamOutcome.PASS) -> RedTeamCase:
    return RedTeamCase(
        gate=gate,
        test_id=REQUIRED_REDTEAM_TESTS[gate][0],
        status=outcome,
        commit=COMMIT,
        evidence_hash="b" * 64,
        observed_at=datetime.now(UTC),
    )


def test_all_hostile_suites_pass_only_on_exact_commit() -> None:
    report = evaluate_redteam([case(gate) for gate in REQUIRED_REDTEAM_GATES])
    assert not report.complete
    assert not report.pilot_start_allowed
    assert not report.guided_downgrade_available


def test_missing_g1_selects_guided_downgrade_but_not_pilot_start() -> None:
    report = evaluate_redteam([case(gate) for gate in REQUIRED_REDTEAM_GATES if gate != "G1"])
    assert not report.pilot_start_allowed
    assert not report.guided_downgrade_available


def test_failure_other_than_g1_has_no_downgrade() -> None:
    cases = [
        case(gate, RedTeamOutcome.FAIL if gate == "G3" else RedTeamOutcome.PASS)
        for gate in REQUIRED_REDTEAM_GATES
    ]
    report = evaluate_redteam(cases)
    assert not report.pilot_start_allowed
    assert not report.guided_downgrade_available


def test_explicit_mismatched_commit_cannot_claim_a_pass() -> None:
    report = evaluate_redteam(
        [case(gate) for gate in REQUIRED_REDTEAM_GATES],
        commit="b" * 40,
    )
    assert not report.pilot_start_allowed
    assert not report.complete


def test_noncanonical_test_identity_and_evidence_hash_are_rejected() -> None:
    with pytest.raises(ValueError, match="canonical hostile test identity"):
        RedTeamCase(
            gate="G1",
            test_id="g1-hostile",
            status=RedTeamOutcome.PASS,
            commit=COMMIT,
            evidence_hash="b" * 64,
            observed_at=datetime.now(UTC),
        )


def test_forged_sha_is_not_accepted_as_an_executed_build() -> None:
    forged = RedTeamCase(
        gate="G1",
        test_id="tests/fixtures/hostile/test_g1_prompt_injection.py",
        status=RedTeamOutcome.PASS,
        commit="not-a-git-sha",
        evidence_hash="not-a-sha256",
        observed_at=datetime.now(UTC),
    )
    assert forged.outcome is RedTeamOutcome.FAIL
