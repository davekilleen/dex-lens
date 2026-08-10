from __future__ import annotations

from capability_exchange.adaptation.conformance import (
    REQUIRED_T_TEST_IDS,
    run_adaptation_conformance,
)
from capability_exchange.adaptation.hosts.claude_code import (
    claude_code_adaptation_contract,
)
from capability_exchange.conformance.checks import CheckOutcome
from capability_exchange.conformance.runner import run_adaptation_conformance_suite


def test_conformance_reports_each_t1_through_t9_independently(tmp_path) -> None:
    contract = claude_code_adaptation_contract((str(tmp_path),))
    report = run_adaptation_conformance(
        contract, passed_test_ids=frozenset(REQUIRED_T_TEST_IDS.values())
    )
    assert tuple(result.gate for result in report.results) == tuple(
        f"T{number}" for number in range(1, 10)
    )
    assert all(result.outcome is CheckOutcome.PASSED for result in report.results)
    assert report.automation_enabled


def test_host_declaration_never_unlocks_missing_runtime_evidence(tmp_path) -> None:
    contract = claude_code_adaptation_contract((str(tmp_path),))
    report = run_adaptation_conformance(contract, passed_test_ids=frozenset())
    assert not report.automation_enabled
    assert all(result.outcome is CheckOutcome.FAILED for result in report.results)


def test_one_missing_gate_evidence_keeps_automation_disabled(tmp_path) -> None:
    contract = claude_code_adaptation_contract((str(tmp_path),))
    for gate, test_id in REQUIRED_T_TEST_IDS.items():
        evidence = frozenset(REQUIRED_T_TEST_IDS.values()) - {test_id}
        report = run_adaptation_conformance(contract, passed_test_ids=evidence)
        failed = tuple(result.gate for result in report.failed)
        assert gate in failed
        assert not report.automation_enabled


def test_diagnose_only_contract_cannot_pass_adaptation_conformance(tmp_path) -> None:
    from capability_exchange.adapters.claude_code.contract import claude_code_contract

    report = run_adaptation_conformance(
        claude_code_contract((str(tmp_path),)),
        passed_test_ids=frozenset(REQUIRED_T_TEST_IDS.values()),
    )
    assert not report.automation_enabled
    assert len(report.failed) == 9


def test_shared_conformance_runner_exposes_the_release_gate(tmp_path) -> None:
    contract = claude_code_adaptation_contract((str(tmp_path),))
    report = run_adaptation_conformance_suite(
        contract,
        passed_test_ids=frozenset(REQUIRED_T_TEST_IDS.values()),
    )
    assert report.automation_enabled
    assert tuple(result.gate for result in report.results) == tuple(
        f"T{number}" for number in range(1, 10)
    )
