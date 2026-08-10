from __future__ import annotations

from datetime import UTC, datetime

from capability_exchange.pilot.gate import (
    PILOT_GATE_TESTS,
    REQUIRED_PILOT_GATES,
    GateRun,
    PilotGateOutcome,
    execute_pilot_gate,
)

COMMIT = "a" * 40
NOW = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)


def runner_with(*failed_gates: str):
    by_tests = {tests: gate for gate, tests in PILOT_GATE_TESTS.items()}

    def run(test_ids: tuple[str, ...]) -> GateRun:
        gate = by_tests[test_ids]
        failed = gate in failed_gates
        return GateRun(
            exit_code=1 if failed else 0,
            output=f"{gate}:{'failed' if failed else 'passed'}",
        )

    return run


def test_exact_build_requires_all_six_gates_and_r3() -> None:
    report = execute_pilot_gate(
        commit=COMMIT,
        runner=runner_with(),
        observed_at=NOW,
    )
    assert tuple(item.gate for item in report.evidence) == REQUIRED_PILOT_GATES
    assert report.exact_build_verified
    assert report.all_six_gates_green
    assert report.r6_redteam_green
    assert report.pilot_start_allowed
    assert report.content_hash == report.canonical_hash()
    assert all(item.commit == COMMIT for item in report.evidence)
    assert all(item.test_ids for item in report.evidence)
    assert all(item.output_sha256 for item in report.evidence)


def test_any_missing_or_failing_gate_blocks_pilot_start() -> None:
    for gate in REQUIRED_PILOT_GATES:
        report = execute_pilot_gate(
            commit=COMMIT,
            runner=runner_with(gate),
            observed_at=NOW,
        )
        assert not report.pilot_start_allowed
        evidence = next(item for item in report.evidence if item.gate == gate)
        assert evidence.outcome is PilotGateOutcome.FAIL


def test_g1_alone_unproven_selects_only_guided_downgrade() -> None:
    report = execute_pilot_gate(
        commit=COMMIT,
        runner=runner_with("G1"),
        observed_at=NOW,
    )
    assert not report.pilot_start_allowed
    assert report.guided_downgrade_available
    assert "guided/export-assisted" in report.explanation


def test_non_g1_failure_has_no_downgrade() -> None:
    report = execute_pilot_gate(
        commit=COMMIT,
        runner=runner_with("G4"),
        observed_at=NOW,
    )
    assert not report.guided_downgrade_available


def test_commit_must_be_the_exact_full_build_sha() -> None:
    import pytest

    with pytest.raises(ValueError, match="40-character"):
        execute_pilot_gate(commit="main", runner=runner_with(), observed_at=NOW)
