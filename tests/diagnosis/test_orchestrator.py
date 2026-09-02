"""Deterministic diagnosis engine owns stage transitions and typed save."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.concierge.test_diagnosis_consent import approved_scope_snapshot as capture_scope
from tests.concierge.test_diagnosis_consent import invented_root
from tests.evals.real_session_fixture import real_session_fingerprint

from capability_exchange.concierge.collection import ScopeSnapshot
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
    PrepareDiagnosisRequest,
    VerifiedCatalogueSlice,
    fingerprint_digest_for,
)
from capability_exchange.diagnosis.report import ReportModel, canonical_fact_block
from capability_exchange.diagnosis.run import (
    NEXT_ACTION,
    ApprovedScopeReceipt,
    DiagnosisCheckpoint,
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    ValidatedProposal,
    candidate_id_for,
    mint_evidence_token,
)
from capability_exchange.diagnosis.work import AnalysisMode, WorkStatus
from capability_exchange.reports.store import LensReportStore

NOW = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)
CATALOGUE_ID = "invented-capability-000"
CAPABILITY_ID = "invented-capability-000"
_ROOT: Path | None = None


def _tiny_ledger(*, catalogue_sha256: str = "b" * 64) -> ComparisonLedger:
    return ComparisonLedger(
        catalogue_version=1,
        catalogue_sha256=catalogue_sha256,
        capabilities=(
            HumanCapability(
                capability_id=CAPABILITY_ID,
                title="Invented capability 000",
                job_ids=("invented-job-000",),
                catalogue_ids=(CATALOGUE_ID,),
                person_observation_ids=(),
            ),
        ),
        entries=(
            CatalogueDisposition(
                catalogue_id=CATALOGUE_ID,
                disposition=Disposition.NOT_ASSESSED,
                capability_id=CAPABILITY_ID,
                reason="Invented harness left this entry Unknown.",
            ),
        ),
        reciprocal_answer="No transferable method cleared the evidence bar.",
    )


@dataclass
class RecordingCollector:
    fingerprint: EvidenceFingerprint
    calls: list[ApprovedScopeReceipt] = field(default_factory=list)

    def collect(self, receipt: ApprovedScopeReceipt) -> EvidenceFingerprint:
        self.calls.append(receipt)
        return self.fingerprint


@dataclass
class RecordingCatalogueLoader:
    slice: VerifiedCatalogueSlice
    calls: list[dict[str, str]] = field(default_factory=list)

    def load(self, *, run_id: str, fingerprint_digest: str) -> VerifiedCatalogueSlice:
        self.calls.append({"run_id": run_id, "fingerprint_digest": fingerprint_digest})
        return self.slice


@dataclass
class RecordingComparer:
    ledger: ComparisonLedger
    calls: list[dict[str, object]] = field(default_factory=list)

    def compare(
        self,
        *,
        fingerprint: object,
        catalogue: VerifiedCatalogueSlice,
        jobs: tuple[object, ...],
        proposals: tuple[ValidatedProposal, ...],
    ) -> ComparisonLedger:
        self.calls.append(
            {
                "fingerprint": fingerprint,
                "catalogue": catalogue,
                "jobs": jobs,
                "proposals": proposals,
            }
        )
        return self.ledger


class RecordingReportStore(LensReportStore):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.save_calls: list[str] = []
        self.save_result_calls: list[object] = []
        self._inside_save_result = False

    def save(self, markdown: str, **kwargs: object) -> object:
        if not self._inside_save_result:
            self.save_calls.append("save")
        return super().save(markdown, **kwargs)

    def save_result(self, result: object, **kwargs: object) -> object:
        self.save_result_calls.append(result)
        self._inside_save_result = True
        try:
            return LensReportStore.save_result(self, result, **kwargs)
        finally:
            self._inside_save_result = False


class EngineHarness:
    """Real engine plus recording dependencies for Task 8 tests."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = invented_root(tmp_path)
        self.consent_authority = LocalScopeConsentAuthority(now=lambda: NOW)
        self.collector = RecordingCollector(real_session_fingerprint())
        self.catalogue_loader = RecordingCatalogueLoader(
            VerifiedCatalogueSlice(
                version=1,
                sha256="b" * 64,
                catalogue_ids=(CATALOGUE_ID,),
                capability_ids=(CAPABILITY_ID,),
                unavailable_ids=(),
                family_contract_present=False,
            )
        )
        self.comparer = RecordingComparer(_tiny_ledger())
        self.report_store = RecordingReportStore(tmp_path / "reports")
        self.run_store = DiagnosisRunStore(tmp_path / "state" / "diagnosis-runs")
        self.engine = DeterministicDiagnosisEngine(
            run_store=self.run_store,
            consent_authority=self.consent_authority,
            collector=self.collector,
            catalogue_loader=self.catalogue_loader,
            comparer=self.comparer,
            report_store=self.report_store,
            clock=lambda: NOW,
        )
        self._before: DiagnosisCheckpoint | None = None

    def prepare(self, request: PrepareDiagnosisRequest) -> object:
        return self.engine.prepare(request)

    def status(self, run_id: str) -> object:
        return self.engine.status(run_id)

    def advance(self, run_id: str) -> object:
        try:
            self._before = self.run_store.load(run_id)
        except DiagnosisStateError:
            self._before = None
        return self.engine.advance(run_id)

    def submit(self, run_id: str, proposal: object) -> object:
        return self.engine.submit(run_id, proposal)

    def result(self, run_id: str) -> object:
        return self.engine.result(run_id)

    def rewind_last_advance(self) -> None:
        if self._before is None:
            raise RuntimeError("no checkpoint to rewind")
        self.run_store.save(self._before)

    def approve(self, run_id: str) -> ApprovedScopeReceipt:
        return self.consent_authority.approve_from_local_session(
            run_id=run_id,
            scope_snapshot=approved_scope_snapshot(),
            authenticated_session_id="local-session",
        )

    def run_to(self, run_id: str, stage: DiagnosisStage) -> object:
        view = self.status(run_id)
        while view.stage is not stage:
            if view.stage is DiagnosisStage.CREATED:
                self.approve(run_id)
            view = self.advance(run_id)
        return view


