"""Focused red tests for the significant-capability coverage slice.

These tests intentionally describe the closed, bidirectional contract before
the engine implementation is changed.  They stay synthetic and use only
invented catalogue/evidence identities.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    HumanCapability,
    LocalObservationDisposition,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    observation_id_for,
)
from capability_exchange.diagnosis.report import (
    canonical_ledger_appendix,
    ledger_appendix_errors,
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

NOW = datetime(2026, 9, 1, tzinfo=UTC)
CATALOGUE_SHA = "a" * 64
RUN_ID = "run:" + "a" * 16
FINGERPRINT_SHA = "sha256:" + "b" * 64
CATALOGUE_DIGEST = "sha256:" + "c" * 64


def _fingerprint() -> EvidenceFingerprint:
    return EvidenceFingerprint(
        adapter_id="synthetic",
        collected_at=NOW,
        observations=(
            Observation(
                kind=ObservationKind.SKILL,
                identity="weekly-plan",
                label="Weekly plan",
                operational_state=OperationalState.IMPLEMENTED,
                evidence=EvidenceItem(
                    state=EvidenceState.OBSERVED,
                    captured_at=NOW,
                    reference="file-token:weekly-plan.md",
                ),
                provenance={
                    "source_id": "scope:primary",
                    "source_class": "vault-authored",
                    "scope_reference": "scope:sha256:" + "d" * 64,
                    "relative_reference": "skills/weekly-plan/SKILL.md",
                },
            ),
        ),
    )


def _catalogue_and_entries() -> tuple[object, tuple[CatalogueDisposition, ...]]:
    from tests.catalogue.test_bridge import _catalogue

    catalogue = _catalogue()
    entries = tuple(
        CatalogueDisposition(
            catalogue_id=item.capability_id,
            disposition=Disposition.NOT_ASSESSED,
            capability_id=item.capability_id,
            reason="No specialist proposal cleared the evidence bar.",
        )
        for item in catalogue.capabilities
    )
    return catalogue, entries


def _capabilities(catalogue: object) -> tuple[HumanCapability, ...]:
    return tuple(
        HumanCapability(
            capability_id=item.capability_id,
            title=item.title,
            job_ids=tuple(item.jobs),
            catalogue_ids=(item.capability_id,),
            person_observation_ids=(),
        )
        for item in catalogue.capabilities
    )


def test_production_ledger_seeds_every_local_observation_not_assessed() -> None:
    catalogue, entries = _catalogue_and_entries()
    ledger = ComparisonLedger.for_catalogue_and_fingerprint(
        catalogue,
        fingerprint=_fingerprint(),
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=_capabilities(catalogue),
        entries=entries,
    )

    assert len(ledger.local_entries) == 1
    assert ledger.local_entries[0].disposition is Disposition.NOT_ASSESSED
    assert ledger.local_entries[0].observation_id == observation_id_for(
        _fingerprint().observations[0]
    )


def test_local_ledger_requires_exact_observation_identity_set() -> None:
    catalogue, entries = _catalogue_and_entries()
    fingerprint = _fingerprint()
    local = LocalObservationDisposition(
        observation_id="observation:sha256:" + "e" * 64,
        kind=ObservationKind.SKILL,
        identity="foreign",
        operational_state=OperationalState.IMPLEMENTED,
        disposition=Disposition.NOT_ASSESSED,
        mapped_catalogue_ids=(),
        mapped_capability_ids=(),
        reason="Not assessed.",
    )

    with pytest.raises(ValidationError, match="observation identity set"):
        ComparisonLedger.for_catalogue_and_fingerprint(
            catalogue,
            fingerprint=fingerprint,
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=_capabilities(catalogue),
            entries=entries,
            local_entries=(local,),
        )


def test_specialist_proposal_must_cite_known_observation_ids() -> None:
    proposal = SpecialistProposal(
        role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
        kind=ProposalKind.MAPPING,
        run_id=RUN_ID,
        fingerprint_digest=FINGERPRINT_SHA,
        catalogue_digest=CATALOGUE_DIGEST,
        catalogue_id="daily-planning",
        capability_id="planning",
        disposition=Disposition.NOT_ASSESSED,
        observation_ids=("skill:unknown:scope:primary",),
        evidence_ids=("current:evidence",),
        reason="The local observation was considered.",
    )
    context = ProposalContext(
        run_id=RUN_ID,
        fingerprint_digest=FINGERPRINT_SHA,
        catalogue_digest=CATALOGUE_DIGEST,
        observation_ids=("skill:weekly-plan:scope:primary",),
        evidence_ids=("current:evidence",),
        catalogue_ids=("daily-planning",),
        capability_ids=("planning",),
    )

    with pytest.raises(SpecialistProposalError, match="observation"):
        validate_proposal(proposal, context)


def test_appendix_is_complete_and_rejects_reordered_rows() -> None:
    catalogue, entries = _catalogue_and_entries()
    ledger = ComparisonLedger.for_catalogue_and_fingerprint(
        catalogue,
        fingerprint=_fingerprint(),
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=_capabilities(catalogue),
        entries=entries,
    )
    appendix = canonical_ledger_appendix(ledger)
    assert appendix
    assert observation_id_for(_fingerprint().observations[0]) in appendix
    assert ledger_appendix_errors(appendix, ledger) == ()
    rows = appendix.splitlines()
    reordered = "\n".join([rows[0], *reversed(rows[1:])]) + "\n"
    assert ledger_appendix_errors(reordered, ledger)


def test_result_storage_contains_structured_ledger_and_appendix() -> None:
    catalogue, entries = _catalogue_and_entries()
    ledger = ComparisonLedger.for_catalogue_and_fingerprint(
        catalogue,
        fingerprint=_fingerprint(),
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=_capabilities(catalogue),
        entries=entries,
    )
    assert json.dumps(ledger.model_dump(mode="json"))


def test_integration_provider_kind_is_closed() -> None:
    assert ObservationKind.INTEGRATION_PROVIDER.value == "integration-provider"
