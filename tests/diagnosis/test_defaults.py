"""Process-default engine construction and durable scope approval."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.concierge.test_diagnosis_consent import approved_scope_snapshot, invented_root
from tests.diagnosis.test_run import RUN_ID, approved_receipt
from tests.diagnosis.test_significant_family_assessment import _catalogue

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis import defaults
from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.defaults import (
    CachedCatalogueLoader,
    ConsentBoundCollector,
    UnknownUntilProposedComparer,
    build_default_engine,
    dispositions_from_proposals,
    local_dispositions_from_proposals,
)
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    EvidenceFingerprint,
    HealthState,
    Observation,
    ObservationKind,
    RuntimeState,
    SafeAttribute,
    observation_id_for,
)
from capability_exchange.diagnosis.orchestrator import DeterministicDiagnosisEngine
from capability_exchange.diagnosis.ranking import RecommendationFactors
from capability_exchange.diagnosis.run import DiagnosisStateError, canonical_json_digest
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposalError,
    ValidatedProposal,
    candidate_id_for,
)
from capability_exchange.evidence import EvidenceItem

_EVIDENCE = "evidence:sha256:" + ("ab" * 32)
_NOW = datetime(2026, 9, 1, tzinfo=UTC)
_PACKET_DIGEST = "sha256:" + "d" * 64
_PACKET_ID = "packet:" + _PACKET_DIGEST


def _proposal(
    *,
    catalogue_id: str = "cap-one",
    capability_id: str = "cap-one",
    disposition: Disposition = Disposition.STRONG_HERE,
    kind: ProposalKind = ProposalKind.STRENGTH,
    reason: str = "Quoted local evidence supports this strength.",
    observation_ids: tuple[str, ...] = (),
    disputed: bool = False,
) -> ValidatedProposal:
    values: dict[str, object] = {
        "kind": kind,
        "catalogue_id": catalogue_id,
        "capability_id": capability_id,
        "disposition": disposition,
        "evidence_ids": (_EVIDENCE,),
        "reason": reason,
        "observation_ids": observation_ids,
    }
    if disputed:
        values["disputed"] = True
    return ValidatedProposal.model_validate(values)


def _guided(
    *,
    kind: ProposalKind,
    disposition: Disposition,
    reason: str,
    catalogue_id: str = "cap-one",
    capability_id: str = "cap-one",
    factors: RecommendationFactors | None = None,
    evidence_ids: tuple[str, ...] = (_EVIDENCE,),
) -> ValidatedProposal:
    """A guided-lawful bound proposal, exactly as validation would emit it."""

    return ValidatedProposal(
        kind=kind,
        catalogue_id=catalogue_id,
        capability_id=capability_id,
        packet_id=_PACKET_ID,
        packet_digest=_PACKET_DIGEST,
        candidate_id=candidate_id_for(kind, catalogue_id, capability_id),
        disposition=disposition,
        recommendation_factors=factors,
        evidence_ids=evidence_ids,
        reason=reason,
    )


def _fingerprint() -> EvidenceFingerprint:
    return EvidenceFingerprint(
        adapter_id="synthetic",
        collected_at=_NOW,
        observations=(
            Observation(
                kind=ObservationKind.AUTOMATION,
                identity="nightly-check",
                label="Nightly check",
                configuration_state=ConfigurationState.ENABLED,
                runtime_state=RuntimeState.LOADED,
                health_state=HealthState.BROKEN,
                evidence=EvidenceItem(
                    state="observed",
                    captured_at=_NOW,
                    reference="file-token:nightly-check",
                ),
                provenance={
                    "source_id": "scope:primary",
                    "source_class": "vault-authored",
                    "scope_reference": "scope:sha256:" + "a" * 64,
                    "relative_reference": "Library/LaunchAgents/nightly-check.plist",
                },
            ),
        ),
    )


def test_build_default_engine_uses_app_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    engine = build_default_engine()
    assert isinstance(engine, DeterministicDiagnosisEngine)
    assert engine.consent_authority is not None
    assert engine.run_store.storage.is_relative_to((tmp_path / "state").resolve())


def test_collector_refuses_before_persisted_approval(tmp_path: Path) -> None:
    store = DiagnosisRunStore(tmp_path / "runs")
    collector = ConsentBoundCollector(store)
    with pytest.raises(DiagnosisStateError, match="approve the exact scope"):
        collector.collect(approved_receipt())


@pytest.mark.parametrize("include_live_state", (False, True))
def test_collector_runs_fixed_live_probe_only_after_explicit_consent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    include_live_state: bool,
) -> None:
    store = DiagnosisRunStore(tmp_path / "runs")
    root = invented_root(tmp_path)
    scope = approved_scope_snapshot(root)
    references = tuple(item.scope_reference for item in scope.source_descriptors)
    receipt = approved_receipt().model_copy(
        update={
            "scope_references": references,
            "scope_digest": canonical_json_digest(list(references)),
            "include_live_state": include_live_state,
        }
    )
    store.save_scope_approval(receipt, approved_roots=(str(root),))
    calls: list[object] = []

    def collect_live_states(*, scope_receipt: object) -> tuple[object, ...]:
        calls.append(scope_receipt)
        return ()

    monkeypatch.setattr(defaults, "collect_live_states", collect_live_states, raising=False)

    ConsentBoundCollector(store).collect(receipt)

    assert calls == ([receipt] if include_live_state else [])


def test_collector_refuses_live_state_escalation_beyond_persisted_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = DiagnosisRunStore(tmp_path / "runs")
    root = invented_root(tmp_path)
    scope = approved_scope_snapshot(root)
    references = tuple(item.scope_reference for item in scope.source_descriptors)
    approved = approved_receipt().model_copy(
        update={
            "scope_references": references,
            "scope_digest": canonical_json_digest(list(references)),
        }
    )
    escalated = approved.model_copy(update={"include_live_state": True})
    store.save_scope_approval(approved, approved_roots=(str(root),))
    calls: list[object] = []
    monkeypatch.setattr(
        defaults,
        "collect_live_states",
        lambda **kwargs: calls.append(kwargs) or (),
        raising=False,
    )

    with pytest.raises(DiagnosisStateError, match="receipt changed"):
        ConsentBoundCollector(store).collect(escalated)

    assert calls == []


def test_scope_approval_round_trips(tmp_path: Path) -> None:
    store = DiagnosisRunStore(tmp_path / "runs")
    root = invented_root(tmp_path)
    receipt = approved_receipt()
    store.save_scope_approval(receipt, approved_roots=(str(root),))
    loaded = store.load_scope_approval(RUN_ID)
    assert loaded is not None
    assert loaded.receipt == receipt
    assert loaded.approved_roots == (str(root),)
    assert store.list_resumable() == ()


def test_unproposed_identities_stay_not_assessed() -> None:
    entries = dispositions_from_proposals(("cap-one", "cap-two"), ())
    assert [item.disposition for item in entries] == [
        Disposition.NOT_ASSESSED,
        Disposition.NOT_ASSESSED,
    ]
    assert all("cleared the evidence bar" in item.reason for item in entries)


def test_agreed_proposal_fills_one_disposition() -> None:
    entries = dispositions_from_proposals(("cap-one",), (_proposal(),))
    assert entries[0].disposition is Disposition.STRONG_HERE
    assert entries[0].evidence_references == (_EVIDENCE,)


def test_conflicting_kinds_for_one_id_remain_unknown() -> None:
    entries = dispositions_from_proposals(
        ("cap-one",),
        (
            _proposal(),
            _proposal(
                kind=ProposalKind.FRAGILITY,
                disposition=Disposition.FRAGILE_OR_CONTRADICTORY,
                reason="The same file also contradicts the claim.",
            ),
        ),
    )
    assert entries[0].disposition is Disposition.NOT_ASSESSED
    # Evolved from the fixed DISAGREEMENT_REASON: the Unknown entry now names
    # the disagreeing dispositions so the dispute stays visible in the report.
    assert entries[0].reason == (
        "Specialist proposals disagreed between fragile-or-contradictory and "
        "strong-here; the sceptical review did not adjudicate, so the "
        "comparison remains Unknown."
    )


def test_reconciled_disagreement_still_outranks_an_agreed_claim() -> None:
    # Evolved for FINDING A1: the coalesced dispute is now marked by the
    # engine-set structural flag, never recognised from its reason text.
    named_disagreement = (
        "Specialist proposals disagreed between fragile-or-contradictory and "
        "strong-here; the sceptical review did not adjudicate, so the "
        "comparison remains Unknown."
    )
    entries = dispositions_from_proposals(
        ("cap-one",),
        (
            _proposal(),
            _proposal(
                kind=ProposalKind.FRAGILITY,
                disposition=Disposition.NOT_ASSESSED,
                reason=named_disagreement,
                disputed=True,
            ),
        ),
    )
    assert entries[0].disposition is Disposition.NOT_ASSESSED
    assert entries[0].reason == named_disagreement


def test_sentinel_shaped_reason_never_steals_the_disagreement_priority() -> None:
    """FINDING A1 (authority laundering): two guided-lawful proposals on one
    catalogue id disagree — mapping/not-relevant vs recommendation/
    worth-borrowing — so the entry must stay honestly Unknown.  A bound
    recommendation whose free-text reason merely echoes the engine's
    disagreement sentence shape must get the same answer: disagreement is a
    structural fact, never inferred from specialist-authored text."""

    factors = RecommendationFactors(
        reliability_risk=1,
        job_relevance=2,
        workflow_leverage=2,
        evidence_strength=2,
        adoption_effort=2,
    )
    mapping = _guided(
        kind=ProposalKind.MAPPING,
        disposition=Disposition.NOT_RELEVANT,
        reason="The local method does not map onto this catalogue entry.",
    )
    sentinel = (
        "Specialist proposals were weighed with care; "
        "the comparison remains Unknown."
    )

    honest = dispositions_from_proposals(
        ("cap-one",),
        (
            mapping,
            _guided(
                kind=ProposalKind.RECOMMENDATION,
                disposition=Disposition.WORTH_BORROWING,
                factors=factors,
                reason="Cited local evidence shows this addition would help.",
            ),
        ),
    )
    hijack = dispositions_from_proposals(
        ("cap-one",),
        (
            mapping,
            _guided(
                kind=ProposalKind.RECOMMENDATION,
                disposition=Disposition.WORTH_BORROWING,
                factors=factors,
                reason=sentinel,
            ),
        ),
    )

    assert honest[0].disposition is Disposition.NOT_ASSESSED
    assert hijack[0].disposition is Disposition.NOT_ASSESSED
    assert hijack[0].reason != sentinel


def test_conservative_factor_pick_ranks_worst_under_the_real_comparator() -> None:
    """FINDING C2: rank_recommendations sorts adoption_effort ASCENDING, so on
    factor tuples equal in the first four axes the old lexicographic-minimum
    pick (the lowest effort) actually ranked the recommendation HIGHER.  The
    conservative deterministic pick is the tuple the real comparator ranks
    worst — here the higher adoption effort."""

    easy = RecommendationFactors(
        reliability_risk=1,
        job_relevance=2,
        workflow_leverage=2,
        evidence_strength=2,
        adoption_effort=1,
    )
    hard = easy.model_copy(update={"adoption_effort": 3})
    reason = "Cited local evidence shows this addition would help."
    proposals = (
        _guided(
            kind=ProposalKind.RECOMMENDATION,
            disposition=Disposition.WORTH_BORROWING,
            factors=easy,
            reason=reason,
        ),
        _guided(
            kind=ProposalKind.MAPPING,
            disposition=Disposition.WORTH_BORROWING,
            factors=hard,
            reason=reason,
        ),
    )
    entries = dispositions_from_proposals(("cap-one",), proposals)
    assert entries[0].disposition is Disposition.WORTH_BORROWING

    ranked = defaults._ranked_recommendations_from_entries(entries, proposals)

    assert len(ranked) == 1
    assert ranked[0].factors == hard


def test_ranked_factors_come_only_from_the_entry_backing_candidate() -> None:
    """FINDING C2 (misattribution): factor options used to pool every proposal
    sharing the catalogue id, so a ranked row could carry one candidate's
    factors beside another candidate's evidence and reason.  Factors must come
    from the candidate the entry actually backs."""

    backing = RecommendationFactors(
        reliability_risk=2,
        job_relevance=2,
        workflow_leverage=2,
        evidence_strength=2,
        adoption_effort=2,
    )
    # A different candidate's tuple that BOTH pick rules over the pooled group
    # would select: lexicographic minimum and worst-ranked alike.
    other = RecommendationFactors(
        reliability_risk=0,
        job_relevance=0,
        workflow_leverage=0,
        evidence_strength=1,
        adoption_effort=3,
    )
    entry_backing = _guided(
        kind=ProposalKind.MAPPING,
        capability_id="capability-b",
        disposition=Disposition.WORTH_BORROWING,
        factors=backing,
        reason="Mapping evidence supports borrowing this method.",
    )
    other_candidate = _guided(
        kind=ProposalKind.RECOMMENDATION,
        capability_id="capability-a",
        disposition=Disposition.WORTH_BORROWING,
        factors=other,
        reason="A different candidate cites different evidence.",
    )
    proposals = (entry_backing, other_candidate)
    entries = dispositions_from_proposals(("cap-one",), proposals)
    assert entries[0].disposition is Disposition.WORTH_BORROWING
    assert entries[0].capability_id == "capability-b"

    ranked = defaults._ranked_recommendations_from_entries(entries, proposals)

    assert len(ranked) == 1
    assert ranked[0].capability_id == "capability-b"
    assert ranked[0].reason == "Mapping evidence supports borrowing this method."
    assert ranked[0].factors == backing


def test_forged_validated_proposal_cannot_cite_an_unknown_observation() -> None:
    forged_reference = "observation:sha256:" + "f" * 64

    with pytest.raises(SpecialistProposalError, match="current fingerprint"):
        local_dispositions_from_proposals(
            _fingerprint(),
            (_proposal(observation_ids=(forged_reference,)),),
        )


def test_local_disposition_preserves_all_three_observation_axes() -> None:
    entries = local_dispositions_from_proposals(_fingerprint(), ())

    assert len(entries) == 1
    assert entries[0].configuration_state is ConfigurationState.ENABLED
    assert entries[0].runtime_state is RuntimeState.LOADED
    assert entries[0].health_state is HealthState.BROKEN


def test_differing_skill_copies_deterministically_recommend_skill_grading() -> None:
    payload = _catalogue().model_dump(mode="json")
    payload["capabilities"][0]["capability_id"] = "skill-score"
    payload["capabilities"][0]["title"] = "Skill grading"
    payload["capability_aliases"] = []
    catalogue = CatalogueV2.model_validate(payload)
    store = SimpleNamespace(
        load_last_verified=lambda **_kwargs: SimpleNamespace(
            catalogue=catalogue,
            metadata=SimpleNamespace(catalog_version=7),
            _signed_json="synthetic-signed-catalogue",
        )
    )
    fingerprint = EvidenceFingerprint(
        adapter_id="synthetic",
        collected_at=_NOW,
        observations=(
            Observation(
                kind=ObservationKind.SKILL,
                identity="morning-plan",
                label="Morning plan",
                configuration_state=ConfigurationState.CONFLICTING,
                runtime_state=RuntimeState.NOT_ASSESSED,
                health_state=HealthState.NOT_ASSESSED,
                attributes=(
                    SafeAttribute(key="copy-count", value="5"),
                    SafeAttribute(key="variant-count", value="3"),
                ),
                evidence=EvidenceItem(
                    state="observed",
                    captured_at=_NOW,
                    reference="file-token:morning-plan",
                ),
                provenance={
                    "source_id": "scope:primary",
                    "source_class": "vault-authored",
                    "scope_reference": "scope:sha256:" + "a" * 64,
                    "relative_reference": "skills/morning-plan",
                },
            ),
        ),
    )
    slice_ = CachedCatalogueLoader(store).load(
        run_id=RUN_ID,
        fingerprint_digest="sha256:" + "b" * 64,
    )

    ledger = UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )

    recommendation = next(
        item for item in ledger.entries if item.catalogue_id == "skill-score"
    )
    assert recommendation.disposition is Disposition.WORTH_BORROWING
    assert "1 skill identity has 5 copies across 3 differing variants" in recommendation.reason
    assert recommendation.evidence_references == ("file-token:morning-plan",)
    local = next(
        item
        for item in ledger.local_entries
        if item.observation_id == observation_id_for(fingerprint.observations[0])
    )
    assert local.disposition is Disposition.WORTH_BORROWING
    assert local.mapped_catalogue_ids == ("skill-score",)