def prepare_request(
    *, mode: AnalysisMode = AnalysisMode.INVENTORY_ONLY
) -> PrepareDiagnosisRequest:
    assert _ROOT is not None
    return PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=mode)


def approved_scope_snapshot() -> ScopeSnapshot:
    assert _ROOT is not None
    return capture_scope(_ROOT)


@pytest.fixture
def engine(tmp_path: Path) -> EngineHarness:
    global _ROOT
    harness = EngineHarness(tmp_path)
    _ROOT = harness.root
    try:
        yield harness
    finally:
        _ROOT = None


def test_engine_exposes_the_consent_authority_adapters_may_attach(
    engine: EngineHarness,
) -> None:
    assert engine.engine.consent_authority is engine.consent_authority


def test_advance_is_idempotent_for_same_checkpoint(engine: EngineHarness) -> None:
    prepared = engine.prepare(prepare_request())
    engine.consent_authority.approve_from_local_session(
        run_id=prepared.run_id,
        scope_snapshot=approved_scope_snapshot(),
        authenticated_session_id="local-session",
    )
    first = engine.advance(prepared.run_id)
    engine.rewind_last_advance()
    repeated = engine.advance(prepared.run_id)
    assert repeated == first


def test_result_is_unavailable_before_close(engine: EngineHarness) -> None:
    run = engine.prepare(prepare_request())
    with pytest.raises(DiagnosisStateError, match="not closed"):
        engine.result(run.run_id)


def test_advance_cannot_read_before_local_scope_approval(engine: EngineHarness) -> None:
    run = engine.prepare(prepare_request())
    with pytest.raises(DiagnosisStateError, match="approve the exact scope"):
        engine.advance(run.run_id)


