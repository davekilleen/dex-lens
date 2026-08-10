from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from capability_exchange.pilot.gate import (
    PILOT_GATE_TESTS,
    REQUIRED_PILOT_GATES,
    FormalGateEvidence,
    GateRun,
    PilotGateOutcome,
    execute_pilot_gate,
)
from capability_exchange.pilot.redteam import (
    REQUIRED_REDTEAM_TESTS,
    evaluate_gate_redteam,
)

COMMIT = "a" * 40
NOW = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
FORMAL = tuple(
    FormalGateEvidence(
        evidence_id=evidence_id,
        commit=COMMIT,
        producer="test executor",
        status="proven",
        artifact_sha256="b" * 64,
        test_ids=("tests/pilot/test_pilot_gate.py",),
    )
    for evidence_id in (
        "formal:g1-bind-mount",
        "formal:m3-egress",
        "formal:m4-egress",
        "formal:m5-egress",
    )
)


def run_gate(**kwargs):
    with patch(
        "capability_exchange.pilot.gate._verified_repository_commit",
        return_value=kwargs["commit"],
    ):
        return execute_pilot_gate(formal_evidence=FORMAL, **kwargs)


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
    report = run_gate(
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
        report = run_gate(
            commit=COMMIT,
            runner=runner_with(gate),
            observed_at=NOW,
        )
        assert not report.pilot_start_allowed
        evidence = next(item for item in report.evidence if item.gate == gate)
        assert evidence.outcome is PilotGateOutcome.FAIL


def test_g1_alone_unproven_selects_only_guided_downgrade() -> None:
    report = run_gate(
        commit=COMMIT,
        runner=runner_with("G1"),
        observed_at=NOW,
    )
    assert not report.pilot_start_allowed
    assert report.guided_downgrade_available
    assert "guided/export-assisted" in report.explanation


def test_non_g1_failure_has_no_downgrade() -> None:
    report = run_gate(
        commit=COMMIT,
        runner=runner_with("G4"),
        observed_at=NOW,
    )
    assert not report.guided_downgrade_available


def test_commit_must_be_the_exact_full_build_sha() -> None:
    with pytest.raises(ValueError, match="40-character"):
        run_gate(commit="main", runner=runner_with(), observed_at=NOW)


def test_forged_full_sha_cannot_be_called_the_exact_live_build() -> None:
    live_head = __import__("subprocess").check_output(
        ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parents[2], text=True
    ).strip()
    forged = "f" * 40 if live_head != "f" * 40 else "e" * 40
    with pytest.raises(ValueError, match="live git HEAD"):
        execute_pilot_gate(commit=forged, runner=runner_with(), observed_at=NOW)


@pytest.mark.parametrize(
    "output",
    (
        "1 skipped",
        "gate NOT PROVEN",
        "1 xpassed",
        "2 passed, 1 deselected",
        "no tests ran",
    ),
)
def test_skip_or_unproven_pytest_output_can_never_pass(output: str) -> None:
    def runner(_: tuple[str, ...]) -> GateRun:
        return GateRun(exit_code=0, output=output)

    report = run_gate(commit=COMMIT, runner=runner, observed_at=NOW)
    assert not report.pilot_start_allowed
    assert all(item.outcome is not PilotGateOutcome.PASS for item in report.evidence)


def test_formal_privileged_and_journey_evidence_are_named_gate_inputs() -> None:
    all_test_ids = {test_id for ids in PILOT_GATE_TESTS.values() for test_id in ids}
    assert "formal:g1-bind-mount" in all_test_ids
    assert "formal:m3-egress" in all_test_ids
    assert "formal:m4-egress" in all_test_ids
    assert "formal:m5-egress" in all_test_ids


def test_redteam_report_is_derived_from_every_canonical_executor_result() -> None:
    gate_report = run_gate(commit=COMMIT, runner=runner_with(), observed_at=NOW)
    report = evaluate_gate_redteam(gate_report)
    assert report.pilot_start_allowed
    assert report.source_gate_report_hash == gate_report.content_hash
    assert len(report.cases) == sum(len(ids) for ids in REQUIRED_REDTEAM_TESTS.values())
    assert all(
        case.execution_report_hash == gate_report.content_hash for case in report.cases
    )
