"""Process-default diagnosis engine ports. CLI and MCP inject these."""

from __future__ import annotations

import hashlib
import json
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
    KeyRing,
    LegacySkillCapabilityEntryV2,
    VerifiedCatalogueStore,
    capability_availability_of,
    capability_class_of,
    default_keyring,
    verify_catalogue_envelope,
)
from capability_exchange.concierge.collection import ScopeSnapshot, default_source_descriptors
from capability_exchange.concierge.consent import LocalScopeConsentAuthority
from capability_exchange.diagnosis.automatic import build_automatic_candidates
from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    FamilyLedgerEntry,
    HumanCapability,
    LocalObservationDisposition,
    VersionDistance,
    family_entries_from_assessments,
    insights_from_proposals,
    ranked_recommendations_from_proposals,
)
from capability_exchange.diagnosis.expectations import assess_wow_expectations
from capability_exchange.diagnosis.families import build_family_delta
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    HealthState,
    Observation,
    ObservationKind,
    RuntimeState,
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
    MAX_RECOMMENDATIONS,
    ProposalKind,
    SpecialistProposalError,
    ValidatedProposal,
    disagreement_reason,
    is_disagreement_reason,
)
from capability_exchange.diagnosis.work import WorkAudit
from capability_exchange.diagnosis.workflows import WorkflowGraph, build_workflow_graph
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
_SKILL_SCORE_ID = "skill-score"
_BUNDLED_REFERENCE_PATH = (
    Path(__file__).resolve().parents[1] / "skill" / "dex-lens" / "dex-capabilities.json"
)
_FOUR_CAPABILITY_CLASSES = frozenset(
    {"active-skill", "mcp-server", "scheduled-automation", "system-engine"}
)


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
        matched_observations = {
            observation_id_for(observation): observation
            for observation in fingerprint.observations
            if observation_id_for(observation) in matched_observation_ids
        }
        working_observation_ids = {
            observation_id
            for observation_id, observation in matched_observations.items()
            if observation.runtime_state is RuntimeState.OUTCOME_VERIFIED
            or observation.health_state is HealthState.HEALTHY
        }
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
        if not working_observation_ids:
            return (
                f"Your approved snapshot contains {building_count} evidence-bound local "
                f"{_plural(building_count, 'building block')} across {kind_count} "
                f"{_plural(kind_count, 'capability type')}, with {matched_components} exact "
                f"signed {_plural(matched_components, 'component overlap')} across "
                f"{matched_families} Dex outcome "
                f"{_plural(matched_families, 'family', 'families')}. These are exact "
                "configuration matches: they show what you have assembled, not whether it "
                "runs well. What Dex should learn remains Unknown until verified outcome or "
                "health evidence, or an evidence-bound method review, establishes a "
                "transferable pattern."
            )
        return (
            f"Your approved snapshot demonstrates {len(working_observation_ids)} outcome- "
            f"or health-verified local {_plural(len(working_observation_ids), 'building block')} "
            f"within {building_count} matched {_plural(building_count, 'building block')} "
            f"across {kind_count} {_plural(kind_count, 'capability type')}, with "
            f"{matched_components} exact "
            f"signed {_plural(matched_components, 'component overlap')} across "
            f"{matched_families} Dex outcome {_plural(matched_families, 'family', 'families')}. "
            f"The strongest evidence-bound overlaps are around {named_strengths}. "
            "What Dex should learn remains Unknown until an evidence-bound method review "
            "establishes a transferable pattern. Exact identity overlap does not prove "
            "method equivalence; the working-state claim is limited to the cited local "
            "outcome or health evidence."
        )
    observation_count = len(fingerprint.observations)
    kind_count = len({observation.kind for observation in fingerprint.observations})
    return (
        f"Your approved snapshot contains {observation_count} evidence-bound local "
        f"{_plural(observation_count, 'observation')} across {kind_count} observed "
        f"{_plural(kind_count, 'capability type')}. What Dex should learn remains Unknown "
        "because no exact significant-family overlap cleared the evidence bar."
    )


