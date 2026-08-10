from datetime import UTC, datetime

from capability_exchange.pilot.redteam import (
    REQUIRED_REDTEAM_GATES,
    RedTeamCase,
    RedTeamOutcome,
    evaluate_redteam,
)


def case(gate: str, outcome: RedTeamOutcome = RedTeamOutcome.PASS) -> RedTeamCase:
    return RedTeamCase(
        gate=gate,
        test_id=f"{gate.lower()}-hostile",
        status=outcome,
        commit="pilot-commit",
        evidence_hash=f"hash-{gate}",
        observed_at=datetime.now(UTC),
    )


def test_all_hostile_suites_pass_only_on_exact_commit() -> None:
    report = evaluate_redteam([case(gate) for gate in REQUIRED_REDTEAM_GATES])
    assert report.complete
    assert report.pilot_start_allowed
    assert not report.guided_downgrade_available


def test_missing_g1_selects_guided_downgrade_but_not_pilot_start() -> None:
    report = evaluate_redteam([case(gate) for gate in REQUIRED_REDTEAM_GATES if gate != "G1"])
    assert not report.pilot_start_allowed
    assert report.guided_downgrade_available
    assert "guided/export-assisted" in report.explanation


def test_failure_other_than_g1_has_no_downgrade() -> None:
    cases = [
        case(gate, RedTeamOutcome.FAIL if gate == "G3" else RedTeamOutcome.PASS)
        for gate in REQUIRED_REDTEAM_GATES
    ]
    report = evaluate_redteam(cases)
    assert not report.pilot_start_allowed
    assert not report.guided_downgrade_available
