"""Process-default diagnosis engine ports. CLI and MCP inject these."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.adapters.claude_code.discovery import discover_fingerprint
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
    HumanCapability,
)
from capability_exchange.diagnosis.observations import EvidenceFingerprint
from capability_exchange.diagnosis.orchestrator import (
    DeterministicDiagnosisEngine,
    VerifiedCatalogueSlice,
)
from capability_exchange.diagnosis.run import ApprovedScopeReceipt, DiagnosisStateError
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    DISAGREEMENT_REASON,
    ProposalKind,
    ValidatedProposal,
)
from capability_exchange.reports.store import LensReportStore, default_report_directory

__all__ = [
    "CachedCatalogueLoader",
    "ConsentBoundCollector",
    "UnknownUntilProposedComparer",
    "build_default_engine",
    "dispositions_from_proposals",
]

_NO_PROPOSAL = "No specialist proposal cleared the evidence bar."


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
        return discover_fingerprint(inspection, collected_at=inspection.taken_at)


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
            family_contract_present=False,
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
        del fingerprint, jobs
        envelope = _load_verified(self._store)
        digest = _signed_digest(envelope)
        if digest != catalogue.sha256:
            raise DiagnosisStateError("verified catalogue identity drifted; start a new run")
        capabilities = tuple(
            HumanCapability(
                capability_id=item.capability_id,
                title=item.title,
                job_ids=tuple(item.jobs),
                catalogue_ids=(item.capability_id,),
                person_observation_ids=(),
            )
            for item in envelope.catalogue.capabilities
        )
        entries = dispositions_from_proposals(
            tuple(item.capability_id for item in envelope.catalogue.capabilities),
            proposals,
        )
        return ComparisonLedger.for_catalogue(
            envelope.catalogue,
            catalogue_version=catalogue.version,
            catalogue_sha256=digest,
            capabilities=capabilities,
            entries=entries,
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
