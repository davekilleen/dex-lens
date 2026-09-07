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

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    HumanCapability,
    LocalObservationDisposition,
    McpToolInventory,
)
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    EvidenceFingerprint,
    HealthState,
    Observation,
    ObservationKind,
    OperationalState,
    RuntimeState,
    observation_id_for,
)
from capability_exchange.diagnosis.report import (
    canonical_ledger_appendix,
    canonical_ledger_digest,
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
                configuration_state=ConfigurationState.IMPLEMENTED,
                runtime_state=RuntimeState.RECENTLY_RUN,
                health_state=HealthState.BROKEN,
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
    assert ledger.local_entries[0].configuration_state is ConfigurationState.IMPLEMENTED
    assert ledger.local_entries[0].runtime_state is RuntimeState.RECENTLY_RUN
    assert ledger.local_entries[0].health_state is HealthState.BROKEN
    assert "operational_state" not in ledger.local_entries[0].model_dump(mode="json")


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


def test_local_ledger_requires_all_three_exact_observation_axes() -> None:
    catalogue, entries = _catalogue_and_entries()
    fingerprint = _fingerprint()
    observation = fingerprint.observations[0]
    local = LocalObservationDisposition(
        observation_id=observation_id_for(observation),
        kind=observation.kind,
        identity=observation.identity,
        configuration_state=observation.configuration_state,
        runtime_state=observation.runtime_state,
        health_state=HealthState.HEALTHY,
        reason="Not assessed.",
    )

    with pytest.raises(ValidationError, match="observation facts"):
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


def test_appendix_groups_every_exact_mcp_tool_and_digest_binds_it() -> None:
    from tests.catalogue.test_significant_contract import _catalogue

    catalogue = CatalogueV2.model_validate(_catalogue())
    entries = tuple(
        CatalogueDisposition(
            catalogue_id=item.capability_id,
            disposition=Disposition.NOT_ASSESSED,
            capability_id=item.capability_id,
            reason="Not assessed.",
        )
        for item in catalogue.capabilities
    )
    ledger = ComparisonLedger.for_catalogue(
        catalogue,
        catalogue_version=7,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=_capabilities(catalogue),
        entries=entries,
    )

    assert ledger.mcp_tools_by_server == (
        McpToolInventory(
            server_id="dex-work-mcp",
            server_name="dex-work",
            tools=("list_tasks", "add_note"),
        ),
    )
    appendix = canonical_ledger_appendix(ledger)
    assert '"server_name":"dex-work"' in appendix
    assert '"tools":["list_tasks","add_note"]' in appendix
    assert ledger_appendix_errors(
        appendix.replace('"add_note"', '"forged_tool"'), ledger
    )

    changed = ledger.model_copy(
        update={
            "mcp_tools_by_server": (
                McpToolInventory(
                    server_id="dex-work-mcp",
                    server_name="dex-work",
                    tools=("list_tasks", "invented_extra"),
                ),
            )
        }
    )
    assert canonical_ledger_digest(changed) != canonical_ledger_digest(ledger)

    with pytest.raises(ValidationError, match="exact verified catalogue inventory"):
        ComparisonLedger.for_catalogue(
            catalogue,
            catalogue_version=7,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=_capabilities(catalogue),
            entries=entries,
            mcp_tools_by_server=changed.mcp_tools_by_server,
        )


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
