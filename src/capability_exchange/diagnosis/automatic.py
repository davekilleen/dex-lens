"""Conservative automatic recommendation candidates without a language model."""

from __future__ import annotations

from capability_exchange.catalogue.v2 import CatalogueV2, capability_availability_of
from capability_exchange.diagnosis.observations import EvidenceFingerprint, ObservationKind
from capability_exchange.diagnosis.ranking import RecommendationCandidate, RecommendationFactors
from capability_exchange.diagnosis.significant_families import SignificantFamilyAssessment
from capability_exchange.diagnosis.workflows import WorkflowGraph

__all__ = ["build_automatic_candidates"]

_BACKUP_RESTORE_CATALOGUE_ID = "backup-restore"


def build_automatic_candidates(
    *,
    catalogue: CatalogueV2,
    fingerprint: EvidenceFingerprint,
    workflows: WorkflowGraph,
    family_assessments: tuple[SignificantFamilyAssessment, ...],
) -> tuple[RecommendationCandidate, ...]:
    """Emit only reviewed rules with complete typed preconditions."""

    del workflows
    if _BACKUP_RESTORE_CATALOGUE_ID not in {
        item.capability_id for item in catalogue.capabilities
    }:
        return ()
    capability = next(
        item
        for item in catalogue.capabilities
        if item.capability_id == _BACKUP_RESTORE_CATALOGUE_ID
    )
    if capability_availability_of(capability) != "active":
        return ()
    backup_family = next(
        (item for item in family_assessments if item.family_id == "backup-and-restore-confidence"),
        None,
    )
    if backup_family is None or not backup_family.matched_components:
        return ()
    backup_observed = any(
        item.kind is ObservationKind.RECOVERY_PROOF for item in fingerprint.observations
    )
    if backup_observed:
        return ()
    evidence = tuple(sorted(backup_family.evidence_references))[:8]
    if not evidence:
        return ()
    return (
        RecommendationCandidate(
            catalogue_id=_BACKUP_RESTORE_CATALOGUE_ID,
            capability_id=_BACKUP_RESTORE_CATALOGUE_ID,
            factors=RecommendationFactors(
                reliability_risk=2,
                job_relevance=2,
                workflow_leverage=2,
                evidence_strength=2,
                adoption_effort=2,
            ),
            evidence_ids=evidence,
            reason=(
                "Backup work is configured in the approved snapshot, but no restore "
                "proof was observed."
            ),
        ),
    )
