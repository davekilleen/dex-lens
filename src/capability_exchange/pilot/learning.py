"""Normalized, privacy-preserving formative learning output (P1/G5)."""

from __future__ import annotations

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.pilot._common import clean_text, tuple_text
from capability_exchange.pilot.analysis import PilotAnalysisReport, PilotVerdict

__all__ = ["LearningOutput", "normalize_learning"]


class LearningOutput(InventoriedModel):
    """Safe summary containing no participant ids, raw values, or source text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_binding_hash: str
    contract_count: int = Field(ge=1)
    verdict: PilotVerdict
    enrolled_count: int = Field(ge=1)
    improved_count: int = Field(ge=0)
    threshold_count: int = Field(ge=1)
    evidence_limit_codes: tuple[str, ...] = ()
    card_learning_count: int = Field(default=0, ge=0)
    formative_only: bool = True
    raw_private_evidence_included: bool = False
    canary_scan_passed: bool = True

    @field_validator("contract_binding_hash")
    @classmethod
    def _id(cls, value: str) -> str:
        return clean_text(value, label="contract_binding_hash", max_length=256)

    @field_validator("evidence_limit_codes")
    @classmethod
    def _limits(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple_text(value, label="evidence_limit_codes")


def _sanitized_limits(
    report: PilotAnalysisReport,
    private_values: tuple[str, ...],
) -> tuple[str, ...]:
    """Map evidence limits to stable codes, never copy their prose verbatim."""

    codes: set[str] = set()
    text = " ".join(report.evidence_limits).lower()
    if "dropout" in text:
        codes.add("dropout")
    if "missing follow-up" in text:
        codes.add("missing-follow-up")
    if "self-report" in text:
        codes.add("self-report-only")
    if "objective" in text:
        codes.add("objective-signal-missing")
    if "claim-supporting" in text or "evidence state" in text:
        codes.add("evidence-state-limited")
    if "severe trust" in text:
        codes.add("trust-floor-stop")
    # If a caller supplies a private canary that appears in an evidence-limit
    # string, emit only the generic private-data code.
    if any(canary and canary.lower() in text for canary in private_values):
        codes.add("private-content-redacted")
    return tuple(sorted(codes))


def normalize_learning(
    report: PilotAnalysisReport,
    *,
    private_values: tuple[str, ...] | list[str] = (),
) -> LearningOutput:
    """Produce normalized learning with no raw participant evidence.

    ``private_values`` is a synthetic canary list used by the hostile suite;
    those strings are never copied to the output and are checked once more in
    the serialized representation before returning.
    """

    canaries = tuple(value for value in private_values if value)
    output = LearningOutput(
        contract_binding_hash=report.contract_binding_hash,
        contract_count=len({item.contract_id for item in report.participant_plan_bindings}),
        verdict=report.verdict,
        enrolled_count=report.enrolled_count,
        improved_count=report.improved_count,
        threshold_count=report.improvement_threshold_count,
        evidence_limit_codes=_sanitized_limits(report, canaries),
        card_learning_count=report.card_learning_count,
        formative_only=True,
        raw_private_evidence_included=False,
        canary_scan_passed=True,
    )
    serialized = output.model_dump_json()
    if any(canary in serialized for canary in canaries):
        # This should be impossible with the schema above.  Keep a defensive
        # fail-closed check in case a future field accidentally copies prose.
        raise ValueError("learning output contains a planted private canary")
    return output
