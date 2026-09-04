"""A guided run driven end to end through the REAL shipped comparer.

Every other guided end-to-end test injects a fixed ``RecordingComparer``, so
``UnknownUntilProposedComparer``'s ledger assembly had never met real guided
proposals until the second real evaluation did it live — and wedged forever at
``analysis-completed`` with a blanket "not a closed typed diagnosis value".
These tests drive the shipped comparer with realistic specialist proposals:
multiple kinds across multiple packets, agreeing recommendations whose
evidence union overflows the cap, a strength and a reciprocal on the same
capability, an uncontested reciprocal lesson, and a sceptical response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from tests.concierge.test_diagnosis_consent import (
    approved_scope_snapshot as capture_scope,
)
from tests.concierge.test_diagnosis_consent import invented_root
from tests.diagnosis.test_significant_family_assessment import _catalogue, _skill

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.concierge.consent import LocalScopeConsentAuthority
from capability_exchange.diagnosis.comparison import (
    ComparisonLedger,
    Disposition,
    ledger_evidence_identities,
)
from capability_exchange.diagnosis.defaults import (
    CachedCatalogueLoader,
    UnknownUntilProposedComparer,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    SafeAttribute,
    observation_id_for,
)
from capability_exchange.diagnosis.orchestrator import (
    DeterministicDiagnosisEngine,
    PrepareDiagnosisRequest,
)
from capability_exchange.diagnosis.ranking import RecommendationFactors
from capability_exchange.diagnosis.run import (
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposal,
    SpecialistRole,
    ValidatedProposal,
    candidate_id_for,
)
from capability_exchange.diagnosis.work import AnalysisMode, WorkPacket
from capability_exchange.evidence import EvidenceItem, EvidenceState
from capability_exchange.reports.store import LensReportStore

NOW = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)

RECOMMENDED_ID = "dex-work-mcp"
STRENGTH_ID = "workflow-skill"
RECIPROCAL_ID = "dormant-helper"
FRAGILE_ID = "dex-nightly-check"

_FACTORS = RecommendationFactors(
    reliability_risk=1,
    job_relevance=2,
    workflow_leverage=2,
    evidence_strength=2,
    adoption_effort=2,
)

_SCEPTICAL_REASON = "The recommendation survives the sceptical evidence check."


def _signed_store(catalogue: CatalogueV2) -> SimpleNamespace:
    return SimpleNamespace(
        load_last_verified=lambda **_kwargs: SimpleNamespace(
            catalogue=catalogue,
            metadata=SimpleNamespace(catalog_version=7),
            _signed_json="invented-signed-catalogue",
        )
    )


def _fingerprint(observation_count: int = 10, *, differing_skill_copies: bool = False) -> (
    EvidenceFingerprint
):
    attributes: tuple[SafeAttribute, ...] = (
        SafeAttribute(key="source-kind", value="vault-authored"),
    )
    if differing_skill_copies:
        attributes = (
            SafeAttribute(key="copy-count", value="4"),
            SafeAttribute(key="variant-count", value="2"),
        )
    observations = tuple(
        Observation(
            kind=ObservationKind.SKILL,
            identity=f"invented-method-{index:02d}",
            label=f"Invented method {index:02d}",
            operational_state=OperationalState.IMPLEMENTED,
            evidence=EvidenceItem(
                state=EvidenceState.OBSERVED,
                captured_at=NOW,
                reference=f"file-token:invented-method-{index:02d}.md",
            ),
            provenance={
                "source_id": f"scope:invented-method-{index:02d}",
                "source_class": "vault-authored",
                "scope_reference": "scope:sha256:" + "c" * 64,
                "relative_reference": f"synthetic/invented-method-{index:02d}/SKILL.md",
            },
            attributes=attributes,
        )
        for index in range(observation_count)
    )
    return EvidenceFingerprint(
        adapter_id="invented-local-adapter",
        collected_at=NOW,
        observations=observations,
    )


class RecordingCollector:
    def __init__(self, fingerprint: EvidenceFingerprint) -> None:
        self.fingerprint = fingerprint

    def collect(self, receipt: object) -> EvidenceFingerprint:
        del receipt
        return self.fingerprint


class RealComparerHarness:
    """Real engine wired to the shipped catalogue loader and comparer."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        catalogue: CatalogueV2 | None = None,
        fingerprint: EvidenceFingerprint | None = None,
    ) -> None:
        self.root = invented_root(tmp_path)
        self.catalogue = catalogue if catalogue is not None else _catalogue()
        self.store = _signed_store(self.catalogue)
        self.consent_authority = LocalScopeConsentAuthority(now=lambda: NOW)
        self.collector = RecordingCollector(
            fingerprint if fingerprint is not None else _fingerprint()
        )
        self.run_store = DiagnosisRunStore(tmp_path / "state" / "diagnosis-runs")
        self.report_store = LensReportStore(tmp_path / "reports")
        self.engine = self._build_engine()

    def _build_engine(self) -> DeterministicDiagnosisEngine:
        return DeterministicDiagnosisEngine(
            run_store=self.run_store,
            consent_authority=self.consent_authority,
            collector=self.collector,
            catalogue_loader=CachedCatalogueLoader(self.store),
            comparer=UnknownUntilProposedComparer(self.store),
            report_store=self.report_store,
            clock=lambda: NOW,
        )

    def reopen(self) -> None:
        """Simulate resuming the same persisted run in a new process."""

        self.engine = self._build_engine()

    def approve(self, run_id: str) -> object:
        return self.consent_authority.approve_from_local_session(
            run_id=run_id,
            scope_snapshot=capture_scope(self.root),
            authenticated_session_id="local-session",
        )

    def run_to(self, run_id: str, stage: DiagnosisStage) -> object:
        view = self.engine.status(run_id)
        while view.stage is not stage:
            if view.stage is DiagnosisStage.CREATED:
                self.approve(run_id)
            view = self.engine.advance(run_id)
        return view


