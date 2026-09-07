"""Engine-derived authorship origin: stock Dex, harness-shipped, authored.

The first real run praised stock Dex skills back to their own vendor as the
person's standout strengths.  SKILL.md rule 5 ("would this file exist in a
fresh Dex install?") existed as prose only; these tests pin the engine
enforcement: a deterministic, capture-fact-plus-signed-identity origin for
every observation, a typed refusal for a strength or reciprocal proposal
citing nothing the person authored, and an engine-computed unique-to-you
list.  Every fixture is invented.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.diagnosis.test_significant_family_assessment import _catalogue

from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    ObservationOrigin,
    OperationalState,
    derive_observation_origin,
    observation_id_for,
)
from capability_exchange.diagnosis.origin import (
    derive_observation_origins,
    signed_identity_keys_for,
    unique_to_you_observation_ids,
)
from capability_exchange.diagnosis.specialists import (
    ProposalContext,
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    validate_proposal,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)

RUN_ID = "run:" + "a" * 16
FINGERPRINT_DIGEST = "sha256:" + "b" * 64
CATALOGUE_DIGEST = "sha256:" + "c" * 64


def _observation(
    kind: ObservationKind,
    identity: str,
    *,
    source_class: str = "vault-authored",
) -> Observation:
    return Observation(
        kind=kind,
        identity=identity,
        label=identity,
        operational_state=OperationalState.IMPLEMENTED,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference=f"fixture:{kind.value}:{identity}",
        ),
        provenance={
            "source_id": "scope:invented-vault",
            "source_class": source_class,
            "scope_reference": "scope:sha256:" + "a" * 64,
            "relative_reference": f"synthetic/{identity}.md",
        },
    )


def _fingerprint(*observations: Observation) -> EvidenceFingerprint:
    return EvidenceFingerprint(
        adapter_id="synthetic-read-only",
        collected_at=NOW,
        observations=observations,
    )


def _signed_keys() -> frozenset[str]:
    return signed_identity_keys_for(_catalogue())


# --- derivation, one test per origin class, invented fixtures ---------------


def test_exact_signed_capability_identity_is_dex_stock() -> None:
    keys = _signed_keys()
    assert (
        derive_observation_origin(
            _observation(ObservationKind.SKILL, "workflow-skill"),
            signed_identity_keys=keys,
        )
        is ObservationOrigin.DEX_STOCK
    )
    # A dormant signed member is still Dex's own identity.
    assert (
        derive_observation_origin(
            _observation(ObservationKind.SKILL, "dormant-helper"),
            signed_identity_keys=keys,
        )
        is ObservationOrigin.DEX_STOCK
    )


def test_signed_alias_server_name_tool_and_release_are_dex_stock() -> None:
    keys = _signed_keys()
    cases = (
        _observation(ObservationKind.SKILL, "workflow-alias"),
        _observation(ObservationKind.MCP_SERVER, "dex-work-mcp"),
        _observation(ObservationKind.MCP_SERVER, "work-mcp"),
        _observation(ObservationKind.MCP_TOOL, "dex-work-mcp.create_task"),
        _observation(ObservationKind.AUTOMATION, "dex-nightly-check"),
        _observation(ObservationKind.RELEASE, "dex-core"),
    )
    for observation in cases:
        assert (
            derive_observation_origin(observation, signed_identity_keys=keys)
            is ObservationOrigin.DEX_STOCK
        ), observation.identity


def test_kind_mismatch_never_grounds_a_stock_claim() -> None:
    keys = _signed_keys()
    # An automation that merely reuses a signed skill's name is not that
    # signed skill; the reviewed matcher refuses the equivalence and so does
    # the origin axis.
    assert (
        derive_observation_origin(
            _observation(ObservationKind.AUTOMATION, "workflow-skill"),
            signed_identity_keys=keys,
        )
        is ObservationOrigin.AUTHORED
    )
    # System engines have no local detector kind, so a skill named after one
    # stays the person's own work.
    assert (
        derive_observation_origin(
            _observation(ObservationKind.SKILL, "parked-engine"),
            signed_identity_keys=keys,
        )
        is ObservationOrigin.AUTHORED
    )


def test_assistant_vendored_items_are_harness_shipped() -> None:
    keys = _signed_keys()
    assert (
        derive_observation_origin(
            _observation(ObservationKind.SKILL, "anthropic-pdf"),
            signed_identity_keys=keys,
        )
        is ObservationOrigin.HARNESS_SHIPPED
    )
    for source_class in ("harness-bundled", "plugin-or-vendor"):
        assert (
            derive_observation_origin(
                _observation(ObservationKind.SKILL, "vendored-helper", source_class=source_class),
                signed_identity_keys=keys,
            )
            is ObservationOrigin.HARNESS_SHIPPED
        )


def test_harness_shipped_takes_precedence_over_a_signed_identity_match() -> None:
    # A plugin-vendored copy of a signed Dex skill is assistant-shipped:
    # neither the person's strength nor a stock-install fact about their vault.
    assert (
        derive_observation_origin(
            _observation(
                ObservationKind.SKILL,
                "workflow-skill",
                source_class="plugin-or-vendor",
            ),
            signed_identity_keys=_signed_keys(),
        )
        is ObservationOrigin.HARNESS_SHIPPED
    )


def test_everything_else_is_authored() -> None:
    assert (
        derive_observation_origin(
            _observation(ObservationKind.SKILL, "weekly-ledger"),
            signed_identity_keys=_signed_keys(),
        )
        is ObservationOrigin.AUTHORED
    )


def test_origin_map_is_deterministic_and_total() -> None:
    fingerprint = _fingerprint(
        _observation(ObservationKind.SKILL, "weekly-ledger"),
        _observation(ObservationKind.SKILL, "workflow-skill"),
        _observation(ObservationKind.SKILL, "anthropic-pdf"),
    )
    keys = _signed_keys()
    first = derive_observation_origins(fingerprint, signed_identity_keys=keys)
    second = derive_observation_origins(fingerprint, signed_identity_keys=keys)
    assert first == second
    assert set(first) == {
        observation_id_for(item) for item in fingerprint.observations
    }
    assert sorted(first.values(), key=lambda item: item.value) == [
        ObservationOrigin.AUTHORED,
        ObservationOrigin.DEX_STOCK,
        ObservationOrigin.HARNESS_SHIPPED,
    ]


# --- the engine-owned unique-to-you candidate list ---------------------------


def test_unique_to_you_carries_exactly_the_authored_catalogue_unmatched_items() -> None:
    authored_skill = _observation(ObservationKind.SKILL, "weekly-ledger")
    authored_automation = _observation(ObservationKind.AUTOMATION, "morning-pulse")
    stock = _observation(ObservationKind.SKILL, "workflow-skill")
    harness = _observation(ObservationKind.SKILL, "anthropic-pdf")
    fingerprint = _fingerprint(authored_skill, authored_automation, stock, harness)

    unique = unique_to_you_observation_ids(
        fingerprint, signed_identity_keys=_signed_keys()
    )

    assert unique == tuple(
        sorted(
            (
                observation_id_for(authored_skill),
                observation_id_for(authored_automation),
            )
        )
    )


def test_harness_shipped_items_are_not_unique_to_you() -> None:
    fingerprint = _fingerprint(_observation(ObservationKind.SKILL, "anthropic-pdf"))
    assert (
        unique_to_you_observation_ids(fingerprint, signed_identity_keys=_signed_keys())
        == ()
    )


# --- enforcement at proposal validation --------------------------------------

_AUTHORED_OBSERVATION = "observation:sha256:" + "1" * 64
_STOCK_OBSERVATION = "observation:sha256:" + "2" * 64
_AUTHORED_EVIDENCE = "evidence:sha256:" + "3" * 64
_STOCK_EVIDENCE = "evidence:sha256:" + "4" * 64


def _context(*, classified: bool = True) -> ProposalContext:
    values: dict[str, object] = {
        "run_id": RUN_ID,
        "fingerprint_digest": FINGERPRINT_DIGEST,
        "catalogue_digest": CATALOGUE_DIGEST,
        "evidence_ids": (_AUTHORED_EVIDENCE, _STOCK_EVIDENCE),
        "catalogue_ids": ("workflow-skill",),
        "capability_ids": ("workflow-skill",),
        "observation_ids": (_AUTHORED_OBSERVATION, _STOCK_OBSERVATION),
    }
    if classified:
        values["authored_observation_ids"] = (_AUTHORED_OBSERVATION,)
        values["authored_evidence_ids"] = (_AUTHORED_EVIDENCE,)
    return ProposalContext.model_validate(values)


def _strength(
    *,
    kind: ProposalKind = ProposalKind.STRENGTH,
    observation_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...] = (_STOCK_EVIDENCE,),
) -> SpecialistProposal:
    return SpecialistProposal(
        role=SpecialistRole.STRENGTH_AND_RECIPROCAL,
        kind=kind,
        run_id=RUN_ID,
        fingerprint_digest=FINGERPRINT_DIGEST,
        catalogue_digest=CATALOGUE_DIGEST,
        catalogue_id="workflow-skill",
        capability_id="workflow-skill",
        disposition=(
            Disposition.STRONG_HERE
            if kind is ProposalKind.STRENGTH
            else Disposition.DEX_SHOULD_LEARN
        ),
        evidence_ids=evidence_ids,
        observation_ids=observation_ids,
        reason="An invented method claim used only to test authorship enforcement.",
    )


def test_strength_citing_only_non_authored_observations_is_refused() -> None:
    with pytest.raises(SpecialistProposalError, match="authored"):
        validate_proposal(
            _strength(observation_ids=(_STOCK_OBSERVATION,)),
            _context(),
        )


def test_reciprocal_citing_only_non_authored_observations_is_refused() -> None:
    with pytest.raises(SpecialistProposalError, match="authored"):
        validate_proposal(
            _strength(
                kind=ProposalKind.RECIPROCAL,
                observation_ids=(_STOCK_OBSERVATION,),
            ),
            _context(),
        )


def test_refusal_carries_no_inspected_system_content() -> None:
    with pytest.raises(SpecialistProposalError) as caught:
        validate_proposal(
            _strength(observation_ids=(_STOCK_OBSERVATION,)),
            _context(),
        )
    message = str(caught.value)
    assert "workflow-skill" not in message
    assert "sha256" not in message


def test_strength_citing_one_authored_observation_stands() -> None:
    validated = validate_proposal(
        _strength(observation_ids=(_AUTHORED_OBSERVATION, _STOCK_OBSERVATION)),
        _context(),
    )
    assert validated.disposition is Disposition.STRONG_HERE


def test_strength_citing_an_authored_evidence_token_stands() -> None:
    validated = validate_proposal(
        _strength(observation_ids=(), evidence_ids=(_AUTHORED_EVIDENCE,)),
        _context(),
    )
    assert validated.disposition is Disposition.STRONG_HERE


def test_non_strength_kinds_are_not_authorship_bound() -> None:
    proposal = SpecialistProposal(
        role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
        kind=ProposalKind.MAPPING,
        run_id=RUN_ID,
        fingerprint_digest=FINGERPRINT_DIGEST,
        catalogue_digest=CATALOGUE_DIGEST,
        catalogue_id="workflow-skill",
        capability_id="workflow-skill",
        disposition=Disposition.NOT_RELEVANT,
        evidence_ids=(_STOCK_EVIDENCE,),
        observation_ids=(_STOCK_OBSERVATION,),
        reason="A mapping claim about a stock item stays lawful.",
    )
    assert validate_proposal(proposal, _context()).disposition is Disposition.NOT_RELEVANT


def test_unclassified_context_keeps_legacy_validation_behaviour() -> None:
    # A context that never derived authorship (direct library use) does not
    # enforce; every engine-built context carries the derivation.
    validated = validate_proposal(
        _strength(observation_ids=(_STOCK_OBSERVATION,)),
        _context(classified=False),
    )
    assert validated.disposition is Disposition.STRONG_HERE
