"""Bounded specialist proposals and deterministic disagreement handling."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_exchange.catalogue.v2 import CapabilityAvailabilityV2
from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.ranking import RecommendationFactors
from capability_exchange.diagnosis.specialists import (
    DISAGREEMENT_REASON,
    CandidateBaseline,
    ProposalContext,
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    SpecialistShard,
    ValidatedProposal,
    candidate_id_for,
    issue_shard,
    mint_evidence_token,
    reconcile_proposals,
    validate_proposal,
)

RUN_ID = "run:" + "a" * 16
FINGERPRINT_DIGEST = "sha256:" + "b" * 64
CATALOGUE_DIGEST = "sha256:" + "c" * 64
PACKET_DIGEST = "sha256:" + "e" * 64
PACKET_ID = "packet:" + PACKET_DIGEST
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
    analysis_mode: str = "inventory-only",
    packet_id: str | None = None,
    packet_digest: str | None = None,
    packet_role: SpecialistRole | None = None,
    accepted_candidate_ids: tuple[str, ...] = (),
    accepted_candidates: tuple[CandidateBaseline, ...] = (),
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
        analysis_mode=analysis_mode,
        evidence_ids=evidence_ids,
        catalogue_ids=known_catalogue,
        capability_ids=known_capabilities,
        held_ids=held_ids,
        collapsed_provenance_ids=collapsed_provenance_ids,
        family_contract_present=family_contract_present,
        packet_id=packet_id,
        packet_digest=packet_digest,
        packet_role=packet_role,
        accepted_candidate_ids=accepted_candidate_ids,
        accepted_candidates=accepted_candidates,
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


def recommendation(
    catalogue_id: str,
    **overrides: object,
) -> SpecialistProposal:
    values: dict[str, object] = {
        "kind": ProposalKind.RECOMMENDATION,
        "catalogue_id": catalogue_id,
        "disposition": Disposition.WORTH_BORROWING,
        "recommendation_factors": RecommendationFactors(
            reliability_risk=1,
            job_relevance=2,
            workflow_leverage=2,
            evidence_strength=2,
            adoption_effort=2,
        ),
    }
    values.update(overrides)
    return proposal(**values)


def candidate_baseline(
    *,
    kind: ProposalKind = ProposalKind.RECOMMENDATION,
    catalogue_id: str = DEFAULT_CATALOGUE_ID,
    capability_id: str = DEFAULT_CAPABILITY_ID,
    original_disposition: Disposition = Disposition.WORTH_BORROWING,
    recommendation_factors: RecommendationFactors | None = None,
    evidence_ids: tuple[str, ...] = (CURRENT_EVIDENCE,),
    observation_ids: tuple[str, ...] = (),
    disputed_dispositions: tuple[Disposition, ...] = (),
    disputed_recommendation_factors: tuple[RecommendationFactors, ...] = (),
) -> CandidateBaseline:
    if (
        recommendation_factors is None
        and kind is ProposalKind.RECOMMENDATION
        and not disputed_dispositions
    ):
        recommendation_factors = RecommendationFactors(
            reliability_risk=1,
            job_relevance=2,
            workflow_leverage=2,
            evidence_strength=2,
            adoption_effort=2,
        )
    return CandidateBaseline(
        candidate_id=candidate_id_for(kind, catalogue_id, capability_id),
        kind=kind,
        catalogue_id=catalogue_id,
        capability_id=capability_id,
        original_disposition=original_disposition,
        recommendation_factors=recommendation_factors,
        evidence_ids=evidence_ids,
        observation_ids=observation_ids,
        disputed_dispositions=disputed_dispositions,
        disputed_recommendation_factors=disputed_recommendation_factors,
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
        "people-and-work-continuity",
        "operating-rhythm-and-memory",
        "strength-and-reciprocal",
        "contradictions-and-reliability",
        "release-distance",
        "workflow-synthesis",
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
        role=SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
    )

    reconciled = reconcile_proposals((first, second), context=context)

    assert len(reconciled) == 1
    assert reconciled[0].kind is ProposalKind.MAPPING
    assert reconciled[0].catalogue_id == DEFAULT_CATALOGUE_ID
    assert reconciled[0].capability_id == DEFAULT_CAPABILITY_ID
    assert reconciled[0].disposition is Disposition.SHARED
    assert reconciled[0].evidence_ids == ("current:a", "current:b", "current:c")


def test_wide_agreeing_evidence_coalesces_to_the_sorted_first_eight() -> None:
    """RISK-GUIDED-RUN-WEDGE: a coalesced union past MAX_EVIDENCE_IDS is
    deterministically truncated to the first eight of the sorted union
    instead of raising and wedging the run that stored the responses.
    """

    tokens = tuple(f"current:{index:02d}" for index in range(9))
    context = proposal_context(evidence_ids=tokens)
    first = proposal(evidence_ids=tokens[:5])
    second = proposal(
        role=SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
        evidence_ids=tokens[4:9],
    )

    reconciled = reconcile_proposals((first, second), context=context)
    reordered = reconcile_proposals((second, first), context=context)

    assert reconciled == reordered
    assert len(reconciled) == 1
    assert reconciled[0].disposition is Disposition.SHARED
    assert reconciled[0].evidence_ids == tokens[:8]
    assert len(reconciled[0].evidence_ids) == 8


def test_conflicting_dispositions_become_not_assessed() -> None:
    context = proposal_context()
    first = proposal(disposition=Disposition.STRONG_HERE)
    second = proposal(
        role=SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
        disposition=Disposition.FRAGILE_OR_CONTRADICTORY,
    )

    reconciled = reconcile_proposals((first, second), context=context)

    assert len(reconciled) == 1
    assert reconciled[0].disposition is Disposition.NOT_ASSESSED
    # Evolved from the fixed DISAGREEMENT_REASON: the reason now names the
    # disposition set (closed vocabulary, sorted values only) so the dispute
    # stays visible instead of reading as a blank Unknown.
    assert reconciled[0].reason == (
        "Specialist proposals disagreed between fragile-or-contradictory and "
        "strong-here; the sceptical review did not adjudicate, so the "
        "comparison remains Unknown."
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
                role=SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
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
                role=SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
                disposition=Disposition.NOT_RELEVANT,
            ),
        ),
        context=context,
    )

    assert sceptical_first == praise_first
    assert sceptical_first[0].disposition is Disposition.NOT_ASSESSED
    assert sceptical_first[0].reason == (
        "Specialist proposals disagreed between not-relevant and strong-here; "
        "the sceptical review did not adjudicate, so the comparison remains "
        "Unknown."
    )


def test_recommendation_cap_is_enforced_at_set_level() -> None:
    catalogue_ids = tuple(f"borrow-{index}" for index in range(11))
    context = proposal_context(catalogue_ids=catalogue_ids)
    proposals = tuple(recommendation(catalogue_id) for catalogue_id in catalogue_ids[:10])

    assert len(reconcile_proposals(proposals, context=context)) == 10

    with pytest.raises(SpecialistProposalError, match="at most 10"):
        reconcile_proposals(
            (*proposals, recommendation("borrow-10")),
            context=context,
        )

    roles = (
        SpecialistRole.TOOLS_AND_INTEGRATIONS,
        SpecialistRole.STRENGTH_AND_RECIPROCAL,
        SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
        SpecialistRole.WORKFLOW_SYNTHESIS,
    )
    two_specialists = tuple(
        recommendation(f"borrow-{index}").model_copy(update={"role": roles[index % len(roles)]})
        for index in range(11)
    )
    with pytest.raises(SpecialistProposalError, match="at most 10"):
        reconcile_proposals(two_specialists, context=context)


def test_recommendation_factors_are_retained_only_for_recommendations() -> None:
    context = proposal_context()
    accepted_recommendation = validate_proposal(
        recommendation(DEFAULT_CATALOGUE_ID),
        context=context,
    )
    accepted_mapping = validate_proposal(proposal(), context=context)

    assert accepted_recommendation.recommendation_factors is not None
    assert accepted_recommendation.recommendation_factors.job_relevance == 2
    assert accepted_mapping.recommendation_factors is None


def test_specialist_and_validated_reasons_cannot_be_whitespace_only() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        proposal(reason="   ")

    with pytest.raises(ValidationError, match="non-empty"):
        ValidatedProposal(
            kind=ProposalKind.MAPPING,
            catalogue_id=DEFAULT_CATALOGUE_ID,
            capability_id=DEFAULT_CAPABILITY_ID,
            disposition=Disposition.SHARED,
            evidence_ids=(CURRENT_EVIDENCE,),
            reason="   ",
        )


def test_conflicting_recommendation_factors_remain_unresolved() -> None:
    context = proposal_context(evidence_ids=("current:first", "current:second"))
    first = recommendation(DEFAULT_CATALOGUE_ID).model_copy(
        update={
            "evidence_ids": ("current:first",),
            "recommendation_factors": RecommendationFactors(
                reliability_risk=1,
                job_relevance=2,
                workflow_leverage=2,
                evidence_strength=2,
                adoption_effort=2,
            ),
        }
    )
    second = recommendation(DEFAULT_CATALOGUE_ID).model_copy(
        update={
            "role": SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
            "evidence_ids": ("current:second",),
            "recommendation_factors": RecommendationFactors(
                reliability_risk=3,
                job_relevance=2,
                workflow_leverage=2,
                evidence_strength=2,
                adoption_effort=2,
            ),
        }
    )

    reconciled = reconcile_proposals((first, second), context=context)

    assert reconciled[0].disposition is Disposition.NOT_ASSESSED
    assert reconciled[0].reason == (
        "Specialist proposals agreed on worth-borrowing but disagreed on "
        "recommendation factors; the sceptical review did not adjudicate, so "
        "the comparison remains Unknown."
    )
    assert reconciled[0].recommendation_factors is None


def test_missing_and_present_recommendation_factors_remain_unresolved() -> None:
    context = proposal_context(evidence_ids=("current:first", "current:second"))
    first = recommendation(DEFAULT_CATALOGUE_ID).model_copy(
        update={"evidence_ids": ("current:first",)}
    )
    second = recommendation(DEFAULT_CATALOGUE_ID).model_copy(
        update={
            "role": SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
            "evidence_ids": ("current:second",),
            "recommendation_factors": None,
        }
    )

    reconciled = reconcile_proposals((first, second), context=context)

    assert reconciled[0].disposition is Disposition.NOT_ASSESSED
    assert reconciled[0].reason == (
        "Specialist proposals agreed on worth-borrowing but disagreed on "
        "recommendation factors; the sceptical review did not adjudicate, so "
        "the comparison remains Unknown."
    )
    assert reconciled[0].recommendation_factors is None


def test_disagreement_reason_constant_remains_the_generic_fallback() -> None:
    assert DISAGREEMENT_REASON == (
        "Specialist proposals disagreed; the comparison remains Unknown."
    )


def test_disputed_baseline_carries_the_proposed_disposition_set() -> None:
    baseline = candidate_baseline(
        kind=ProposalKind.STRENGTH,
        original_disposition=Disposition.NOT_ASSESSED,
        disputed_dispositions=(
            Disposition.STRONG_HERE,
            Disposition.FRAGILE_OR_CONTRADICTORY,
        ),
    )

    # Canonical: sorted by disposition value, deduplicated.
    assert baseline.disputed_dispositions == (
        Disposition.FRAGILE_OR_CONTRADICTORY,
        Disposition.STRONG_HERE,
    )
    assert baseline.disputed_recommendation_factors == ()

    with pytest.raises(ValidationError, match="not-assessed"):
        candidate_baseline(
            kind=ProposalKind.STRENGTH,
            original_disposition=Disposition.STRONG_HERE,
            disputed_dispositions=(
                Disposition.STRONG_HERE,
                Disposition.FRAGILE_OR_CONTRADICTORY,
            ),
        )
    with pytest.raises(ValidationError, match="factor tuples"):
        candidate_baseline(
            kind=ProposalKind.RECOMMENDATION,
            original_disposition=Disposition.NOT_ASSESSED,
            disputed_dispositions=(
                Disposition.WORTH_BORROWING,
                Disposition.NOT_RELEVANT,
            ),
        )
    with pytest.raises(ValidationError, match="disputed"):
        candidate_baseline(
            kind=ProposalKind.STRENGTH,
            original_disposition=Disposition.STRONG_HERE,
            disputed_recommendation_factors=(
                RecommendationFactors(
                    reliability_risk=1,
                    job_relevance=2,
                    workflow_leverage=2,
                    evidence_strength=2,
                    adoption_effort=2,
                ),
            ),
        )


def _disputed_strength_context() -> tuple[CandidateBaseline, ProposalContext]:
    baseline = candidate_baseline(
        kind=ProposalKind.STRENGTH,
        original_disposition=Disposition.NOT_ASSESSED,
        disputed_dispositions=(
            Disposition.STRONG_HERE,
            Disposition.FRAGILE_OR_CONTRADICTORY,
        ),
    )
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(baseline.candidate_id,),
        accepted_candidates=(baseline,),
    )
    return baseline, context


def test_sceptical_adjudication_selects_only_a_proposed_disposition() -> None:
    baseline, context = _disputed_strength_context()

    def sceptical_item(disposition: Disposition) -> SpecialistProposal:
        return proposal(
            role=SpecialistRole.SCEPTICAL_RECONCILER,
            kind=ProposalKind.STRENGTH,
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            candidate_id=baseline.candidate_id,
            disposition=disposition,
            reason="The contradiction claim does not survive the evidence.",
        )

    adjudicated = validate_proposal(sceptical_item(Disposition.STRONG_HERE), context)
    assert adjudicated.disposition is Disposition.STRONG_HERE

    downgraded = validate_proposal(sceptical_item(Disposition.NOT_RELEVANT), context)
    assert downgraded.disposition is Disposition.NOT_RELEVANT

    # `shared` was never proposed by any specialist: the sceptical reconciler
    # may adjudicate the dispute, never invent a third position.
    with pytest.raises(SpecialistProposalError, match="proposed"):
        validate_proposal(sceptical_item(Disposition.SHARED), context)


def test_disputed_recommendation_adjudication_uses_only_proposed_factor_tuples() -> None:
    factors_a = RecommendationFactors(
        reliability_risk=1,
        job_relevance=2,
        workflow_leverage=2,
        evidence_strength=2,
        adoption_effort=2,
    )
    factors_b = factors_a.model_copy(update={"job_relevance": 3})
    baseline = candidate_baseline(
        original_disposition=Disposition.NOT_ASSESSED,
        disputed_dispositions=(Disposition.WORTH_BORROWING,),
        disputed_recommendation_factors=(factors_a, factors_b),
    )
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(baseline.candidate_id,),
        accepted_candidates=(baseline,),
    )

    def sceptical_item(factors: RecommendationFactors) -> SpecialistProposal:
        return recommendation(
            DEFAULT_CATALOGUE_ID,
            role=SpecialistRole.SCEPTICAL_RECONCILER,
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            candidate_id=baseline.candidate_id,
            recommendation_factors=factors,
        )

    adjudicated = validate_proposal(sceptical_item(factors_b), context)
    assert adjudicated.recommendation_factors == factors_b

    invented = factors_a.model_copy(update={"workflow_leverage": 3})
    with pytest.raises(SpecialistProposalError, match="proposed factor tuples"):
        validate_proposal(sceptical_item(invented), context)


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
    source = Path("src/capability_exchange/diagnosis/specialists.py").read_text(encoding="utf-8")
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


def test_guided_proposal_must_match_packet_identity_and_digest() -> None:
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
    )
    item = recommendation(
        DEFAULT_CATALOGUE_ID,
        packet_id="packet:sha256:" + "0" * 64,
        packet_digest="sha256:" + "0" * 64,
        candidate_id=candidate_id_for(
            ProposalKind.RECOMMENDATION,
            DEFAULT_CATALOGUE_ID,
            DEFAULT_CAPABILITY_ID,
        ),
    )

    with pytest.raises(SpecialistProposalError, match="packet identity"):
        validate_proposal(item, context)


def test_guided_proposal_requires_packet_fields() -> None:
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
    )

    with pytest.raises(SpecialistProposalError, match="packet"):
        validate_proposal(proposal(), context)
    with pytest.raises(ValidationError, match="packet"):
        proposal(packet_id=PACKET_ID)
    with pytest.raises(ValidationError, match="packet"):
        proposal(packet_digest=PACKET_DIGEST)


def test_packet_binding_context_fields_are_all_or_none() -> None:
    with pytest.raises(ValidationError, match="packet"):
        proposal_context(packet_id=PACKET_ID)
    with pytest.raises(ValidationError, match="packet"):
        proposal_context(packet_digest=PACKET_DIGEST)
    with pytest.raises(ValidationError, match="packet"):
        proposal_context(packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS)


def test_bound_and_unbound_proposals_cannot_cross_contexts() -> None:
    bound_item = proposal(
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=candidate_id_for(
            ProposalKind.MAPPING,
            DEFAULT_CATALOGUE_ID,
            DEFAULT_CAPABILITY_ID,
        ),
    )
    with pytest.raises(SpecialistProposalError, match="bound"):
        validate_proposal(bound_item, proposal_context())

    with pytest.raises(SpecialistProposalError, match="packet"):
        validate_proposal(
            proposal(),
            proposal_context(
                analysis_mode="guided-analysis",
                packet_id=PACKET_ID,
                packet_digest=PACKET_DIGEST,
                packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
            ),
        )


def test_guided_proposal_role_must_match_issued_packet() -> None:
    baseline = candidate_baseline(
        kind=ProposalKind.MAPPING,
        original_disposition=Disposition.SHARED,
    )
    normal_context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
    )
    sceptical_item = proposal(
        role=SpecialistRole.SCEPTICAL_RECONCILER,
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=candidate_id_for(
            ProposalKind.MAPPING,
            DEFAULT_CATALOGUE_ID,
            DEFAULT_CAPABILITY_ID,
        ),
    )
    with pytest.raises(SpecialistProposalError, match="role"):
        validate_proposal(sceptical_item, normal_context)

    sceptical_context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(baseline.candidate_id,),
        accepted_candidates=(baseline,),
    )
    normal_item = proposal(
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=candidate_id_for(
            ProposalKind.MAPPING,
            DEFAULT_CATALOGUE_ID,
            DEFAULT_CAPABILITY_ID,
        ),
    )
    with pytest.raises(SpecialistProposalError, match="role"):
        validate_proposal(normal_item, sceptical_context)


def test_guided_recommendations_require_factors_and_non_recommendations_strip_them() -> None:
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
    )
    missing_factors = recommendation(
        DEFAULT_CATALOGUE_ID,
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        recommendation_factors=None,
        candidate_id=candidate_id_for(
            ProposalKind.RECOMMENDATION,
            DEFAULT_CATALOGUE_ID,
            DEFAULT_CAPABILITY_ID,
        ),
    )
    with pytest.raises(SpecialistProposalError, match="RecommendationFactors"):
        validate_proposal(missing_factors, context)

    with pytest.raises(ValidationError, match="recommendation factors"):
        proposal(
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            candidate_id=candidate_id_for(
                ProposalKind.MAPPING,
                DEFAULT_CATALOGUE_ID,
                DEFAULT_CAPABILITY_ID,
            ),
            recommendation_factors=RecommendationFactors(
                reliability_risk=1,
                job_relevance=2,
                workflow_leverage=2,
                evidence_strength=2,
                adoption_effort=2,
            ),
        )


def test_sceptical_role_cannot_add_a_new_positive_claim() -> None:
    baseline = candidate_baseline()
    context = proposal_context(
        catalogue_ids=(DEFAULT_CATALOGUE_ID, "cap-new"),
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(baseline.candidate_id,),
        accepted_candidates=(baseline,),
    )
    item = recommendation(
        "cap-new",
        role=SpecialistRole.SCEPTICAL_RECONCILER,
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=candidate_id_for(
            ProposalKind.RECOMMENDATION,
            "cap-new",
            DEFAULT_CAPABILITY_ID,
        ),
    )

    with pytest.raises(SpecialistProposalError, match="accept or downgrade"):
        validate_proposal(item, context)


def test_sceptical_role_can_review_an_existing_candidate() -> None:
    baseline = candidate_baseline(catalogue_id="cap-one")
    context = proposal_context(
        catalogue_ids=("cap-one",),
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(baseline.candidate_id,),
        accepted_candidates=(baseline,),
    )
    item = recommendation(
        "cap-one",
        role=SpecialistRole.SCEPTICAL_RECONCILER,
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=baseline.candidate_id,
        recommendation_factors=baseline.recommendation_factors,
        evidence_ids=baseline.evidence_ids,
        observation_ids=baseline.observation_ids,
    )

    accepted = validate_proposal(item, context)
    assert accepted.candidate_id == baseline.candidate_id


def test_accepted_candidate_ids_are_canonical() -> None:
    baseline_z = candidate_baseline(catalogue_id="z")
    baseline_a = candidate_baseline(catalogue_id="a")
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(
            baseline_z.candidate_id,
            baseline_a.candidate_id,
        ),
        accepted_candidates=(baseline_z, baseline_a),
    )
    expected = tuple(sorted((baseline_z.candidate_id, baseline_a.candidate_id)))
    assert context.accepted_candidate_ids == expected
    assert tuple(item.candidate_id for item in context.accepted_candidates) == expected


def test_packet_binding_tampering_is_revalidated_on_copy_and_construct() -> None:
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
    )
    with pytest.raises(ValidationError, match="packet"):
        context.model_copy(update={"packet_role": None})
    with pytest.raises(ValidationError, match="packet"):
        ProposalContext.model_construct(
            **{
                **context.model_dump(),
                "packet_digest": None,
            }
        )

    item = recommendation(
        DEFAULT_CATALOGUE_ID,
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=candidate_id_for(
            ProposalKind.RECOMMENDATION,
            DEFAULT_CATALOGUE_ID,
            DEFAULT_CAPABILITY_ID,
        ),
    )
    with pytest.raises(ValidationError, match="packet"):
        item.model_copy(update={"packet_id": "packet:sha256:" + "0" * 64})


def test_candidate_id_for_is_a_stable_digest() -> None:
    first = candidate_id_for(ProposalKind.MAPPING, DEFAULT_CATALOGUE_ID, DEFAULT_CAPABILITY_ID)
    second = candidate_id_for("mapping", DEFAULT_CATALOGUE_ID, DEFAULT_CAPABILITY_ID)

    assert first == second
    assert first.startswith("candidate:sha256:")
    assert first != candidate_id_for(
        ProposalKind.RECOMMENDATION,
        DEFAULT_CATALOGUE_ID,
        DEFAULT_CAPABILITY_ID,
    )


def test_proposal_binding_and_candidate_fields_are_closed_on_all_model_routes() -> None:
    expected = candidate_id_for(ProposalKind.MAPPING, DEFAULT_CATALOGUE_ID, DEFAULT_CAPABILITY_ID)
    with pytest.raises(ValidationError, match="packet"):
        proposal(packet_id=PACKET_ID)
    with pytest.raises(ValidationError, match="packet"):
        proposal(packet_digest=PACKET_DIGEST)
    with pytest.raises(ValidationError, match="candidate"):
        proposal(candidate_id=expected)

    with pytest.raises(ValidationError, match="candidate"):
        proposal(packet_id=PACKET_ID, packet_digest=PACKET_DIGEST)

    valid = proposal(
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=expected,
    )
    with pytest.raises(ValidationError, match="packet"):
        valid.model_copy(update={"packet_digest": None})
    with pytest.raises(ValidationError, match="candidate"):
        SpecialistProposal.model_construct(
            **{
                **valid.model_dump(),
                "candidate_id": None,
            }
        )

    validated = validate_proposal(
        valid,
        proposal_context(
            analysis_mode="guided-analysis",
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
        ),
    )
    with pytest.raises(ValidationError, match="packet"):
        validated.model_copy(update={"packet_id": None})
    with pytest.raises(ValidationError, match="candidate"):
        ValidatedProposal.model_construct(
            **{
                **validated.model_dump(),
                "candidate_id": None,
            }
        )


def test_recommendation_factors_are_rejected_on_non_recommendation_models() -> None:
    factors = RecommendationFactors(
        reliability_risk=1,
        job_relevance=2,
        workflow_leverage=2,
        evidence_strength=2,
        adoption_effort=2,
    )
    with pytest.raises(ValidationError, match="recommendation factors"):
        proposal(recommendation_factors=factors)
    with pytest.raises(ValidationError, match="recommendation factors"):
        ValidatedProposal(
            kind=ProposalKind.MAPPING,
            catalogue_id=DEFAULT_CATALOGUE_ID,
            capability_id=DEFAULT_CAPABILITY_ID,
            disposition=Disposition.SHARED,
            recommendation_factors=factors,
            evidence_ids=(CURRENT_EVIDENCE,),
            reason="The local method matches the signed catalogue method.",
        )


def test_context_analysis_mode_closes_packet_and_candidate_bindings() -> None:
    assert proposal_context().analysis_mode == "inventory-only"
    with pytest.raises(ValidationError, match="inventory-only"):
        proposal_context(
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
        )
    with pytest.raises(ValidationError, match="candidate"):
        proposal_context(accepted_candidate_ids=("candidate-one",))
    with pytest.raises(ValidationError, match="guided"):
        proposal_context(analysis_mode="guided-analysis")

    with pytest.raises(ValidationError, match="candidate"):
        proposal_context(
            analysis_mode="guided-analysis",
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
            accepted_candidate_ids=("candidate-one",),
        )

    with pytest.raises(ValidationError, match="baseline"):
        proposal_context(
            analysis_mode="guided-analysis",
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
            accepted_candidate_ids=("candidate-z", "candidate-a"),
        )

    baseline_z = candidate_baseline(catalogue_id="z")
    baseline_a = candidate_baseline(catalogue_id="a")
    sceptical = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(baseline_z.candidate_id, baseline_a.candidate_id),
        accepted_candidates=(baseline_z, baseline_a),
    )
    expected = tuple(sorted((baseline_z.candidate_id, baseline_a.candidate_id)))
    assert sceptical.accepted_candidate_ids == expected
    assert tuple(item.candidate_id for item in sceptical.accepted_candidates) == expected
    with pytest.raises(ValidationError, match="baseline candidate IDs"):
        sceptical.model_copy(update={"accepted_candidate_ids": ()})
    with pytest.raises(ValidationError, match="baseline candidate IDs"):
        ProposalContext.model_construct(
            **{
                **sceptical.model_dump(),
                "accepted_candidate_ids": (),
            }
        )


def test_unbound_sceptical_proposals_are_refused() -> None:
    with pytest.raises(SpecialistProposalError, match="unbound sceptical"):
        validate_proposal(
            proposal(role=SpecialistRole.SCEPTICAL_RECONCILER),
            proposal_context(),
        )


def test_bound_normal_proposals_use_the_computed_candidate_id() -> None:
    candidate_id = candidate_id_for(
        ProposalKind.MAPPING,
        DEFAULT_CATALOGUE_ID,
        DEFAULT_CAPABILITY_ID,
    )
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
    )
    accepted = validate_proposal(
        proposal(
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            candidate_id=candidate_id,
        ),
        context,
    )
    assert accepted.candidate_id == candidate_id


def test_sceptical_candidate_substitution_is_rejected() -> None:
    candidate_id = candidate_id_for(
        ProposalKind.RECOMMENDATION,
        DEFAULT_CATALOGUE_ID,
        DEFAULT_CAPABILITY_ID,
    )
    with pytest.raises(ValidationError, match="candidate"):
        recommendation(
            "other-capability",
            role=SpecialistRole.SCEPTICAL_RECONCILER,
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            candidate_id=candidate_id,
        )


def test_packet_id_must_equal_packet_digest_on_every_model_route() -> None:
    candidate_id = candidate_id_for(
        ProposalKind.MAPPING,
        DEFAULT_CATALOGUE_ID,
        DEFAULT_CAPABILITY_ID,
    )
    wrong_packet_id = "packet:sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="packet_id"):
        proposal(
            packet_id=wrong_packet_id,
            packet_digest=PACKET_DIGEST,
            candidate_id=candidate_id,
        )

    valid = proposal(
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=candidate_id,
    )
    with pytest.raises(ValidationError, match="packet_id"):
        valid.model_copy(update={"packet_id": wrong_packet_id})
    with pytest.raises(ValidationError, match="packet_id"):
        SpecialistProposal.model_construct(
            **{
                **valid.model_dump(),
                "packet_id": wrong_packet_id,
            }
        )

    with pytest.raises(ValidationError, match="packet_id"):
        proposal_context(
            analysis_mode="guided-analysis",
            packet_id=wrong_packet_id,
            packet_digest=PACKET_DIGEST,
            packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
        )
    valid_context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
    )
    with pytest.raises(ValidationError, match="packet_id"):
        valid_context.model_copy(update={"packet_id": wrong_packet_id})
    with pytest.raises(ValidationError, match="packet_id"):
        ProposalContext.model_construct(
            **{
                **valid_context.model_dump(),
                "packet_id": wrong_packet_id,
            }
        )

    validated = validate_proposal(valid, valid_context)
    with pytest.raises(ValidationError, match="packet_id"):
        validated.model_copy(update={"packet_id": wrong_packet_id})
    with pytest.raises(ValidationError, match="packet_id"):
        ValidatedProposal.model_construct(
            **{
                **validated.model_dump(),
                "packet_id": wrong_packet_id,
            }
        )


def test_candidate_baseline_is_deterministic_and_factor_closed() -> None:
    baseline = candidate_baseline(
        kind=ProposalKind.MAPPING,
        original_disposition=Disposition.STRONG_HERE,
    )
    assert baseline.candidate_id == candidate_id_for(
        ProposalKind.MAPPING,
        DEFAULT_CATALOGUE_ID,
        DEFAULT_CAPABILITY_ID,
    )
    with pytest.raises(ValidationError, match="candidate_id"):
        CandidateBaseline(
            candidate_id="candidate:sha256:" + "0" * 64,
            kind=baseline.kind,
            catalogue_id=baseline.catalogue_id,
            capability_id=baseline.capability_id,
            original_disposition=baseline.original_disposition,
            evidence_ids=baseline.evidence_ids,
            observation_ids=baseline.observation_ids,
        )
    with pytest.raises(ValidationError, match="candidate_id"):
        baseline.model_copy(update={"candidate_id": "candidate:sha256:" + "0" * 64})
    with pytest.raises(ValidationError, match="candidate_id"):
        CandidateBaseline.model_construct(
            **{
                **baseline.model_dump(),
                "candidate_id": "candidate:sha256:" + "0" * 64,
            }
        )
    with pytest.raises(ValidationError, match="recommendation factors"):
        CandidateBaseline(
            candidate_id=baseline.candidate_id,
            kind=baseline.kind,
            catalogue_id=baseline.catalogue_id,
            capability_id=baseline.capability_id,
            original_disposition=baseline.original_disposition,
            recommendation_factors=RecommendationFactors(
                reliability_risk=1,
                job_relevance=2,
                workflow_leverage=2,
                evidence_strength=2,
                adoption_effort=2,
            ),
            evidence_ids=baseline.evidence_ids,
            observation_ids=baseline.observation_ids,
        )
    with pytest.raises(ValidationError, match="recommendation factors"):
        CandidateBaseline(
            candidate_id=candidate_id_for(
                ProposalKind.RECOMMENDATION,
                DEFAULT_CATALOGUE_ID,
                DEFAULT_CAPABILITY_ID,
            ),
            kind=ProposalKind.RECOMMENDATION,
            catalogue_id=DEFAULT_CATALOGUE_ID,
            capability_id=DEFAULT_CAPABILITY_ID,
            original_disposition=Disposition.WORTH_BORROWING,
            evidence_ids=baseline.evidence_ids,
            observation_ids=baseline.observation_ids,
        )


def test_guided_sceptical_context_rejects_candidate_ids_without_baselines() -> None:
    candidate_id = candidate_id_for(
        ProposalKind.RECOMMENDATION,
        DEFAULT_CATALOGUE_ID,
        DEFAULT_CAPABILITY_ID,
    )
    with pytest.raises(ValidationError, match="baseline"):
        proposal_context(
            analysis_mode="guided-analysis",
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
            accepted_candidate_ids=(candidate_id,),
        )

    baseline = candidate_baseline()
    with pytest.raises(ValidationError, match="baseline"):
        proposal_context(
            analysis_mode="guided-analysis",
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
            accepted_candidate_ids=(),
            accepted_candidates=(baseline,),
        )
    with pytest.raises(ValidationError, match="candidate IDs"):
        proposal_context(
            analysis_mode="guided-analysis",
            packet_id=PACKET_ID,
            packet_digest=PACKET_DIGEST,
            packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
            accepted_candidate_ids=("candidate:sha256:" + "0" * 64,),
            accepted_candidates=(baseline,),
        )


def test_sceptical_accept_and_downgrade_are_bound_to_the_baseline() -> None:
    baseline = candidate_baseline(
        evidence_ids=(CURRENT_EVIDENCE,),
        observation_ids=("observation:baseline",),
    )
    context = proposal_context(
        evidence_ids=(CURRENT_EVIDENCE, "current:other"),
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(baseline.candidate_id,),
        accepted_candidates=(baseline,),
    ).model_copy(update={"observation_ids": ("observation:baseline", "observation:other")})
    unchanged = recommendation(
        DEFAULT_CATALOGUE_ID,
        role=SpecialistRole.SCEPTICAL_RECONCILER,
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=baseline.candidate_id,
        evidence_ids=baseline.evidence_ids,
        observation_ids=baseline.observation_ids,
        recommendation_factors=baseline.recommendation_factors,
    )
    accepted = validate_proposal(unchanged, context)
    assert accepted.evidence_ids == baseline.evidence_ids
    assert accepted.observation_ids == baseline.observation_ids

    with pytest.raises(SpecialistProposalError, match="baseline evidence"):
        validate_proposal(
            unchanged.model_copy(update={"evidence_ids": ("current:other",)}),
            context,
        )

    downgraded = unchanged.model_copy(
        update={
            "disposition": Disposition.FRAGILE_OR_CONTRADICTORY,
            "evidence_ids": ("current:other",),
            "observation_ids": ("observation:other",),
        }
    )
    downgraded_result = validate_proposal(downgraded, context)
    assert downgraded_result.disposition is Disposition.FRAGILE_OR_CONTRADICTORY
    assert downgraded_result.evidence_ids == ("current:other",)
    assert downgraded_result.observation_ids == ("observation:other",)


def test_sceptical_cannot_substitute_strong_here_or_inflate_factors() -> None:
    strong_baseline = candidate_baseline(
        kind=ProposalKind.MAPPING,
        original_disposition=Disposition.STRONG_HERE,
    )
    recommendation_baseline = candidate_baseline(
        recommendation_factors=RecommendationFactors(
            reliability_risk=1,
            job_relevance=1,
            workflow_leverage=1,
            evidence_strength=1,
            adoption_effort=3,
        )
    )
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(strong_baseline.candidate_id, recommendation_baseline.candidate_id),
        accepted_candidates=(strong_baseline, recommendation_baseline),
    )
    with pytest.raises(SpecialistProposalError, match="disposition"):
        validate_proposal(
            proposal(
                role=SpecialistRole.SCEPTICAL_RECONCILER,
                packet_id=PACKET_ID,
                packet_digest=PACKET_DIGEST,
                candidate_id=strong_baseline.candidate_id,
                disposition=Disposition.SHARED,
            ),
            context,
        )

    inflated = recommendation(
        DEFAULT_CATALOGUE_ID,
        role=SpecialistRole.SCEPTICAL_RECONCILER,
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=recommendation_baseline.candidate_id,
        recommendation_factors=RecommendationFactors(
            reliability_risk=3,
            job_relevance=3,
            workflow_leverage=3,
            evidence_strength=3,
            adoption_effort=1,
        ),
    )
    with pytest.raises(SpecialistProposalError, match="factors"):
        validate_proposal(inflated, context)


def test_non_recommendation_downgrade_may_drop_baseline_factors() -> None:
    factors = RecommendationFactors(
        reliability_risk=1,
        job_relevance=2,
        workflow_leverage=2,
        evidence_strength=2,
        adoption_effort=2,
    )
    baseline = candidate_baseline(
        kind=ProposalKind.RELEASE_DISTANCE,
        original_disposition=Disposition.WORTH_BORROWING,
        recommendation_factors=factors,
    )
    context = proposal_context(
        analysis_mode="guided-analysis",
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        packet_role=SpecialistRole.SCEPTICAL_RECONCILER,
        accepted_candidate_ids=(baseline.candidate_id,),
        accepted_candidates=(baseline,),
        family_contract_present=True,
    )
    accepted = proposal(
        role=SpecialistRole.SCEPTICAL_RECONCILER,
        kind=ProposalKind.RELEASE_DISTANCE,
        disposition=Disposition.WORTH_BORROWING,
        packet_id=PACKET_ID,
        packet_digest=PACKET_DIGEST,
        candidate_id=baseline.candidate_id,
        recommendation_factors=factors,
    )
    assert validate_proposal(accepted, context).recommendation_factors == factors

    downgraded = accepted.model_copy(
        update={
            "disposition": Disposition.FRAGILE_OR_CONTRADICTORY,
            "recommendation_factors": None,
        }
    )
    result = validate_proposal(downgraded, context)
    assert result.disposition is Disposition.FRAGILE_OR_CONTRADICTORY
    assert result.recommendation_factors is None

    inflated = accepted.model_copy(
        update={
            "recommendation_factors": RecommendationFactors(
                reliability_risk=3,
                job_relevance=3,
                workflow_leverage=3,
                evidence_strength=3,
                adoption_effort=1,
            )
        }
    )
    with pytest.raises(SpecialistProposalError, match="factors"):
        validate_proposal(inflated, context)