def _bound(
    packet: WorkPacket,
    *,
    kind: ProposalKind,
    catalogue_id: str,
    disposition: Disposition,
    evidence_ids: tuple[str, ...],
    observation_ids: tuple[str, ...],
    reason: str,
    factors: RecommendationFactors | None = None,
) -> SpecialistProposal:
    return SpecialistProposal(
        role=packet.role,
        kind=kind,
        run_id=packet.run_id,
        fingerprint_digest=packet.fingerprint_digest,
        catalogue_digest=packet.catalogue_digest,
        packet_id=packet.packet_id,
        packet_digest=packet.packet_digest,
        catalogue_id=catalogue_id,
        capability_id=catalogue_id,
        candidate_id=candidate_id_for(kind, catalogue_id, catalogue_id),
        disposition=disposition,
        recommendation_factors=factors,
        evidence_ids=evidence_ids,
        observation_ids=observation_ids,
        reason=reason,
    )


def _proposals_for_packet(packet: WorkPacket) -> tuple[SpecialistProposal, ...]:
    """Realistic proposals shaped like the founder's real guided run."""

    tokens = packet.evidence_ids
    observations = packet.observation_ids

    def recommendation(evidence: tuple[str, ...], observation: str) -> SpecialistProposal:
        return _bound(
            packet,
            kind=ProposalKind.RECOMMENDATION,
            catalogue_id=RECOMMENDED_ID,
            disposition=Disposition.WORTH_BORROWING,
            evidence_ids=evidence,
            observation_ids=(observation,),
            reason="The approved evidence supports this bounded Dex addition.",
            factors=_FACTORS,
        )

    if packet.role is SpecialistRole.TOOLS_AND_INTEGRATIONS:
        return (recommendation((tokens[0], tokens[1]), observations[0]),)
    if packet.role is SpecialistRole.AUTOMATIONS_AND_LIVE_STATE:
        return (
            recommendation((tokens[2], tokens[3]), observations[1]),
            _bound(
                packet,
                kind=ProposalKind.FRAGILITY,
                catalogue_id=FRAGILE_ID,
                disposition=Disposition.FRAGILE_OR_CONTRADICTORY,
                evidence_ids=(tokens[4],),
                observation_ids=(observations[4],),
                reason="Written intent and configured runtime contradict each other.",
            ),
        )
    if packet.role is SpecialistRole.PEOPLE_AND_WORK_CONTINUITY:
        return (recommendation((tokens[4], tokens[5]), observations[2]),)
    if packet.role is SpecialistRole.OPERATING_RHYTHM_AND_MEMORY:
        # Third and fourth agreeing packets push the coalesced evidence union
        # to nine tokens, past MAX_EVIDENCE_IDS, engaging the truncation path.
        return (recommendation((tokens[6], tokens[7], tokens[8]), observations[3]),)
    if packet.role is SpecialistRole.STRENGTH_AND_RECIPROCAL:
        return (
            _bound(
                packet,
                kind=ProposalKind.STRENGTH,
                catalogue_id=STRENGTH_ID,
                disposition=Disposition.STRONG_HERE,
                evidence_ids=(tokens[0], tokens[2]),
                observation_ids=(observations[5],),
                reason="The distinctive local method closes its loop reliably.",
            ),
            _bound(
                packet,
                kind=ProposalKind.RECIPROCAL,
                catalogue_id=STRENGTH_ID,
                disposition=Disposition.DEX_SHOULD_LEARN,
                evidence_ids=(tokens[1],),
                observation_ids=(observations[5],),
                reason="The same method review shows a transferable pattern.",
            ),
            _bound(
                packet,
                kind=ProposalKind.RECIPROCAL,
                catalogue_id=RECIPROCAL_ID,
                disposition=Disposition.DEX_SHOULD_LEARN,
                evidence_ids=(tokens[3],),
                observation_ids=(observations[6],),
                reason="An evidence-bound method review found a lesson Dex lacks.",
            ),
        )
    if packet.role is SpecialistRole.CONTRADICTIONS_AND_RELIABILITY:
        return (
            _bound(
                packet,
                kind=ProposalKind.FRAGILITY,
                catalogue_id=FRAGILE_ID,
                disposition=Disposition.FRAGILE_OR_CONTRADICTORY,
                evidence_ids=(tokens[4], tokens[5]),
                observation_ids=(observations[4],),
                reason="Written intent and configured runtime contradict each other.",
            ),
        )
    if packet.role is SpecialistRole.WORKFLOW_SYNTHESIS:
        return (
            _bound(
                packet,
                kind=ProposalKind.MAPPING,
                catalogue_id=STRENGTH_ID,
                disposition=Disposition.STRONG_HERE,
                evidence_ids=(tokens[8], tokens[9]),
                observation_ids=(observations[7],),
                reason="Two approved surfaces connect into one working flow.",
            ),
        )
    if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
        # An unchanged accept of the coalesced recommendation baseline must
        # retain the baseline's exact (truncated) evidence and observations.
        return (
            _bound(
                packet,
                kind=ProposalKind.RECOMMENDATION,
                catalogue_id=RECOMMENDED_ID,
                disposition=Disposition.WORTH_BORROWING,
                evidence_ids=tuple(sorted(tokens[0:9]))[:8],
                observation_ids=tuple(sorted(observations[0:4])),
                reason=_SCEPTICAL_REASON,
                factors=_FACTORS,
            ),
        )
    return ()