def test_prepare_does_not_call_collector_or_scope_snapshot(
    engine: EngineHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[object] = []
    original = ScopeSnapshot.capture

    def forbidden(*args: object, **kwargs: object) -> ScopeSnapshot:
        captured.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(ScopeSnapshot, "capture", forbidden)
    view = engine.prepare(prepare_request())

    assert view.stage is DiagnosisStage.CREATED
    assert view.next_action == NEXT_ACTION[DiagnosisStage.CREATED]
    assert engine.collector.calls == []
    assert captured == []
    assert engine.catalogue_loader.calls == []
    assert engine.comparer.calls == []
    assert engine.report_store.save_result_calls == []


def test_prepare_accepts_string_or_path_roots(engine: EngineHarness) -> None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class StringRoots:
        roots: tuple[str, ...]

    view = engine.prepare(StringRoots(roots=(str(engine.root),)))
    assert view.stage is DiagnosisStage.CREATED
    assert engine.collector.calls == []
    persisted = engine.run_store.load_candidate_scope(view.run_id)
    assert persisted is not None
    assert persisted.analysis_mode is AnalysisMode.INVENTORY_ONLY


def test_each_stage_calls_exactly_its_lawful_dependency(engine: EngineHarness) -> None:
    prepared = engine.prepare(prepare_request())
    run_id = prepared.run_id
    engine.approve(run_id)

    approved = engine.advance(run_id)
    assert approved.stage is DiagnosisStage.SCOPE_APPROVED
    assert engine.collector.calls == []
    assert engine.catalogue_loader.calls == []
    assert engine.comparer.calls == []
    assert engine.report_store.save_result_calls == []

    captured = engine.advance(run_id)
    assert captured.stage is DiagnosisStage.CAPTURED
    assert len(engine.collector.calls) == 1
    assert engine.collector.calls[0].run_id == run_id
    assert engine.catalogue_loader.calls == []
    assert engine.comparer.calls == []

    verified = engine.advance(run_id)
    assert verified.stage is DiagnosisStage.CATALOGUE_VERIFIED
    assert len(engine.collector.calls) == 1
    assert len(engine.catalogue_loader.calls) == 1
    assert engine.comparer.calls == []

    jobs = engine.advance(run_id)
    assert jobs.stage is DiagnosisStage.JOBS_CONFIRMED
    assert len(engine.catalogue_loader.calls) == 1
    assert engine.comparer.calls == []

    compared = engine.advance(run_id)
    assert compared.stage is DiagnosisStage.COMPARED
    assert len(engine.comparer.calls) == 1
    assert engine.report_store.save_result_calls == []

    rendered = engine.advance(run_id)
    assert rendered.stage is DiagnosisStage.RENDERED
    assert len(engine.comparer.calls) == 1
    assert engine.report_store.save_result_calls == []

    checked = engine.advance(run_id)
    assert checked.stage is DiagnosisStage.CHECKED
    assert engine.report_store.save_result_calls == []

    saved = engine.advance(run_id)
    assert saved.stage is DiagnosisStage.SAVED
    assert len(engine.report_store.save_result_calls) == 1
    assert engine.report_store.save_calls == []

    closed = engine.advance(run_id)
    assert closed.stage is DiagnosisStage.CLOSED
    assert len(engine.report_store.save_result_calls) == 1
    assert engine.report_store.save_calls == []


def test_failed_reconciliation_never_reaches_saved(
    engine: EngineHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = engine.prepare(prepare_request())
    engine.run_to(prepared.run_id, DiagnosisStage.RENDERED)
    monkeypatch.setattr(
        "capability_exchange.diagnosis.orchestrator.canonical_fact_block",
        lambda _ledger: "- Ledger digest: sha256:" + "0" * 64 + "\n",
    )

    with pytest.raises(DiagnosisStateError, match="ledger-derived facts"):
        engine.advance(prepared.run_id)

    assert engine.status(prepared.run_id).stage is DiagnosisStage.RENDERED
    assert engine.report_store.save_result_calls == []


def test_closed_exposes_no_mutation_port(engine: EngineHarness) -> None:
    prepared = engine.prepare(prepare_request())
    engine.run_to(prepared.run_id, DiagnosisStage.CLOSED)

    with pytest.raises(DiagnosisStateError, match="closed"):
        engine.advance(prepared.run_id)
    with pytest.raises(DiagnosisStateError, match="closed"):
        engine.submit(prepared.run_id, {"role": "tools-and-integrations"})


def test_submit_validates_via_task_7_and_cannot_alter_evidence(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(prepare_request())
    engine.run_to(prepared.run_id, DiagnosisStage.CATALOGUE_VERIFIED)
    before = engine.status(prepared.run_id)
    fingerprint = engine.collector.fingerprint
    digest = fingerprint_digest_for(fingerprint)
    token = mint_evidence_token(
        run_id=prepared.run_id,
        fingerprint_digest=digest,
        observation_key=(
            f"{fingerprint.observations[0].kind.value}:"
            f"{fingerprint.observations[0].identity}:"
            f"{fingerprint.observations[0].provenance.source_id}"
        ),
    )
    proposal = SpecialistProposal(
        role=SpecialistRole.TOOLS_AND_INTEGRATIONS,
        kind=ProposalKind.MAPPING,
        run_id=prepared.run_id,
        fingerprint_digest=digest,
        catalogue_digest="sha256:" + "b" * 64,
        catalogue_id=CATALOGUE_ID,
        capability_id=CAPABILITY_ID,
        disposition=Disposition.NOT_ASSESSED,
        evidence_ids=(token,),
        reason="Invented mapping cites only engine-owned evidence.",
    )

    accepted = engine.submit(prepared.run_id, proposal)
    assert accepted.stage is before.stage
    assert accepted.input_identity == before.input_identity
    assert fingerprint_digest_for(engine.collector.fingerprint) == digest
    assert engine.collector.calls  # capture already happened
    collector_calls_before = list(engine.collector.calls)

    with pytest.raises(SpecialistProposalError, match="current fingerprint"):
        engine.submit(
            prepared.run_id,
            proposal.model_copy(update={"evidence_ids": ("foreign:evidence",)}),
        )
    assert fingerprint_digest_for(engine.collector.fingerprint) == digest
    assert engine.collector.calls == collector_calls_before


def test_guided_run_refuses_legacy_submit_before_input_is_materialised(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.CATALOGUE_VERIFIED)
    persisted = engine.run_store.load_candidate_scope(prepared.run_id)
    assert persisted is not None
    assert persisted.analysis_mode is AnalysisMode.GUIDED

    with pytest.raises(DiagnosisStateError, match="submit_work"):
        engine.submit(prepared.run_id, {})

    checkpoint = engine.run_store.load(prepared.run_id)
    assert engine.engine._proposal_payloads(checkpoint) == []  # noqa: SLF001


def test_save_consumes_report_model_via_save_result(engine: EngineHarness) -> None:
    prepared = engine.prepare(prepare_request())
    engine.run_to(prepared.run_id, DiagnosisStage.SAVED)
    result = engine.report_store.save_result_calls[0]
    assert hasattr(result, "report")
    assert isinstance(result.report, ReportModel)
    markdown = result.render_markdown()
    assert canonical_fact_block(result.ledger) in markdown
    saved = engine.report_store.last()
    assert saved is not None
    assert saved.ledger_path.is_file()
    assert saved.path.with_suffix(".result.json").is_file()
    assert engine.report_store.save_calls == []


def test_result_after_close_can_render_canonical_markdown(engine: EngineHarness) -> None:
    prepared = engine.prepare(prepare_request())
    engine.run_to(prepared.run_id, DiagnosisStage.CLOSED)
    result = engine.result(prepared.run_id)
    payload = result.dump_for_storage()
    assert payload["run_id"] == prepared.run_id
    assert payload["stage"] == DiagnosisStage.CLOSED.value
    markdown = result.render_markdown()
    assert canonical_fact_block(result.ledger) in markdown
    saved = engine.report_store.last()
    assert saved is not None
    assert f"- Report location: `{saved.path}`." in markdown
    assert "not been saved" not in markdown


def test_report_carries_collection_limits_from_the_bound_fingerprint(
    engine: EngineHarness,
) -> None:
    engine.collector.fingerprint = engine.collector.fingerprint.model_copy(
        update={"limits": ("Collection stopped at the approved safe-file bound.",)}
    )
    prepared = engine.prepare(prepare_request())
    engine.run_to(prepared.run_id, DiagnosisStage.CLOSED)

    markdown = engine.result(prepared.run_id).render_markdown()

    assert "- Collection stopped at the approved safe-file bound." in markdown


def test_orchestrator_does_not_import_follow_on_surfaces() -> None:
    source = Path("src/capability_exchange/diagnosis/orchestrator.py").read_text(
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


def test_engine_exports_without_follow_on_surfaces() -> None:
    from capability_exchange.diagnosis import DeterministicDiagnosisEngine as exported

    assert exported is DeterministicDiagnosisEngine


def test_catalogue_slice_does_not_invent_held_availability() -> None:
    slice_ = VerifiedCatalogueSlice(
        version=1,
        sha256="b" * 64,
        catalogue_ids=(CATALOGUE_ID, "parked-capability"),
        capability_ids=(CAPABILITY_ID,),
        unavailable_ids=("parked-capability",),
        family_contract_present=False,
    )
    assert "held" not in json.dumps(slice_.__dict__)
    assert slice_.unavailable_ids == ("parked-capability",)


def test_guided_run_refuses_comparison_until_work_is_reconciled(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.JOBS_CONFIRMED)

    planned = engine.advance(prepared.run_id)
    assert planned.stage is DiagnosisStage.ANALYSIS_PLANNED
    with pytest.raises(DiagnosisStateError, match="specialist work remains"):
        engine.advance(prepared.run_id)


def test_guided_work_packet_is_stable_across_engine_reopen(engine: EngineHarness) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    first = engine.engine.work(prepared.run_id)
    assert first is not None

    reopened = DeterministicDiagnosisEngine(
        run_store=engine.run_store,
        consent_authority=engine.consent_authority,
        collector=engine.collector,
        catalogue_loader=engine.catalogue_loader,
        comparer=engine.comparer,
        report_store=engine.report_store,
        clock=lambda: NOW,
    )

    assert reopened.work(prepared.run_id) == first


def test_guided_work_validation_failure_is_bounded_and_recorded(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    packet = engine.engine.work(prepared.run_id)
    assert packet is not None

    with pytest.raises(SpecialistProposalError, match="one retry remains"):
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ({},))
    first_queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    assert first_queue.receipts[0].status is WorkStatus.PENDING
    assert first_queue.receipts[0].attempt_count == 1
    assert engine.engine.work(prepared.run_id) == packet

    with pytest.raises(SpecialistProposalError, match="unresolved"):
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ({},))
    second_queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    history = tuple(item for item in second_queue.receipts if item.packet_id == packet.packet_id)
    assert [item.status for item in history] == [WorkStatus.PENDING, WorkStatus.UNRESOLVED]
    assert [item.attempt_count for item in history] == [1, 2]


def test_guided_work_does_not_turn_stored_context_failure_into_a_retry(
    engine: EngineHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    packet = engine.engine.work(prepared.run_id)
    assert packet is not None

    def invalid_context(*args: object, **kwargs: object) -> object:
        raise DiagnosisStateError("stored specialist context is invalid")

    monkeypatch.setattr(engine.engine, "_proposal_context_for_packet", invalid_context)
    with pytest.raises(DiagnosisStateError, match="stored specialist context"):
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    assert queue.receipts == ()


def test_guided_normal_and_sceptical_proposals_reconcile_from_stored_work(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    normal = engine.engine.work(prepared.run_id)
    assert normal is not None
    proposal = SpecialistProposal(
        role=normal.role,
        kind=ProposalKind.STRENGTH,
        run_id=normal.run_id,
        fingerprint_digest=normal.fingerprint_digest,
        catalogue_digest=normal.catalogue_digest,
        packet_id=normal.packet_id,
        packet_digest=normal.packet_digest,
        catalogue_id=normal.catalogue_ids[0],
        capability_id=normal.capability_ids[0],
        candidate_id=candidate_id_for(
            ProposalKind.STRENGTH,
            normal.catalogue_ids[0],
            normal.capability_ids[0],
        ),
        disposition=Disposition.STRONG_HERE,
        evidence_ids=(normal.evidence_ids[0],),
        observation_ids=(normal.observation_ids[0],),
        reason="The approved evidence shows a distinctive reliable method.",
    )
    engine.engine.submit_work(prepared.run_id, normal.packet_id, (proposal,))
    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role.value == "sceptical-reconciler":
            sceptical = packet
            break
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())
    downgrade = proposal.model_copy(
        update={
            "role": sceptical.role,
            "packet_id": sceptical.packet_id,
            "packet_digest": sceptical.packet_digest,
            "disposition": Disposition.FRAGILE_OR_CONTRADICTORY,
            "reason": "The evidence is real but the method has a material contradiction.",
        }
    )
    engine.engine.submit_work(prepared.run_id, sceptical.packet_id, (downgrade,))

    completed = engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    compared = engine.advance(prepared.run_id)
    assert compared.stage is DiagnosisStage.COMPARED
    assert (
        engine.comparer.calls[-1]["proposals"][0].disposition
        is Disposition.FRAGILE_OR_CONTRADICTORY
    )
