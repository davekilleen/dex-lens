"""Bounded specialist proposal shards and deterministic validation.

Specialists improve recall; they never become authorities. This module
accepts opaque, schema-bound claims, checks them against engine-owned
evidence tokens, and coalesces or refuses them. Writing conclusions stays
with the later deterministic engine.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum

from pydantic import Field, field_validator

from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.ranking import (
    MAX_EVIDENCE_IDS,
    MAX_REASON_LENGTH,
    MAX_RECOMMENDATIONS,
    RecommendationFactors,
)
from capability_exchange.diagnosis.run import _ValidatedInventoried, canonical_json_digest

__all__ = [
    "DISAGREEMENT_REASON",
    "MAX_EVIDENCE_IDS",
    "MAX_REASON_LENGTH",
    "MAX_RECOMMENDATIONS",
    "ProposalContext",
    "ProposalKind",
    "SpecialistProposal",
    "SpecialistProposalError",
    "SpecialistRole",
    "SpecialistShard",
    "ValidatedProposal",
    "issue_shard",
    "mint_evidence_token",
    "reconcile_proposals",
    "validate_proposal",
]

DISAGREEMENT_REASON = "Specialist proposals disagreed; the comparison remains Unknown."
_RUN_ID = re.compile(r"^run:[a-z0-9]{16,64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SpecialistProposalError(ValueError):
    """A specialist proposal cannot be accepted against the current run."""


class SpecialistRole(StrEnum):
    """Closed specialist roles. Adapters may not invent another string."""

    TOOLS_AND_INTEGRATIONS = "tools-and-integrations"
    AUTOMATIONS_AND_LIVE_STATE = "automations-and-live-state"
    PEOPLE_AND_WORK_CONTINUITY = "people-and-work-continuity"
    OPERATING_RHYTHM_AND_MEMORY = "operating-rhythm-and-memory"
    STRENGTH_AND_RECIPROCAL = "strength-and-reciprocal"
    CONTRADICTIONS_AND_RELIABILITY = "contradictions-and-reliability"
    RELEASE_DISTANCE = "release-distance"
    WORKFLOW_SYNTHESIS = "workflow-synthesis"
    SCEPTICAL_RECONCILER = "sceptical-reconciler"


class ProposalKind(StrEnum):
    """Closed kinds of opaque claim a specialist may offer."""

    MAPPING = "mapping"
    METHOD_COMPARISON = "method-comparison"
    STRENGTH = "strength"
    RECIPROCAL = "reciprocal"
    FRAGILITY = "fragility"
    RECOMMENDATION = "recommendation"
    RELEASE_DISTANCE = "release-distance"


def _unique_identities(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if _ID.fullmatch(value) is None:
            raise ValueError(f"{label} must be bounded identities")
    return values


def _unique_tokens(
    values: tuple[str, ...],
    label: str,
    *,
    max_items: int | None = None,
) -> tuple[str, ...]:
    if max_items is not None and len(values) > max_items:
        raise ValueError(f"{label} may cite at most {max_items} evidence tokens")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if not value.strip():
            raise ValueError(f"{label} must be non-empty")
    return values


class SpecialistShard(_ValidatedInventoried):
    """Bounded identity slice issued to one specialist for one run."""

    role: SpecialistRole
    run_id: str = Field(pattern=_RUN_ID.pattern)
    fingerprint_digest: str = Field(pattern=_SHA256.pattern)
    catalogue_digest: str = Field(pattern=_SHA256.pattern)
    evidence_ids: tuple[str, ...]
    catalogue_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    observation_ids: tuple[str, ...] = ()

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_tokens(values, "shard evidence tokens")

    @field_validator("catalogue_ids")
    @classmethod
    def _catalogue_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identities(values, "shard catalogue identities")

    @field_validator("capability_ids")
    @classmethod
    def _capability_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identities(values, "shard capability identities")

    @field_validator("observation_ids")
    @classmethod
    def _observation_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identities(values, "shard observation identities")


class SpecialistProposal(_ValidatedInventoried):
    """One untrusted, evidence-referenced specialist claim."""

    role: SpecialistRole
    kind: ProposalKind
    run_id: str = Field(pattern=_RUN_ID.pattern)
    fingerprint_digest: str = Field(pattern=_SHA256.pattern)
    catalogue_digest: str = Field(pattern=_SHA256.pattern)
    catalogue_id: str = Field(pattern=_ID.pattern)
    capability_id: str = Field(pattern=_ID.pattern)
    disposition: Disposition
    recommendation_factors: RecommendationFactors | None = None
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_IDS)
    observation_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_tokens(values, "proposal evidence tokens", max_items=MAX_EVIDENCE_IDS)

    @field_validator("observation_ids")
    @classmethod
    def _observation_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identities(values, "proposal observation identities")

    @field_validator("reason")
    @classmethod
    def _reason_is_one_safe_line(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a proposal reason must be non-empty")
        if _CONTROL.search(value):
            raise ValueError("a proposal reason must be one bounded line")
        return value


class ProposalContext(_ValidatedInventoried):
    """Engine-owned facts a proposal may cite for the current fingerprint."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    fingerprint_digest: str = Field(pattern=_SHA256.pattern)
    catalogue_digest: str = Field(pattern=_SHA256.pattern)
    evidence_ids: tuple[str, ...]
    catalogue_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    held_ids: tuple[str, ...] = ()
    collapsed_provenance_ids: tuple[str, ...] = ()
    family_contract_present: bool = False
    observation_ids: tuple[str, ...] = ()

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_tokens(values, "context evidence tokens")

    @field_validator("catalogue_ids")
    @classmethod
    def _catalogue_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identities(values, "context catalogue identities")

    @field_validator("capability_ids")
    @classmethod
    def _capability_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identities(values, "context capability identities")

    @field_validator("observation_ids")
    @classmethod
    def _observation_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identities(values, "context observation identities")

    @field_validator("held_ids")
    @classmethod
    def _held_ids_are_unavailable_identities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """IDs that must not be recommended. Not a catalogue availability state."""

        return _unique_identities(values, "unavailable catalogue identities")

    @field_validator("collapsed_provenance_ids")
    @classmethod
    def _collapsed_tokens_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_tokens(values, "collapsed provenance tokens")


