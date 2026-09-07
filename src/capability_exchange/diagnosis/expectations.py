"""Versioned Wow Gate expectation manifest for significant outcome families."""

from __future__ import annotations

from pydantic import Field, field_validator

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis.observations import EvidenceFingerprint
from capability_exchange.diagnosis.run import (
    ExpectationState,
    FamilyMap,
    FamilyMapRow,
    _ValidatedInventoried,
)
from capability_exchange.diagnosis.significant_families import (
    FamilyAssessmentDisposition,
    SignificantFamilyAssessment,
    assess_significant_families,
)

__all__ = [
    "NOT_GATED_REASON",
    "WOW_EXPECTATIONS",
    "ExpectationState",
    "SignificantExpectation",
    "assess_wow_expectations",
    "build_family_map",
]

WOW_EXPECTATIONS: tuple[str, ...] = (
    "meeting-follow-through",
    "living-people-company-context",
    "durable-task-continuity",
    "external-task-interoperability",
    "connected-work-context",
    "pipedrive-pipeline-continuity",
    "daily-weekly-operating-rhythm",
    "durable-work-memory",
    "proactive-health-and-recovery",
    "backup-and-restore-confidence",
    "safe-change-and-rewind",
    "capability-discovery-and-adoption",
    "privacy-safe-feedback-loop",
    "career-growth-evidence",
)

#: The one fixed sentence every not-gated row carries.  A family-free (or
#: partially signed) catalogue can never again yield a silent empty manifest —
#: the first real run's missing release-gap story with no sentence saying why.
NOT_GATED_REASON = (
    "No signed capability-family contract is present in this catalogue; "
    "family coverage cannot be assessed against it."
)


class SignificantExpectation(_ValidatedInventoried):
    family_id: str
    state: ExpectationState
    evidence_ids: tuple[str, ...]
    reason: str = Field(min_length=1, max_length=600)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("expectation evidence identities must be unique")
        return values


def _state_for_assessment(assessment: SignificantFamilyAssessment) -> ExpectationState:
    if assessment.unavailable_member_ids and not assessment.recommendable_member_ids:
        return ExpectationState.NOT_CURRENTLY_AVAILABLE
    if assessment.matched_components and not assessment.unresolved_components:
        return ExpectationState.PRESENT
    if assessment.matched_components:
        return ExpectationState.PARTIAL
    if assessment.disposition is FamilyAssessmentDisposition.NOT_RECOMMENDABLE:
        return ExpectationState.NOT_CURRENTLY_AVAILABLE
    if assessment.disposition is FamilyAssessmentDisposition.UNRESOLVED:
        return ExpectationState.UNKNOWN
    return ExpectationState.UNKNOWN


def assess_wow_expectations(
    catalogue: CatalogueV2,
    assessments: tuple[SignificantFamilyAssessment, ...],
) -> tuple[SignificantExpectation, ...]:
    """Join the fixed manifest to signed family rows exactly once each.

    A catalogue that does not carry the complete signed family contract yields
    fourteen loud ``not-gated`` rows with the fixed reason — never a silent
    empty tuple.  That silence is exactly why the first real run had no
    release-gap story and no sentence saying why.
    """

    by_id = {item.family_id: item for item in assessments}
    signed_ids = {family.family_id for family in catalogue.capability_families}
    if set(WOW_EXPECTATIONS) - signed_ids:
        return tuple(
            SignificantExpectation(
                family_id=family_id,
                state=ExpectationState.NOT_GATED,
                evidence_ids=(),
                reason=NOT_GATED_REASON,
            )
            for family_id in WOW_EXPECTATIONS
        )
    if len(by_id) != len(assessments):
        raise ValueError("duplicate family assessment in wow expectation input")
    rows: list[SignificantExpectation] = []
    for family_id in WOW_EXPECTATIONS:
        if family_id not in by_id:
            raise ValueError("wow expectation is missing a required family assessment")
        assessment = by_id[family_id]
        rows.append(
            SignificantExpectation(
                family_id=family_id,
                state=_state_for_assessment(assessment),
                evidence_ids=assessment.evidence_references,
                reason=assessment.reason,
            )
        )
    return tuple(rows)


def build_family_map(
    catalogue: CatalogueV2,
    fingerprint: EvidenceFingerprint,
    *,
    catalogue_version: int,
    catalogue_sha256: str,
    assessments: tuple[SignificantFamilyAssessment, ...] | None = None,
) -> FamilyMap:
    """Derive the deterministic pass-1 family map from verified inputs only.

    This is the same derivation ``compare()`` folds into the ledger — the
    exact-identity family assessment plus the six-state expectation fold —
    surfaced early: one row per manifest family, in manifest order, each with
    the state, engine-derived evidence references and reason, or the loud
    typed ``not-gated`` placeholder when the catalogue carries no signed
    family contract.  Pure and clock-free: two derivations over the same
    inputs are byte-identical, and nothing host-supplied enters a row.
    """

    if assessments is None:
        assessments = assess_significant_families(catalogue, fingerprint)
    expectations = assess_wow_expectations(catalogue, assessments)
    titles = {family.family_id: family.title for family in catalogue.capability_families}
    return FamilyMap(
        catalogue_version=catalogue_version,
        catalogue_sha256=catalogue_sha256,
        rows=tuple(
            FamilyMapRow(
                family_id=item.family_id,
                title=titles.get(item.family_id, item.family_id),
                state=item.state,
                evidence_references=tuple(sorted(item.evidence_ids)),
                reason=item.reason,
            )
            for item in expectations
        ),
    )
