"""Process-default diagnosis engine ports. CLI and MCP inject these."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.adapters.claude_code.discovery import discover_fingerprint
from capability_exchange.adapters.claude_code.live_state import collect_live_states
from capability_exchange.adapters.claude_code.snapshot import take_snapshot
from capability_exchange.catalogue.subscription import (
    default_lens_app_storage,
    diagnosis_run_storage,
)
from capability_exchange.catalogue.v2 import (
    CatalogueVerificationError,
    VerifiedCatalogueStore,
    capability_availability_of,
    default_keyring,
)
from capability_exchange.concierge.collection import ScopeSnapshot, default_source_descriptors
from capability_exchange.concierge.consent import LocalScopeConsentAuthority
from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    FamilyLedgerEntry,
    HumanCapability,
    LocalObservationDisposition,
    family_entries_from_assessments,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    observation_id_for,
)
from capability_exchange.diagnosis.orchestrator import (
    DeterministicDiagnosisEngine,
    VerifiedCatalogueSlice,
)
from capability_exchange.diagnosis.run import ApprovedScopeReceipt, DiagnosisStateError
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.significant_families import assess_significant_families
from capability_exchange.diagnosis.specialists import (
    DISAGREEMENT_REASON,
    ProposalKind,
    SpecialistProposalError,
    ValidatedProposal,
)
from capability_exchange.reports.store import LensReportStore, default_report_directory

__all__ = [
    "CachedCatalogueLoader",
    "ConsentBoundCollector",
    "UnknownUntilProposedComparer",
    "build_default_engine",
    "dispositions_from_proposals",
    "local_dispositions_from_proposals",
]

_NO_PROPOSAL = "No specialist proposal cleared the evidence bar."


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _reciprocal_answer(
    fingerprint: EvidenceFingerprint,
    family_entries: tuple[FamilyLedgerEntry, ...],
) -> str:
    matched_observation_ids = {
        observation_id
        for family in family_entries
        for observation_id in family.matched_observation_ids
    }
    matched_components = sum(len(family.matched_components) for family in family_entries)
    matched_families = sum(bool(family.matched_components) for family in family_entries)
    if matched_observation_ids:
        kind_count = len(
            {
                observation.kind
                for observation in fingerprint.observations
                if observation_id_for(observation) in matched_observation_ids
            }
        )
        building_count = len(matched_observation_ids)
        strongest = sorted(
            (family for family in family_entries if family.matched_components),
            key=lambda family: (-len(family.matched_components), family.family_id),
        )[:2]
        named_strengths = " and ".join(f"‘{family.title}’" for family in strongest)
        return (
            f"Your approved snapshot demonstrates {building_count} evidence-backed local "
            f"{_plural(building_count, 'building block')} across {kind_count} "
            f"{_plural(kind_count, 'capability type')}, with {matched_components} exact "
            f"signed {_plural(matched_components, 'component overlap')} across "
            f"{matched_families} Dex outcome {_plural(matched_families, 'family', 'families')}. "
            f"The strongest evidence-bound patterns are around {named_strengths}. "
            "Dex should learn how you assemble these building blocks; this configuration "
            "evidence does not prove method equivalence, runtime quality, or outcomes."
        )
    observation_count = len(fingerprint.observations)
    kind_count = len({observation.kind for observation in fingerprint.observations})
    return (
        f"Your approved snapshot contains {observation_count} evidence-bound local "
        f"{_plural(observation_count, 'observation')} across {kind_count} observed "
        f"{_plural(kind_count, 'capability type')}. What Dex should learn remains Unknown "
        "because no exact significant-family overlap cleared the evidence bar."
    )


def _verified_store(store: VerifiedCatalogueStore | None) -> VerifiedCatalogueStore:
    if store is not None:
        return store
    return VerifiedCatalogueStore(default_lens_app_storage())


def _signed_digest(envelope: object) -> str:
    signed = getattr(envelope, "_signed_json", None) or envelope.model_dump_json()
    return hashlib.sha256(signed.encode("utf-8")).hexdigest()


def _load_verified(store: VerifiedCatalogueStore) -> object:
    try:
        return store.load_last_verified(keyring=default_keyring())
    except CatalogueVerificationError as exc:
        raise DiagnosisStateError(
            "verify the Dex catalogue first with dex-lens catalogue"
        ) from exc


def dispositions_from_proposals(
    capability_ids: tuple[str, ...],
    proposals: tuple[ValidatedProposal, ...],
) -> tuple[CatalogueDisposition, ...]:
    """Apply reconciled proposals onto a complete not-assessed ledger."""

    by_id: dict[str, list[ValidatedProposal]] = defaultdict(list)
    for proposal in proposals:
        by_id[proposal.catalogue_id].append(proposal)
    return tuple(
        _entry_for(capability_id, by_id[capability_id]) for capability_id in capability_ids
    )


def _entry_for(capability_id: str, group: list[ValidatedProposal]) -> CatalogueDisposition:
    if not group:
        return CatalogueDisposition(
            catalogue_id=capability_id,
            disposition=Disposition.NOT_ASSESSED,
            capability_id=capability_id,
            reason=_NO_PROPOSAL,
        )
    disagreement = next((item for item in group if item.reason == DISAGREEMENT_REASON), None)
    chosen = disagreement or _agreed_or_unknown(capability_id, group)
    method_compared = (
        chosen.kind is ProposalKind.METHOD_COMPARISON or chosen.disposition is Disposition.SHARED
    )
    return CatalogueDisposition(
        catalogue_id=chosen.catalogue_id,
        disposition=chosen.disposition,
        capability_id=chosen.capability_id,
        evidence_references=chosen.evidence_ids,
        method_compared=method_compared,
        reason=chosen.reason,
    )


def _agreed_or_unknown(
    capability_id: str,
    group: list[ValidatedProposal],
) -> ValidatedProposal:
    ordered = sorted(group, key=lambda item: (item.kind.value, item.reason, item.capability_id))
    dispositions = {item.disposition for item in ordered}
    if len(dispositions) == 1:
        return ordered[0]
    evidence = tuple(sorted({token for item in ordered for token in item.evidence_ids}))[:8]
    return ValidatedProposal(
        kind=ordered[0].kind,
        catalogue_id=capability_id,
        capability_id=ordered[0].capability_id,
        disposition=Disposition.NOT_ASSESSED,
        evidence_ids=evidence or ordered[0].evidence_ids,
        reason=DISAGREEMENT_REASON,
        observation_ids=tuple(
            sorted({token for item in ordered for token in item.observation_ids})
        ),
    )


def local_dispositions_from_proposals(
    fingerprint: EvidenceFingerprint,
    proposals: tuple[ValidatedProposal, ...],
) -> tuple[LocalObservationDisposition, ...]:
    """Apply validated specialist mappings to every captured observation.

    Observations without a cited proposal remain visible and explicitly
    ``not-assessed``.  Their source evidence is retained as a bounded
    reference; no raw content or path is introduced here.
    """

    known_observation_ids = {
        observation_id_for(observation) for observation in fingerprint.observations
    }
    cited_observation_ids = {
        observation_id
        for proposal in proposals
        for observation_id in proposal.observation_ids
    }
    if not cited_observation_ids.issubset(known_observation_ids):
        raise SpecialistProposalError(
            "validated proposal observation identity is not present in the current fingerprint"
        )

    by_observation: dict[str, list[ValidatedProposal]] = defaultdict(list)
    for proposal in proposals:
        for observation_id in proposal.observation_ids:
            by_observation[observation_id].append(proposal)
    return tuple(
        _local_entry_for(observation, by_observation[observation_id_for(observation)])
        for observation in fingerprint.observations
    )


def _local_entry_for(
    observation: Observation,
    group: list[ValidatedProposal],
) -> LocalObservationDisposition:
    observation_id = observation_id_for(observation)
    if not group:
        return LocalObservationDisposition(
            observation_id=observation_id,
            kind=observation.kind,
            identity=observation.identity,
            configuration_state=observation.configuration_state,
            runtime_state=observation.runtime_state,
            health_state=observation.health_state,
            disposition=Disposition.NOT_ASSESSED,
            evidence_references=(observation.evidence.reference,),
            reason="No specialist proposal cited this observation.",
            limitation="No specialist proposal cited this observation.",
        )
    chosen = _agreed_or_unknown(group[0].catalogue_id, group)
    catalogue_ids = tuple(sorted({item.catalogue_id for item in group}))
    capability_ids = tuple(sorted({item.capability_id for item in group}))
    evidence = tuple(sorted({token for item in group for token in item.evidence_ids}))
    return LocalObservationDisposition(
        observation_id=observation_id,
        kind=observation.kind,
        identity=observation.identity,
        configuration_state=observation.configuration_state,
        runtime_state=observation.runtime_state,
        health_state=observation.health_state,
        disposition=chosen.disposition,
        mapped_catalogue_ids=catalogue_ids,
        mapped_capability_ids=capability_ids,
        evidence_references=evidence or (observation.evidence.reference,),
        reason=chosen.reason,
        limitation=(
            "Specialist proposals disagreed; this observation remains not-assessed."
            if chosen.disposition is Disposition.NOT_ASSESSED
            else "Assessment is limited to the cited local evidence."
        ),
    )


class ConsentBoundCollector:
    """Collect only after local /approve persisted the exact approved roots."""

    def __init__(self, run_store: DiagnosisRunStore) -> None:
        self._runs = run_store

    def collect(self, receipt: ApprovedScopeReceipt) -> EvidenceFingerprint:
        approval = self._runs.load_scope_approval(receipt.run_id)
        if approval is None:
            raise DiagnosisStateError(
                "approve the exact scope in this chat with dex-lens diagnosis approve"
            )
        if approval.receipt != receipt:
            raise DiagnosisStateError("approved scope receipt changed; start a new run")
        roots = tuple(Path(root) for root in approval.approved_roots)
        try:
            descriptors = default_source_descriptors(roots) if len(roots) > 1 else None
            snapshot = ScopeSnapshot.capture(roots, source_descriptors=descriptors)
        except ValueError as exc:
            raise DiagnosisStateError("approved root identity changed; start a new run") from exc
        live_refs = tuple(item.scope_reference for item in snapshot.source_descriptors)
        if live_refs != receipt.scope_references:
            raise DiagnosisStateError("approved root identity changed; start a new run")
        snapshot.revalidate(roots)
        contract = claude_code_contract(tuple(str(root) for root in roots))
        allowlist = CanonicalAllowlist(contract.read_scope, denied_paths=contract.denied_paths)
        inspection = take_snapshot(allowlist, source_descriptors=snapshot.source_descriptors)
        live_states = (
            collect_live_states(scope_receipt=receipt) if receipt.include_live_state else ()
        )
        return discover_fingerprint(
            inspection,
            collected_at=inspection.taken_at,
            live_states=live_states,
            scope_receipt=receipt,
        )


class CachedCatalogueLoader:
    """Load the last signature-verified catalogue. Do not fetch here."""

    def __init__(self, store: VerifiedCatalogueStore | None = None) -> None:
        self._store = _verified_store(store)

    def load(self, *, run_id: str, fingerprint_digest: str) -> VerifiedCatalogueSlice:
        del run_id, fingerprint_digest
        envelope = _load_verified(self._store)
        catalogue = envelope.catalogue
        unavailable = tuple(
            item.capability_id
            for item in catalogue.capabilities
            if capability_availability_of(item) != "active"
        )
        return VerifiedCatalogueSlice(
            version=envelope.metadata.catalog_version,
            sha256=_signed_digest(envelope),
            catalogue_ids=tuple(item.capability_id for item in catalogue.capabilities),
            capability_ids=tuple(item.capability_id for item in catalogue.capabilities),
            unavailable_ids=unavailable,
            family_contract_present=bool(catalogue.capability_families),
        )


class UnknownUntilProposedComparer:
    """Complete ledger: every catalogue identity starts as not-assessed."""

    def __init__(self, store: VerifiedCatalogueStore | None = None) -> None:
        self._store = _verified_store(store)

    def compare(
        self,
        *,
        fingerprint: EvidenceFingerprint,
        catalogue: VerifiedCatalogueSlice,
        jobs: tuple[object, ...],
        proposals: tuple[ValidatedProposal, ...],
    ) -> ComparisonLedger:
        del jobs
        envelope = _load_verified(self._store)
        digest = _signed_digest(envelope)
        if digest != catalogue.sha256:
            raise DiagnosisStateError("verified catalogue identity drifted; start a new run")
        observations_by_capability: dict[str, set[str]] = defaultdict(set)
        for proposal in proposals:
            for observation_id in proposal.observation_ids:
                observations_by_capability[proposal.capability_id].add(observation_id)
        capabilities = tuple(
            HumanCapability(
                capability_id=item.capability_id,
                title=item.title,
                job_ids=tuple(item.jobs),
                catalogue_ids=(item.capability_id,),
                person_observation_ids=tuple(
                    sorted(observations_by_capability.get(item.capability_id, ()))
                ),
            )
            for item in envelope.catalogue.capabilities
        )
        entries = dispositions_from_proposals(
            tuple(item.capability_id for item in envelope.catalogue.capabilities),
            proposals,
        )
        family_entries = family_entries_from_assessments(
            envelope.catalogue,
            assess_significant_families(envelope.catalogue, fingerprint),
        )
        return ComparisonLedger.for_catalogue_and_fingerprint(
            envelope.catalogue,
            fingerprint=fingerprint,
            catalogue_version=catalogue.version,
            catalogue_sha256=digest,
            capabilities=capabilities,
            entries=entries,
            family_entries=family_entries,
            local_entries=local_dispositions_from_proposals(fingerprint, proposals),
            reciprocal_answer=_reciprocal_answer(fingerprint, family_entries),
        )


def build_default_engine() -> DeterministicDiagnosisEngine:
    """Construct the process engine from app storage. Never used inside tests that inject."""

    run_store = DiagnosisRunStore(diagnosis_run_storage())
    return DeterministicDiagnosisEngine(
        run_store=run_store,
        consent_authority=LocalScopeConsentAuthority(),
        collector=ConsentBoundCollector(run_store),
        catalogue_loader=CachedCatalogueLoader(),
        comparer=UnknownUntilProposedComparer(),
        report_store=LensReportStore(default_report_directory()),
        clock=lambda: datetime.now(UTC),
    )