class ValidatedProposal(_ValidatedInventoried):
    """A proposal that cleared validation or a deterministic coalesced result."""

    kind: ProposalKind
    catalogue_id: str = Field(pattern=_ID.pattern)
    capability_id: str = Field(pattern=_ID.pattern)
    disposition: Disposition
    recommendation_factors: RecommendationFactors | None = None
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_IDS)
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    observation_ids: tuple[str, ...] = ()

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_tokens(values, "validated evidence tokens", max_items=MAX_EVIDENCE_IDS)

    @field_validator("observation_ids")
    @classmethod
    def _observation_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identities(values, "validated observation identities")

    @field_validator("reason")
    @classmethod
    def _reason_is_one_safe_line(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a validated reason must be non-empty")
        if _CONTROL.search(value):
            raise ValueError("a validated reason must be one bounded line")
        return value


def mint_evidence_token(
    *,
    run_id: str,
    fingerprint_digest: str,
    observation_key: str,
) -> str:
    """Mint an engine-owned evidence token bound to this run and fingerprint."""

    return "evidence:" + canonical_json_digest(
        {
            "fingerprint_digest": fingerprint_digest,
            "observation_key": observation_key,
            "run_id": run_id,
        }
    )


def issue_shard(role: SpecialistRole, *, context: ProposalContext) -> SpecialistShard:
    """Issue the bounded identity slice one specialist may see."""

    return SpecialistShard(
        role=role,
        run_id=context.run_id,
        fingerprint_digest=context.fingerprint_digest,
        catalogue_digest=context.catalogue_digest,
        evidence_ids=context.evidence_ids,
        catalogue_ids=context.catalogue_ids,
        capability_ids=context.capability_ids,
        observation_ids=context.observation_ids,
    )


def _is_recommendation(proposal: SpecialistProposal | ValidatedProposal) -> bool:
    return (
        proposal.kind is ProposalKind.RECOMMENDATION
        or proposal.disposition is Disposition.WORTH_BORROWING
    )


def _claims_usable_family_distance(proposal: SpecialistProposal) -> bool:
    release_distance = (
        proposal.role is SpecialistRole.RELEASE_DISTANCE
        or proposal.kind is ProposalKind.RELEASE_DISTANCE
    )
    return release_distance and proposal.disposition is not Disposition.NOT_ASSESSED


def validate_proposal(
    proposal: SpecialistProposal,
    context: ProposalContext,
) -> ValidatedProposal:
    """Accept one proposal only when every cited identity belongs to this run."""

    if proposal.run_id != context.run_id:
        raise SpecialistProposalError("proposal run identity does not match the current run")
    if proposal.fingerprint_digest != context.fingerprint_digest:
        raise SpecialistProposalError(
            "proposal fingerprint digest does not match the current fingerprint"
        )
    if proposal.catalogue_digest != context.catalogue_digest:
        raise SpecialistProposalError(
            "proposal catalogue digest does not match the verified catalogue"
        )
    allowed_evidence = set(context.evidence_ids)
    allowed_observations = set(context.observation_ids)
    collapsed = set(context.collapsed_provenance_ids)
    for token in proposal.evidence_ids:
        if token not in allowed_evidence:
            raise SpecialistProposalError(
                "proposal evidence is not present in the current fingerprint"
            )
        if token in collapsed:
            raise SpecialistProposalError(
                "proposal cites evidence whose source provenance has been collapsed"
            )
    for observation_id in proposal.observation_ids:
        if observation_id not in allowed_observations:
            raise SpecialistProposalError(
                "proposal observation identity is not present in the current fingerprint"
            )
    if _is_recommendation(proposal) and proposal.catalogue_id in set(context.held_ids):
        raise SpecialistProposalError(
            f"catalogue identity {proposal.catalogue_id} is not available to recommend"
        )
    if proposal.catalogue_id not in set(context.catalogue_ids):
        raise SpecialistProposalError("proposal catalogue identity is not in the issued shard")
    if proposal.capability_id not in set(context.capability_ids):
        raise SpecialistProposalError("proposal capability identity is not in the issued shard")
    if _claims_usable_family_distance(proposal) and not context.family_contract_present:
        raise SpecialistProposalError(
            "release-distance analysis is disabled until a signed "
            "capability-family contract exists"
        )
    return ValidatedProposal(
        kind=proposal.kind,
        catalogue_id=proposal.catalogue_id,
        capability_id=proposal.capability_id,
        disposition=proposal.disposition,
        recommendation_factors=(
            proposal.recommendation_factors if _is_recommendation(proposal) else None
        ),
        evidence_ids=tuple(sorted(proposal.evidence_ids)),
        reason=proposal.reason,
        observation_ids=tuple(sorted(proposal.observation_ids)),
    )


def _group_key(proposal: ValidatedProposal) -> tuple[str, str, str]:
    return (proposal.kind.value, proposal.catalogue_id, proposal.capability_id)


def _coalesced_recommendation_factors(
    group: list[ValidatedProposal],
) -> RecommendationFactors | None:
    """Retain factors only when every agreeing recommendation supplied the same tuple."""

    recommendation_factors = [
        item.recommendation_factors
        for item in group
        if _is_recommendation(item)
    ]
    factors = [item for item in recommendation_factors if item is not None]
    if not factors:
        return None
    if len(factors) != len(recommendation_factors) or len(set(factors)) != 1:
        return None
    return factors[0]


def _recommendation_factors_conflict(group: list[ValidatedProposal]) -> bool:
    """Detect conflicting complete factor tuples without choosing a winner."""

    factors = [
        item.recommendation_factors
        for item in group
        if _is_recommendation(item)
    ]
    present = [item for item in factors if item is not None]
    return (
        len(factors) > 1
        and bool(present)
        and (len(present) != len(factors) or len(set(present)) > 1)
    )


def _coalesce_group(group: list[ValidatedProposal]) -> ValidatedProposal:
    dispositions = {item.disposition for item in group}
    evidence_ids = tuple(sorted({token for item in group for token in item.evidence_ids}))
    observation_ids = tuple(sorted({token for item in group for token in item.observation_ids}))
    if len(evidence_ids) > MAX_EVIDENCE_IDS:
        raise SpecialistProposalError(
            f"coalesced proposals may cite at most {MAX_EVIDENCE_IDS} evidence tokens"
        )
    sample = group[0]
    if len(dispositions) == 1 and not _recommendation_factors_conflict(group):
        reasons = sorted(item.reason for item in group)
        return ValidatedProposal(
            kind=sample.kind,
            catalogue_id=sample.catalogue_id,
            capability_id=sample.capability_id,
            disposition=sample.disposition,
            recommendation_factors=_coalesced_recommendation_factors(group),
            evidence_ids=evidence_ids,
            reason=reasons[0],
            observation_ids=observation_ids,
        )
    return ValidatedProposal(
        kind=sample.kind,
        catalogue_id=sample.catalogue_id,
        capability_id=sample.capability_id,
        disposition=Disposition.NOT_ASSESSED,
        recommendation_factors=None,
        evidence_ids=evidence_ids,
        reason=DISAGREEMENT_REASON,
        observation_ids=observation_ids,
    )


def _enforce_recommendation_cap(proposals: Iterable[ValidatedProposal]) -> None:
    recommended = [item for item in proposals if _is_recommendation(item)]
    if len(recommended) > MAX_RECOMMENDATIONS:
        raise SpecialistProposalError(
            f"a diagnosis may recommend at most {MAX_RECOMMENDATIONS} Dex additions"
        )


def reconcile_proposals(
    proposals: Iterable[SpecialistProposal],
    *,
    context: ProposalContext,
) -> tuple[ValidatedProposal, ...]:
    """Coalesce agreeing proposals and refuse to break ties with confidence."""

    validated = [validate_proposal(item, context) for item in proposals]
    grouped: dict[tuple[str, str, str], list[ValidatedProposal]] = {}
    for item in validated:
        grouped.setdefault(_group_key(item), []).append(item)
    reconciled = tuple(
        _coalesce_group(grouped[key])
        for key in sorted(grouped)
    )
    _enforce_recommendation_cap(reconciled)
    return reconciled
