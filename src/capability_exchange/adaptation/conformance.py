"""Release-gate index for executable T1–T9 evidence (M4/T9)."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from capability_exchange.adaptation.contract import Guarantee
from capability_exchange.adapter import AdapterContract
from capability_exchange.conformance.checks import (
    CheckResult,
    check_adaptation_gate_evidence,
)

__all__ = [
    "REQUIRED_T_TEST_IDS",
    "AdaptationConformanceReport",
    "run_adaptation_conformance",
]

REQUIRED_T_TEST_IDS: Final = MappingProxyType(
    {
        "T1": "tests/adaptation/test_preview.py",
        "T2": "tests/adaptation/test_allowlist.py",
        "T3": "tests/adaptation/test_approval.py",
        "T4": "tests/adaptation/test_recovery.py",
        "T5": "tests/adaptation/test_receipt.py",
        "T6": "tests/adaptation/test_transaction_faults.py",
        "T7": "tests/adaptation/test_verification.py",
        "T8": "tests/adaptation/test_undo.py",
        "T9": "tests/conformance/test_adaptation_conformance.py",
    }
)

_GATE_GUARANTEES: Final = {
    "T1": frozenset({Guarantee.PREVIEW_IDENTITY}),
    "T2": frozenset({Guarantee.PREVIEW_IDENTITY}),
    "T3": frozenset({Guarantee.PERMISSION}),
    "T4": frozenset({Guarantee.RECOVERY}),
    "T5": frozenset({Guarantee.OWNERSHIP}),
    "T6": frozenset({Guarantee.RECEIPT}),
    "T7": frozenset({Guarantee.VERIFICATION}),
    "T8": frozenset({Guarantee.UNDO}),
    "T9": frozenset(Guarantee),
}


@dataclass(frozen=True, slots=True)
class AdaptationConformanceReport:
    adapter_id: str
    results: tuple[CheckResult, ...]

    @property
    def failed(self) -> tuple[CheckResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    @property
    def automation_enabled(self) -> bool:
        return bool(self.results) and not self.failed


def run_adaptation_conformance(
    contract: AdapterContract, *, passed_test_ids: frozenset[str]
) -> AdaptationConformanceReport:
    """Require real named suite evidence; contract declarations alone prove nothing."""

    results: list[CheckResult] = []
    for gate, test_id in REQUIRED_T_TEST_IDS.items():
        results.append(
            check_adaptation_gate_evidence(
                contract,
                gate=gate,
                required_test_id=test_id,
                passed_test_ids=passed_test_ids,
                required_guarantees=_GATE_GUARANTEES[gate],
            )
        )
    return AdaptationConformanceReport(
        adapter_id=contract.adapter_id,
        results=tuple(results),
    )
