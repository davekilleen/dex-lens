"""Versioned Wow Gate expectation manifest for significant outcome families."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis.run import _ValidatedInventoried
from capability_exchange.diagnosis.significant_families import (
    FamilyAssessmentDisposition,
    SignificantFamilyAssessment,
)

__all__ = [
    "WOW_EXPECTATIONS",
    "ExpectationState",
    "SignificantExpectation",
    "assess_wow_expectations",
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


class ExpectationState(StrEnum):
    PRESENT = "present"
    PARTIAL = "partial"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    NOT_RELEVANT = "not-relevant"
    NOT_CURRENTLY_AVAILABLE = "not-currently-available"


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
    """Join the fixed manifest to signed family rows exactly once each."""

    by_id = {item.family_id: item for item in assessments}
    signed_ids = {family.family_id for family in catalogue.capability_families}
    if set(WOW_EXPECTATIONS) - signed_ids:
        return ()
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