def _version_distance(
    fingerprint: EvidenceFingerprint,
    *,
    current_version: str | None,
    catalogue: object,
) -> VersionDistance | None:
    """Use only exact local Dex lineage and signed skill release fields."""

    if current_version is None or not catalogue.capability_families:
        return None
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
        return None
    inspected_version = next(iter(observed_versions))
    if inspected_version == current_version:
        return None
    evidence = tuple(
        sorted({observation.evidence.reference for observation in release_observations})
    )[:8]
    if not evidence:
        return None
    entries_by_id = {entry.capability_id: entry for entry in catalogue.capabilities}
    try:
        families = tuple(
            delta
            for family in sorted(catalogue.capability_families, key=lambda item: item.family_id)
            if (
                delta := build_family_delta(
                    current_version=current_version,
                    inspected_version=inspected_version,
                    family=family,
                    entries=tuple(
                        entries_by_id[item] for item in family.member_capability_ids
                    ),
                )
            )
            is not None
        )
    except ValueError:
        return None
    if not families:
        return None
    return VersionDistance(
        inspected_version=inspected_version,
        current_version=current_version,
        evidence_references=evidence,
        families=families,
    )


def _verified_store(store: VerifiedCatalogueStore | None) -> VerifiedCatalogueStore:
    if store is not None:
        return store
    return VerifiedCatalogueStore(default_lens_app_storage())


def _keyring_or_default(keyring: KeyRing | None) -> KeyRing:
    if keyring is not None:
        return keyring
    return default_keyring()


def _signed_digest(envelope: object) -> str:
    signed = getattr(envelope, "_signed_json", None) or envelope.model_dump_json()
    return hashlib.sha256(signed.encode("utf-8")).hexdigest()


def _load_verified(store: VerifiedCatalogueStore, keyring: KeyRing | None = None) -> object:
    try:
        return store.load_last_verified(keyring=_keyring_or_default(keyring))
    except CatalogueVerificationError as exc:
        raise DiagnosisStateError(
            "verify the Dex catalogue first with dex-lens catalogue"
        ) from exc


def _load_bundled_reference(*, now: datetime | None = None) -> object:
    """Re-verify the current packaged four-class fallback; never trust summary prose."""

    try:
        wrapper = json.loads(_BUNDLED_REFERENCE_PATH.read_text(encoding="utf-8"))
        if not isinstance(wrapper, dict) or wrapper.get("reference_version") != 2:
            raise ValueError("unexpected bundled reference contract")
        signed_catalogue = wrapper["signed_catalogue"]
        raw = json.dumps(signed_catalogue, sort_keys=True, separators=(",", ":"))
        envelope = verify_catalogue_envelope(
            raw,
            keyring=default_keyring(),
            now=now,
        )
    except (OSError, KeyError, TypeError, ValueError, CatalogueVerificationError) as exc:
        raise DiagnosisStateError(
            "the bundled Dex capability reference could not be verified for current diagnosis"
        ) from exc
    classes = {capability_class_of(item) for item in envelope.catalogue.capabilities}
    if classes != _FOUR_CAPABILITY_CLASSES:
        raise DiagnosisStateError(
            "the bundled Dex capability reference does not contain all four classes"
        )
    return envelope


def _load_diagnosis_envelope(
    store: VerifiedCatalogueStore, keyring: KeyRing | None = None
) -> object:
    """Choose one complete verified envelope without overlaying catalogue truth."""

    current = _load_verified(store, keyring)
    entries = tuple(current.catalogue.capabilities)
    classes = {capability_class_of(item) for item in current.catalogue.capabilities}
    legacy_entries = tuple(
        item for item in entries if isinstance(item, LegacySkillCapabilityEntryV2)
    )
    if legacy_entries and len(legacy_entries) != len(entries):
        raise DiagnosisStateError(
            "the verified catalogue mixes legacy and enriched skill entries; "
            "diagnosis requires one complete contract shape"
        )
    if not legacy_entries and classes == _FOUR_CAPABILITY_CLASSES:
        return current
    if not legacy_entries:
        raise DiagnosisStateError(
            "the verified catalogue has incomplete capability classes; diagnosis requires "
            "either the legacy skills-only contract or all four enriched classes"
        )
    bundled = _load_bundled_reference()
    if bundled.metadata.catalog_version < current.metadata.catalog_version:
        raise DiagnosisStateError(
            "the verified catalogue is skills-only and the bundled four-class "
            "reference is older"
        )
    return bundled


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
    disagreement = next((item for item in group if is_disagreement_reason(item.reason)), None)
    chosen = disagreement or _agreed_or_unknown(capability_id, group)
    method_compared = chosen.kind is ProposalKind.METHOD_COMPARISON
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
        reason=disagreement_reason(dispositions),
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


