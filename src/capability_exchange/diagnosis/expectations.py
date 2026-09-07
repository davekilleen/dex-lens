"""Versioned Wow Gate expectation manifest for significant outcome families."""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis.families import build_family_delta
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    ObservationKind,
)
from capability_exchange.diagnosis.run import (
    ExpectationState,
    FamilyMap,
    FamilyMapRow,
    FamilyReleaseDelta,
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
    "observed_release_lineage",
]

#: The bounded SemVer forms Lens accepts for release identities — the same
#: contract ``VersionDistance`` and the map's release fields enforce.
_RELEASE_SHAPE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

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


def observed_release_lineage(
    fingerprint: EvidenceFingerprint,
) -> tuple[str | None, tuple[str, ...]]:
    """The one Dex Core release the approved snapshot proves, with its evidence.

    Returns ``(None, ())`` — the loud Unknown branch — unless the release
    observations agree on exactly one release-shaped ``release-id``.  This is
    the single lineage derivation both the pass-1 family map and the closing
    ``_version_distance`` consume, so the early map and the final ledger can
    never disagree about whether lineage was established.
    """

    release_observations = tuple(
        observation
        for observation in fingerprint.observations
        if observation.kind is ObservationKind.RELEASE and observation.identity == "dex-core"
    )
    observed_versions = {
        attribute.value
        for observation in release_observations
        for attribute in observation.attributes
        if attribute.key == "release-id"
    }
    if len(observed_versions) != 1:
        return None, ()
    inspected_version = next(iter(observed_versions))
    if _RELEASE_SHAPE.fullmatch(inspected_version) is None:
        return None, ()
    evidence = tuple(
        sorted({observation.evidence.reference for observation in release_observations})
    )[:8]
    if not evidence:
        return None, ()
    return inspected_version, evidence


def _family_release_deltas(
    catalogue: CatalogueV2,
    *,
    inspected_release: str | None,
    current_release: str | None,
) -> dict[str, FamilyReleaseDelta]:
    """Per-family signed release gaps, derivable only with both endpoints.

    A family-free catalogue yields no delta (never an invented one), and any
    non-release-shaped signed lineage field disables the whole derivation
    rather than producing a partial story — mirroring ``_version_distance``.
    """

    if (
        inspected_release is None
        or current_release is None
        or inspected_release == current_release
        or not catalogue.capability_families
    ):
        return {}
    entries_by_id = {entry.capability_id: entry for entry in catalogue.capabilities}
    deltas: dict[str, FamilyReleaseDelta] = {}
    try:
        for family in catalogue.capability_families:
            delta = build_family_delta(
                current_version=current_release,
                inspected_version=inspected_release,
                family=family,
                entries=tuple(
                    entries_by_id[member_id]
                    for member_id in family.member_capability_ids
                ),
            )
            if delta is None:
                continue
            deltas[family.family_id] = FamilyReleaseDelta(
                inspected_release=inspected_release,
                current_release=current_release,
                newer_member_ids=delta.introduced_member_ids,
                changed_member_ids=delta.changed_member_ids,
                outcome=delta.outcome,
            )
    except ValueError:
        return {}
    return deltas


def build_family_map(
    catalogue: CatalogueV2,
    fingerprint: EvidenceFingerprint,
    *,
    catalogue_version: int,
    catalogue_sha256: str,
    core_release: str | None = None,
    assessments: tuple[SignificantFamilyAssessment, ...] | None = None,
) -> FamilyMap:
    """Derive the deterministic pass-1 family map from verified inputs only.

    This is the same derivation ``compare()`` folds into the ledger — the
    exact-identity family assessment plus the six-state expectation fold —
    surfaced early: one row per manifest family, in manifest order, each with
    the state, engine-derived evidence references and reason, or the loud
    typed ``not-gated`` placeholder when the catalogue carries no signed
    family contract.  When the observations establish a Verified dex-core
    lineage and the signed catalogue carries families, each row also carries
    its signed release delta; when lineage cannot be established the map's
    ``inspected_release`` is ``None`` — the loud Unknown every map surface
    renders.  Pure and clock-free: two derivations over the same inputs are
    byte-identical, and nothing host-supplied enters a row.
    """

    if assessments is None:
        assessments = assess_significant_families(catalogue, fingerprint)
    expectations = assess_wow_expectations(catalogue, assessments)
    titles = {family.family_id: family.title for family in catalogue.capability_families}
    inspected_release, release_evidence = observed_release_lineage(fingerprint)
    current_release = (
        core_release
        if core_release is not None and _RELEASE_SHAPE.fullmatch(core_release) is not None
        else None
    )
    deltas = _family_release_deltas(
        catalogue,
        inspected_release=inspected_release,
        current_release=current_release,
    )
    return FamilyMap(
        catalogue_version=catalogue_version,
        catalogue_sha256=catalogue_sha256,
        current_release=current_release,
        inspected_release=inspected_release,
        release_evidence_references=release_evidence,
        rows=tuple(
            FamilyMapRow(
                family_id=item.family_id,
                title=titles.get(item.family_id, item.family_id),
                state=item.state,
                evidence_references=tuple(sorted(item.evidence_ids)),
                reason=item.reason,
                release_delta=deltas.get(item.family_id),
            )
            for item in expectations
        ),
    )