def _drive_to_analysis_completed(harness: RealComparerHarness) -> str:
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=AnalysisMode.GUIDED)
    )
    harness.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    while True:
        packet = harness.engine.work(prepared.run_id)
        if packet is None:
            break
        harness.engine.submit_work(
            prepared.run_id, packet.packet_id, _proposals_for_packet(packet)
        )
    completed = harness.engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    return prepared.run_id


@pytest.fixture
def harness(tmp_path: Path) -> RealComparerHarness:
    return RealComparerHarness(tmp_path)


def test_real_comparer_guided_run_reaches_closed_with_its_findings(
    harness: RealComparerHarness,
) -> None:
    """Proposals in, CLOSED out, findings rendered — through the REAL comparer.

    Before the fix this run wedged permanently at analysis-completed: the
    uncontested reciprocal (dex-should-learn) built a ``CatalogueDisposition``
    with ``method_compared=False`` and every advance raised a pydantic
    ValidationError.
    """

    run_id = _drive_to_analysis_completed(harness)
    closed = harness.run_to(run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED

    result = harness.engine.result(run_id)
    ledger = result.ledger
    entries = {item.catalogue_id: item for item in ledger.entries}

    recommended = entries[RECOMMENDED_ID]
    assert recommended.disposition is Disposition.WORTH_BORROWING
    assert len(recommended.evidence_references) == 8  # truncated nine-token union
    assert recommended.reason == _SCEPTICAL_REASON

    assert len(ledger.ranked_recommendations) == 1
    ranked = ledger.ranked_recommendations[0]
    assert ranked.catalogue_id == RECOMMENDED_ID
    assert ranked.evidence_ids == tuple(sorted(recommended.evidence_references))
    assert ranked.factors == _FACTORS

    # Strength and reciprocal on the same capability disagree on the verdict,
    # so the entry stays honestly Unknown while both insights survive.
    strength_entry = entries[STRENGTH_ID]
    assert strength_entry.disposition is Disposition.NOT_ASSESSED
    assert "dex-should-learn" in strength_entry.reason
    assert "strong-here" in strength_entry.reason

    reciprocal_entry = entries[RECIPROCAL_ID]
    assert reciprocal_entry.disposition is Disposition.DEX_SHOULD_LEARN
    assert reciprocal_entry.method_compared is True

    assert entries[FRAGILE_ID].disposition is Disposition.FRAGILE_OR_CONTRADICTORY

    assert {item.title for item in ledger.strengths} == {STRENGTH_ID}
    assert {item.title for item in ledger.reciprocal_lessons} == {
        STRENGTH_ID,
        RECIPROCAL_ID,
    }
    held = ledger_evidence_identities(ledger)
    for insight in (*ledger.strengths, *ledger.reciprocal_lessons, *ledger.workflow_insights):
        assert set(insight.evidence_ids) <= held

    markdown = result.render_markdown()
    assert _SCEPTICAL_REASON in markdown
    assert "An evidence-bound method review found a lesson Dex lacks." in markdown


def test_wedged_run_at_analysis_completed_recovers_after_reopen(
    harness: RealComparerHarness,
) -> None:
    """The founder's wedge: same persisted state, advance now succeeds.

    The run is driven to analysis-completed (the exact state the wedged real
    run is parked in), the engine is rebuilt over the same run store as a
    resume would do, and advance must now walk to CLOSED.
    """

    run_id = _drive_to_analysis_completed(harness)
    harness.reopen()

    compared = harness.engine.advance(run_id)
    assert compared.stage is DiagnosisStage.COMPARED
    closed = harness.run_to(run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED


def _compare_directly(
    harness: RealComparerHarness,
    proposals: tuple[ValidatedProposal, ...],
) -> ComparisonLedger:
    comparer = UnknownUntilProposedComparer(harness.store)
    catalogue_slice = CachedCatalogueLoader(harness.store).load(
        run_id="run:" + "a" * 32, fingerprint_digest="sha256:" + "d" * 64
    )
    return comparer.compare(
        fingerprint=harness.collector.fingerprint,
        catalogue=catalogue_slice,
        jobs=(),
        proposals=proposals,
    )


def _validated(
    *,
    kind: ProposalKind,
    catalogue_id: str,
    disposition: Disposition,
    evidence_ids: tuple[str, ...],
    observation_ids: tuple[str, ...] = (),
    reason: str,
    factors: RecommendationFactors | None = None,
) -> ValidatedProposal:
    return ValidatedProposal(
        kind=kind,
        catalogue_id=catalogue_id,
        capability_id=catalogue_id,
        disposition=disposition,
        recommendation_factors=factors,
        evidence_ids=evidence_ids,
        observation_ids=observation_ids,
        reason=reason,
    )


def test_uncontested_reciprocal_builds_a_lawful_method_reviewed_entry(
    harness: RealComparerHarness,
) -> None:
    """A reciprocal proposal is a method review; its entry must construct.

    Before the fix this raised ``ValidationError`` for ``CatalogueDisposition``
    ("Dex-should-learn requires method evidence, not identity overlap")
    because ``method_compared`` was derived from the method-comparison kind
    alone.
    """

    observation = observation_id_for(harness.collector.fingerprint.observations[0])
    ledger = _compare_directly(
        harness,
        (
            _validated(
                kind=ProposalKind.RECIPROCAL,
                catalogue_id=RECIPROCAL_ID,
                disposition=Disposition.DEX_SHOULD_LEARN,
                evidence_ids=("evidence:sha256:" + "1" * 64,),
                observation_ids=(observation,),
                reason="An evidence-bound method review found a lesson Dex lacks.",
            ),
        ),
    )
    entry = next(item for item in ledger.entries if item.catalogue_id == RECIPROCAL_ID)
    assert entry.disposition is Disposition.DEX_SHOULD_LEARN
    assert entry.method_compared is True
    assert len(ledger.reciprocal_lessons) == 1


def test_method_level_claim_without_a_method_review_stays_unknown(
    harness: RealComparerHarness,
) -> None:
    """A dex-should-learn claim no method-level kind supports downgrades
    honestly to not-assessed instead of failing ledger construction."""

    observation = observation_id_for(harness.collector.fingerprint.observations[0])
    ledger = _compare_directly(
        harness,
        (
            _validated(
                kind=ProposalKind.STRENGTH,
                catalogue_id=STRENGTH_ID,
                disposition=Disposition.DEX_SHOULD_LEARN,
                evidence_ids=("evidence:sha256:" + "2" * 64,),
                observation_ids=(observation,),
                reason="A strength claim cannot stand in for a method review.",
            ),
        ),
    )
    entry = next(item for item in ledger.entries if item.catalogue_id == STRENGTH_ID)
    assert entry.disposition is Disposition.NOT_ASSESSED
    assert "method review" in entry.reason


def test_strength_and_recommendation_on_one_identity_stay_consistent(
    harness: RealComparerHarness,
) -> None:
    """Disagreeing kinds on one catalogue identity must not leave a ranked
    recommendation pointing at a not-assessed entry.

    Before the fix the ranked list was derived from the proposals while the
    entry was derived from the disagreement, and ``ComparisonLedger`` raised
    "ranked recommendations must equal the ledger recommendation identities".
    """

    observation = observation_id_for(harness.collector.fingerprint.observations[0])
    ledger = _compare_directly(
        harness,
        (
            _validated(
                kind=ProposalKind.RECOMMENDATION,
                catalogue_id=RECOMMENDED_ID,
                disposition=Disposition.WORTH_BORROWING,
                evidence_ids=("evidence:sha256:" + "3" * 64,),
                observation_ids=(observation,),
                reason="The approved evidence supports this bounded Dex addition.",
                factors=_FACTORS,
            ),
            _validated(
                kind=ProposalKind.STRENGTH,
                catalogue_id=RECOMMENDED_ID,
                disposition=Disposition.STRONG_HERE,
                evidence_ids=("evidence:sha256:" + "4" * 64,),
                observation_ids=(observation,),
                reason="The same identity is already distinctively strong here.",
            ),
        ),
    )
    entry = next(item for item in ledger.entries if item.catalogue_id == RECOMMENDED_ID)
    assert entry.disposition is Disposition.NOT_ASSESSED
    assert ledger.ranked_recommendations == ()


def test_deterministic_skill_copy_recommendation_ranks_beside_a_guided_one(
    tmp_path: Path,
) -> None:
    """Every worth-borrowing entry must reach the ranked list.

    Before the fix the deterministic skill-copy recommendation carried no
    recommendation factors, so it could never be ranked, and any guided
    recommendation beside it made ``ComparisonLedger`` raise "ranked
    recommendations must equal the ledger recommendation identities".
    """

    payload = _catalogue().model_dump(mode="json")
    payload["capabilities"].append(_skill("skill-score"))
    payload["capabilities"][-1]["title"] = "Skill grading"
    catalogue = CatalogueV2.model_validate(payload)
    harness = RealComparerHarness(
        tmp_path,
        catalogue=catalogue,
        fingerprint=_fingerprint(2, differing_skill_copies=True),
    )
    observation = observation_id_for(harness.collector.fingerprint.observations[0])
    ledger = _compare_directly(
        harness,
        (
            _validated(
                kind=ProposalKind.RECOMMENDATION,
                catalogue_id=RECOMMENDED_ID,
                disposition=Disposition.WORTH_BORROWING,
                evidence_ids=("evidence:sha256:" + "5" * 64,),
                observation_ids=(observation,),
                reason="The approved evidence supports this bounded Dex addition.",
                factors=_FACTORS,
            ),
        ),
    )
    worth_borrowing = {
        item.catalogue_id
        for item in ledger.entries
        if item.disposition is Disposition.WORTH_BORROWING
    }
    assert worth_borrowing == {RECOMMENDED_ID, "skill-score"}
    assert {item.catalogue_id for item in ledger.ranked_recommendations} == worth_borrowing


def test_insight_evidence_never_exceeds_what_the_ledger_holds(
    harness: RealComparerHarness,
) -> None:
    """A truncated evidence union must not leave an insight citing a token
    the ledger no longer holds, which would wedge the run at render."""

    tokens = tuple("evidence:sha256:" + f"{index:x}" * 64 for index in range(1, 10))
    ledger = _compare_directly(
        harness,
        (
            _validated(
                kind=ProposalKind.STRENGTH,
                catalogue_id=STRENGTH_ID,
                disposition=Disposition.STRONG_HERE,
                evidence_ids=tokens[0:8],
                reason="The distinctive local method closes its loop reliably.",
            ),
            _validated(
                kind=ProposalKind.FRAGILITY,
                catalogue_id=STRENGTH_ID,
                disposition=Disposition.FRAGILE_OR_CONTRADICTORY,
                evidence_ids=tokens[7:9],
                reason="The same surface also carries a material contradiction.",
            ),
        ),
    )
    held = ledger_evidence_identities(ledger)
    for insight in (*ledger.strengths, *ledger.reciprocal_lessons, *ledger.workflow_insights):
        assert set(insight.evidence_ids) <= held
        assert insight.evidence_ids


class _InconsistentComparer:
    """A comparer whose output fails typed validation, carrying a canary."""

    CANARY = "INVENTED/CANARY/VALUE/NEVER/PRINT"

    def compare(self, **_kwargs: object) -> ComparisonLedger:
        from capability_exchange.diagnosis.comparison import CatalogueDisposition

        CatalogueDisposition(
            catalogue_id=self.CANARY,
            disposition=Disposition.STRONG_HERE,
            capability_id="invented-capability",
            evidence_references=("evidence:sha256:" + "6" * 64,),
            reason="Deliberately inconsistent comparer output.",
        )
        raise AssertionError("unreachable: the construction above must fail")


def test_compare_failure_is_a_typed_refusal_naming_model_and_fields(
    tmp_path: Path,
) -> None:
    """A ValidationError inside compare becomes a DiagnosisStateError that
    names the failing model and field names — and never any value."""

    harness = RealComparerHarness(tmp_path)
    harness.engine = DeterministicDiagnosisEngine(
        run_store=harness.run_store,
        consent_authority=harness.consent_authority,
        collector=harness.collector,
        catalogue_loader=CachedCatalogueLoader(harness.store),
        comparer=_InconsistentComparer(),
        report_store=harness.report_store,
        clock=lambda: NOW,
    )
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=AnalysisMode.INVENTORY_ONLY)
    )
    harness.run_to(prepared.run_id, DiagnosisStage.JOBS_CONFIRMED)

    with pytest.raises(DiagnosisStateError) as excinfo:
        harness.engine.advance(prepared.run_id)

    message = str(excinfo.value)
    assert not isinstance(excinfo.value, ValidationError)
    assert "CatalogueDisposition" in message
    assert "catalogue_id" in message
    assert _InconsistentComparer.CANARY not in message