def _attribute_count(observation: Observation, key: str) -> int:
    value = next((item.value for item in observation.attributes if item.key == key), "0")
    try:
        return int(value)
    except ValueError:
        return 0


def _automatic_proposals(
    *,
    fingerprint: EvidenceFingerprint,
    catalogue: VerifiedCatalogueSlice,
    envelope: object,
    family_assessments: tuple[object, ...],
    workflows: WorkflowGraph,
    proposals: tuple[ValidatedProposal, ...],
) -> tuple[ValidatedProposal, ...]:
    """Add conservative automatic candidates when typed preconditions are met."""

    automatic = build_automatic_candidates(
        catalogue=envelope.catalogue,
        fingerprint=fingerprint,
        workflows=workflows,
        family_assessments=family_assessments,
    )
    if not automatic:
        return proposals
    existing = {
        item.catalogue_id
        for item in proposals
        if item.disposition is Disposition.WORTH_BORROWING
    }
    extras: list[ValidatedProposal] = []
    for candidate in automatic:
        if candidate.catalogue_id in existing:
            continue
        if (
            candidate.catalogue_id in set(catalogue.unavailable_ids)
            or candidate.catalogue_id not in set(catalogue.catalogue_ids)
        ):
            continue
        if sum(
            item.kind is ProposalKind.RECOMMENDATION
            or item.disposition is Disposition.WORTH_BORROWING
            for item in (*proposals, *extras)
        ) >= MAX_RECOMMENDATIONS:
            break
        extras.append(
            ValidatedProposal(
                kind=ProposalKind.RECOMMENDATION,
                catalogue_id=candidate.catalogue_id,
                capability_id=candidate.capability_id,
                disposition=Disposition.WORTH_BORROWING,
                evidence_ids=candidate.evidence_ids,
                observation_ids=candidate.observation_ids,
                reason=candidate.reason,
                recommendation_factors=candidate.factors,
                candidate_id=f"automatic:{candidate.catalogue_id}",
            )
        )
        existing.add(candidate.catalogue_id)
    if not extras:
        return proposals
    return proposals + tuple(extras)


