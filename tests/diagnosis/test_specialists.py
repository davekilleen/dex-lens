"""Bounded specialist proposals and deterministic disagreement handling."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_exchange.catalogue.v2 import CapabilityAvailabilityV2
from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.specialists import (
    DISAGREEMENT_REASON,
    ProposalContext,
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    SpecialistShard,
    ValidatedProposal,
    issue_shard,
    mint_evidence_token,
    reconcile_proposals,
    validate_proposal,
)

RUN_ID = "run:" + "a" * 16
FINGERPRINT_DIGEST = "sha256:" + "b" * 64
CATALOGUE_DIGEST = "sha256:" + "c" * 64
DEFAULT_CATALOGUE_ID = "daily-planning"
DEFAULT_CAPABILITY_ID = "planning"
CURRENT_EVIDENCE = "current:evidence"


def proposal_context(
    *,
    evidence_ids: tuple[str, ...] = (CURRENT_EVIDENCE,),
    held_ids: tuple[str, ...] = (),
    catalogue_ids: tuple[str, ...] | None = None,
    capability_ids: tuple[str, ...] | None = None,
    collapsed_provenance_ids: tuple[str, ...] = (),
    family_contract_present: bool = False,
    run_id: str = RUN_ID,
    fingerprint_digest: str = FINGERPRINT_DIGEST,
    catalogue_digest: str = CATALOGUE_DIGEST,
) -> ProposalContext:
    known_catalogue = catalogue_ids
    if known_catalogue is None:
        known_catalogue = (DEFAULT_CATALOGUE_ID, *held_ids)
    known_capabilities = capability_ids
    if known_capabilities is None:
        known_capabilities = (DEFAULT_CAPABILITY_ID,)
    return ProposalContext(
        run_id=run_id,
        fingerprint_digest=fingerprint_digest,
        catalogue_digest=catalogue_digest,
        evidence_ids=evidence_ids,
        catalogue_ids=known_catalogue,
        capability_ids=known_capabilities,
        held_ids=held_ids,
        collapsed_provenance_ids=collapsed_provenance_ids,
        family_contract_present=family_contract_present,
    )


def proposal(**overrides: object) -> SpecialistProposal:
    values: dict[str, object] = {
        "role": SpecialistRole.TOOLS_AND_INTEGRATIONS,
        "kind": ProposalKind.MAPPING,
        "run_id": RUN_ID,
        "fingerprint_digest": FINGERPRINT_DIGEST,
        "catalogue_digest": CATALOGUE_DIGEST,
        "catalogue_id": DEFAULT_CATALOGUE_ID,
        "capability_id": DEFAULT_CAPABILITY_ID,
        "disposition": Disposition.SHARED,
        "evidence_ids": (CURRENT_EVIDENCE,),
        "reason": "The local method matches the signed catalogue method.",
    }
    values.update(overrides)
    return SpecialistProposal.model_validate(values)


def recommendation(catalogue_id: str) -> SpecialistProposal:
    return proposal(
        kind=ProposalKind.RECOMMENDATION,
        catalogue_id=catalogue_id,
        disposition=Disposition.WORTH_BORROWING,
    )


def test_proposal_cannot_reference_another_run() -> None:
    with pytest.raises(SpecialistProposalError, match="current fingerprint"):
        validate_proposal(
            proposal(evidence_ids=("foreign:evidence",)),
            context=proposal_context(evidence_ids=("current:evidence",)),
        )


def test_specialist_cannot_recommend_held_capability() -> None:
    with pytest.raises(SpecialistProposalError, match="not available"):
        validate_proposal(
            recommendation("held-capability"),
            context=proposal_context(held_ids=("held-capability",)),
        )


def test_specialist_roles_are_closed() -> None:
    assert [role.value for role in SpecialistRole] == [
        "tools-and-integrations",
        "automations-and-live-state",
        "strength-and-reciprocal",
        "contradictions-and-reliability",
        "release-distance",
        "sceptical-reconciler",
    ]


def test_invented_role_string_is_refused() -> None:
    with pytest.raises(ValidationError, match="tools-and-integrations"):
        proposal(role="invented-oracle")


def test_catalogue_availability_has_no_held_member() -> None:
    assert set(CapabilityAvailabilityV2.__args__) == {"active", "dormant", "parked"}
    assert "held" not in set(CapabilityAvailabilityV2.__args__)


def test_matching_proposals_coalesce_sorted_evidence_ids() -> None:
    context = proposal_context(evidence_ids=("current:a", "current:b", "current:c"))
    first = proposal(
        evidence_ids=("current:b", "current:a"),
        role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
    )
    second = proposal(
        evidence_ids=("current:c", "current:a"),
        role=SpecialistRole.SCEPTICAL_RECONCILER,
    )

    reconciled = reconcile_proposals((first, second), context=context)

    assert len(reconciled) == 1
    assert reconciled[0].kind is ProposalKind.MAPPING
    assert reconciled[0].catalogue_id == DEFAULT_CATALOGUE_ID
    assert reconciled[0].capability_id == DEFAULT_CAPABILITY_ID
    assert reconciled[0].disposition is Disposition.SHARED
    assert reconciled[0].evidence_ids == ("current:a", "current:b", "current:c")


def test_conflicting_dispositions_become_not_assessed() -> None:
    context = proposal_context()
    first = proposal(disposition=Disposition.STRONG_HERE)
    second = proposal(
        role=SpecialistRole.SCEPTICAL_RECONCILER,
        disposition=Disposition.FRAGILE_OR_CONTRADICTORY,
    )

    reconciled = reconcile_proposals((first, second), context=context)

    assert len(reconciled) == 1
    assert reconciled[0].disposition is Disposition.NOT_ASSESSED
    assert reconciled[0].reason == DISAGREEMENT_REASON
    assert reconciled[0].reason == (
        "Specialist proposals disagreed; the comparison remains Unknown."
    )


def test_no_confidence_score_breaks_a_tie() -> None:
    assert "confidence" not in SpecialistProposal.model_fields
    assert "confidence" not in ValidatedProposal.model_fields
    with pytest.raises(ValidationError):
        proposal(confidence=0.99)

    context = proposal_context()
    sceptical_first = reconcile_proposals(
        (
            proposal(
                role=SpecialistRole.SCEPTICAL_RECONCILER,
                disposition=Disposition.NOT_RELEVANT,
            ),
            proposal(disposition=Disposition.STRONG_HERE),
        ),
        context=context,
    )
    praise_first = reconcile_proposals(
        (
            proposal(disposition=Disposition.STRONG_HERE),
            proposal(
                role=SpecialistRole.SCEPTICAL_RECONCILER,
                disposition=Disposition.NOT_RELEVANT,
            ),
        ),
        context=context,
    )

    assert sceptical_first == praise_first
    assert sceptical_first[0].disposition is Disposition.NOT_ASSESSED
    assert sceptical_first[0].reason == DISAGREEMENT_REASON


def test_recommendation_cap_is_enforced_at_set_level() -> None:
    catalogue_ids = tuple(f"borrow-{index}" for index in range(4))
    context = proposal_context(catalogue_ids=catalogue_ids)
    proposals = tuple(recommendation(catalogue_id) for catalogue_id in catalogue_ids)

    validate_proposal(proposals[0], context=context)
    validate_proposal(proposals[1], context=context)
    validate_proposal(proposals[2], context=context)

    with pytest.raises(SpecialistProposalError, match="at most three"):
        reconcile_proposals(proposals, context=context)

    two_specialists = (
        recommendation("borrow-0").model_copy(
            update={"role": SpecialistRole.TOOLS_AND_INTEGRATIONS}
        ),
        recommendation("borrow-1").model_copy(
            update={"role": SpecialistRole.STRENGTH_AND_RECIPROCAL}
        ),
        recommendation("borrow-2").model_copy(
            update={"role": SpecialistRole.AUTOMATIONS_AND_LIVE_STATE}
        ),
        recommendation("borrow-3").model_copy(
            update={"role": SpecialistRole.SCEPTICAL_RECONCILER}
        ),
    )
    with pytest.raises(SpecialistProposalError, match="at most three"):
        reconcile_proposals(two_specialists, context=context)


def test_release_distance_without_family_contract_is_refused() -> None:
    usable = proposal(
        role=SpecialistRole.RELEASE_DISTANCE,
        kind=ProposalKind.RELEASE_DISTANCE,
        disposition=Disposition.WORTH_BORROWING,
    )
    with pytest.raises(SpecialistProposalError, match="capability-family contract"):
        validate_proposal(usable, context=proposal_context(family_contract_present=False))

    honest = validate_proposal(
        proposal(
            role=SpecialistRole.RELEASE_DISTANCE,
            kind=ProposalKind.RELEASE_DISTANCE,
            disposition=Disposition.NOT_ASSESSED,
        ),
        context=proposal_context(family_contract_present=False),
    )
    assert honest.disposition is Disposition.NOT_ASSESSED


def test_collapsed_source_provenance_is_refused() -> None:
    with pytest.raises(SpecialistProposalError, match="provenance"):
        validate_proposal(
            proposal(evidence_ids=("collapsed:evidence",)),
            context=proposal_context(
                evidence_ids=("collapsed:evidence",),
                collapsed_provenance_ids=("collapsed:evidence",),
            ),
        )


def test_proposal_identities_must_come_from_the_shard() -> None:
    with pytest.raises(SpecialistProposalError, match="shard"):
        validate_proposal(
            proposal(catalogue_id="foreign-catalogue"),
            context=proposal_context(catalogue_ids=(DEFAULT_CATALOGUE_ID,)),
        )


def test_run_and_digest_bindings_must_match_context() -> None:
    context = proposal_context()
    with pytest.raises(SpecialistProposalError, match="run"):
        validate_proposal(proposal(run_id="run:" + "z" * 16), context=context)
    with pytest.raises(SpecialistProposalError, match="current fingerprint"):
        validate_proposal(proposal(fingerprint_digest="sha256:" + "d" * 64), context=context)
    with pytest.raises(SpecialistProposalError, match="catalogue"):
        validate_proposal(proposal(catalogue_digest="sha256:" + "e" * 64), context=context)


def test_proposal_models_reject_bypasses() -> None:
    item = proposal()
    context = proposal_context()

    with pytest.raises(TypeError, match="validated model_copy"):
        item.copy()
    with pytest.raises(TypeError, match="validated model_copy"):
        context.copy()
    with pytest.raises(ValidationError, match="600"):
        item.model_copy(update={"reason": "x" * 601})
    with pytest.raises(ValidationError, match="8"):
        SpecialistProposal.model_construct(
            **{
                **item.model_dump(),
                "evidence_ids": tuple(f"current:{index}" for index in range(9)),
            }
        )


def test_minted_evidence_tokens_are_bound_to_the_current_fingerprint() -> None:
    first = mint_evidence_token(
        run_id=RUN_ID,
        fingerprint_digest=FINGERPRINT_DIGEST,
        observation_key="skill:daily-plan",
    )
    other_run = mint_evidence_token(
        run_id="run:" + "z" * 16,
        fingerprint_digest=FINGERPRINT_DIGEST,
        observation_key="skill:daily-plan",
    )
    other_fingerprint = mint_evidence_token(
        run_id=RUN_ID,
        fingerprint_digest="sha256:" + "d" * 64,
        observation_key="skill:daily-plan",
    )

    assert first.startswith("evidence:")
    assert first != other_run
    assert first != other_fingerprint
    assert first == mint_evidence_token(
        run_id=RUN_ID,
        fingerprint_digest=FINGERPRINT_DIGEST,
        observation_key="skill:daily-plan",
    )

    context = proposal_context(evidence_ids=(first,))
    validated = validate_proposal(proposal(evidence_ids=(first,)), context=context)
    assert validated.evidence_ids == (first,)
    with pytest.raises(SpecialistProposalError, match="current fingerprint"):
        validate_proposal(proposal(evidence_ids=(other_run,)), context=context)


def test_issue_shard_exposes_only_engine_owned_identities() -> None:
    context = proposal_context(evidence_ids=("current:evidence", "current:other"))
    shard = issue_shard(SpecialistRole.TOOLS_AND_INTEGRATIONS, context=context)

    assert isinstance(shard, SpecialistShard)
    assert shard.role is SpecialistRole.TOOLS_AND_INTEGRATIONS
    assert shard.run_id == RUN_ID
    assert shard.evidence_ids == ("current:evidence", "current:other")
    assert shard.catalogue_ids == (DEFAULT_CATALOGUE_ID,)
    assert shard.capability_ids == (DEFAULT_CAPABILITY_ID,)


def test_specialists_module_does_not_import_follow_on_surfaces() -> None:
    source = Path("src/capability_exchange/diagnosis/specialists.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = (
        "capability_exchange.adaptation",
        "capability_exchange.contribution",
        "capability_exchange.share",
    )
    assert not any(
        module == banned or module.startswith(f"{banned}.")
        for module in imported
        for banned in forbidden
    )