def _with_deterministic_skill_copy_recommendation(
    fingerprint: EvidenceFingerprint,
    catalogue: VerifiedCatalogueSlice,
    proposals: tuple[ValidatedProposal, ...],
) -> tuple[ValidatedProposal, ...]:
    """Recommend grading only when bounded evidence proves differing skill copies."""

    catalogue_ids = set(catalogue.catalogue_ids)
    if (
        _SKILL_SCORE_ID not in catalogue_ids
        or _SKILL_SCORE_ID in set(catalogue.unavailable_ids)
        or any(item.catalogue_id == _SKILL_SCORE_ID for item in proposals)
    ):
        return proposals
    recommendation_count = sum(
        item.kind is ProposalKind.RECOMMENDATION
        or item.disposition is Disposition.WORTH_BORROWING
        for item in proposals
    )
    if recommendation_count >= MAX_RECOMMENDATIONS:
        return proposals
    differing = tuple(
        observation
        for observation in fingerprint.observations
        if observation.kind is ObservationKind.SKILL
        and _attribute_count(observation, "copy-count") > 1
        and _attribute_count(observation, "variant-count") > 1
    )
    if not differing:
        return proposals
    identities = len({observation.identity for observation in differing})
    copy_count = sum(_attribute_count(observation, "copy-count") for observation in differing)
    variant_count = sum(
        _attribute_count(observation, "variant-count") for observation in differing
    )
    reason = (
        f"{identities} skill {_plural(identities, 'identity', 'identities')} "
        f"{_plural(identities, 'has', 'have')} {copy_count} copies across "
        f"{variant_count} differing variants in the approved snapshot; grade and "
        "choose canonical copies before consolidating them."
    )
    evidence_ids = tuple(
        sorted({observation.evidence.reference for observation in differing})
    )[:8]
    observation_ids = tuple(
        sorted({observation_id_for(observation) for observation in differing})
    )[:8]
    return proposals + (
        ValidatedProposal(
            kind=ProposalKind.RECOMMENDATION,
            catalogue_id=_SKILL_SCORE_ID,
            capability_id=_SKILL_SCORE_ID,
            disposition=Disposition.WORTH_BORROWING,
            evidence_ids=evidence_ids,
            reason=reason,
            observation_ids=observation_ids,
        ),
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
    """Load the last signature-verified catalogue. Do not fetch here.

    ``keyring`` defaults to the pinned production Dex Core keys. Tests inject
    an invented keyring so the complete verification path — signature, schema,
    expiry and rollback — is exercised with keys that exist only in the test.
    """

    def __init__(
        self,
        store: VerifiedCatalogueStore | None = None,
        *,
        keyring: KeyRing | None = None,
    ) -> None:
        self._store = _verified_store(store)
        self._keyring = keyring

    def load(self, *, run_id: str, fingerprint_digest: str) -> VerifiedCatalogueSlice:
        del run_id, fingerprint_digest
        envelope = _load_diagnosis_envelope(self._store, self._keyring)
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
            core_release=getattr(envelope.metadata, "core_release", None),
        )


class UnknownUntilProposedComparer:
    """Complete ledger: every catalogue identity starts as not-assessed."""

    def __init__(
        self,
        store: VerifiedCatalogueStore | None = None,
        *,
        keyring: KeyRing | None = None,
    ) -> None:
        self._store = _verified_store(store)
        self._keyring = keyring

    def compare(
        self,
        *,
        fingerprint: EvidenceFingerprint,
        catalogue: VerifiedCatalogueSlice,
        jobs: tuple[object, ...],
        proposals: tuple[ValidatedProposal, ...],
        work_audit: WorkAudit | None = None,
    ) -> ComparisonLedger:
        del jobs
        envelope = _load_diagnosis_envelope(self._store, self._keyring)
        digest = _signed_digest(envelope)
        if digest != catalogue.sha256:
            raise DiagnosisStateError("verified catalogue identity drifted; start a new run")
        workflows = build_workflow_graph(fingerprint)
        assessments = assess_significant_families(envelope.catalogue, fingerprint)
        proposals = _automatic_proposals(
            fingerprint=fingerprint,
            catalogue=catalogue,
            envelope=envelope,
            family_assessments=assessments,
            workflows=workflows,
            proposals=_with_deterministic_skill_copy_recommendation(
                fingerprint,
                catalogue,
                proposals,
            ),
        )
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
        family_entries = family_entries_from_assessments(envelope.catalogue, assessments)
        strengths, reciprocal_lessons, workflow_insights = insights_from_proposals(proposals)
        version_distance = _version_distance(
            fingerprint,
            current_version=catalogue.core_release,
            catalogue=envelope.catalogue,
        )
        return ComparisonLedger.for_catalogue_and_fingerprint(
            envelope.catalogue,
            fingerprint=fingerprint,
            catalogue_version=catalogue.version,
            catalogue_sha256=digest,
            capabilities=capabilities,
            entries=entries,
            ranked_recommendations=ranked_recommendations_from_proposals(proposals),
            family_entries=family_entries,
            version_distance=version_distance,
            local_entries=local_dispositions_from_proposals(fingerprint, proposals),
            reciprocal_answer=_reciprocal_answer(fingerprint, family_entries),
            workflow_graph=workflows,
            work_audit=work_audit,
            expectations=assess_wow_expectations(envelope.catalogue, assessments),
            strengths=strengths,
            reciprocal_lessons=reciprocal_lessons,
            workflow_insights=workflow_insights,
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
