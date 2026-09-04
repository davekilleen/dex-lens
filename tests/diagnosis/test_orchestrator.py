"""Deterministic diagnosis engine owns stage transitions and typed save."""

from __future__ import annotations

import ast
import fcntl
import json
import os
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
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    SafeAttribute,
)
from capability_exchange.diagnosis.orchestrator import (
    MAX_FACTOR_TUPLES_PER_CANDIDATE,
    DeterministicDiagnosisEngine,
    PrepareDiagnosisRequest,
    VerifiedCatalogueSlice,
    fingerprint_digest_for,
)
from capability_exchange.diagnosis.ranking import RecommendationFactors
from capability_exchange.diagnosis.report import ReportModel, canonical_fact_block
from capability_exchange.diagnosis.run import (
    NEXT_ACTION,
    ApprovedScopeReceipt,
    DiagnosisCheckpoint,
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.run_store import DiagnosisRunConflict, DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    ValidatedProposal,
    candidate_id_for,
    mint_evidence_token,
)
from capability_exchange.diagnosis.work import (
    NORMAL_ROLES,
    AnalysisMode,
    WorkPacket,
    WorkQueueError,
    WorkStatus,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState
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
        work_audit: object | None = None,
    ) -> ComparisonLedger:
        self.calls.append(
            {
                "fingerprint": fingerprint,
                "catalogue": catalogue,
                "jobs": jobs,
                "proposals": proposals,
                "work_audit": work_audit,
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


def test_capture_accepts_lawful_nested_relative_references(engine: EngineHarness) -> None:
    """Finding B3: an ordinary vault must never wedge at capture.

    A vault containing a folder named ``private``, ``home`` or ``Users`` below
    its root produces relative references such as ``notes/private/journal.md``
    — accepted by provenance validation and emitted verbatim by the snapshot
    adapter. The capture guard refuses absolute-path SHAPE, so these lawful
    references must reach the CAPTURED stage instead of being refused as
    hostile content forever.
    """

    base = real_session_fingerprint()
    nested_references = (
        "notes/private/journal.md",
        "dotfiles/home/config.md",
        "sync/Users/list.md",
    )
    observations = list(base.observations)
    for index, reference in enumerate(nested_references):
        observations.append(
            Observation(
                kind=ObservationKind.SKILL,
                identity=f"invented-nested-{index:03d}",
                label=f"Invented nested folder method {index:03d}",
                operational_state=OperationalState.IMPLEMENTED,
                evidence=EvidenceItem(
                    state=EvidenceState.OBSERVED,
                    captured_at=NOW,
                    reference=f"file-token:invented-nested-{index:03d}.md",
                ),
                provenance={
                    "source_id": f"scope:invented-nested-{index:03d}",
                    "source_class": "vault-authored",
                    "scope_reference": "scope:sha256:" + "b" * 64,
                    "relative_reference": reference,
                },
                attributes=(SafeAttribute(key="source-kind", value="vault-authored"),),
            )
        )
    engine.collector.fingerprint = base.model_copy(
        update={"observations": tuple(observations)}
    )

    prepared = engine.prepare(prepare_request())
    view = engine.run_to(prepared.run_id, DiagnosisStage.CAPTURED)

    assert view.stage is DiagnosisStage.CAPTURED
    assert len(engine.collector.calls) == 1


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


def test_guided_run_fails_closed_when_candidate_sidecar_is_missing(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.CATALOGUE_VERIFIED)
    candidate_path = engine.run_store._candidate_path_for(prepared.run_id)  # noqa: SLF001
    assert candidate_path.is_file()
    candidate_path.unlink()

    with pytest.raises(DiagnosisStateError, match="candidate scope"):
        engine.advance(prepared.run_id)
    with pytest.raises(DiagnosisStateError, match="candidate scope"):
        engine.submit(prepared.run_id, {})


def test_guided_run_fails_closed_when_candidate_sidecar_mode_is_tampered(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.CATALOGUE_VERIFIED)
    candidate_path = engine.run_store._candidate_path_for(prepared.run_id)  # noqa: SLF001
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["analysis_mode"] = AnalysisMode.INVENTORY_ONLY.value
    candidate_path.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(DiagnosisStateError, match="analysis mode"):
        engine.advance(prepared.run_id)


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


def test_result_after_close_can_render_canonical_markdown(
    engine: EngineHarness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The closed result names its exact saved destination, home-relative.

    Finding A2 evolved this test: it previously asserted the footer carried
    the saved ABSOLUTE path verbatim (the store lives outside home in this
    harness), which is the leak the footer contract now forbids. The invented
    home below puts the store under home, so the footer still binds to the
    exact saved file — rendered relative, never absolute.
    """

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
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
    relative = "~/" + saved.path.relative_to(tmp_path).as_posix()
    assert f"- Report location: `{relative}`." in markdown
    assert str(saved.path) not in markdown
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


def test_work_context_legend_matches_the_issued_packet_tokens(
    engine: EngineHarness,
) -> None:
    """Every citable packet token gets one legend row drawn from the fingerprint."""

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    packet = engine.engine.work(prepared.run_id)
    assert packet is not None

    legend = engine.engine.work_context(prepared.run_id)

    fingerprint = engine.collector.fingerprint
    assert len(legend) == len(fingerprint.observations)
    assert tuple(row.evidence_id for row in legend) == packet.evidence_ids
    rows_by_observation = {row.observation_id: row for row in legend}
    for observation in fingerprint.observations:
        row = rows_by_observation[observation.observation_id]
        assert row.kind is observation.kind
        assert row.identity == observation.identity
        assert row.label == observation.label
        assert row.relative_reference == observation.provenance.relative_reference
        assert row.source_class is observation.provenance.source_class


def test_pending_work_lists_every_pending_normal_packet(engine: EngineHarness) -> None:
    """One fetch returns the whole legal round, not just the first packet."""

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)

    packets = engine.engine.pending_work(prepared.run_id)

    assert tuple(item.role for item in packets) == NORMAL_ROLES
    assert engine.engine.work(prepared.run_id) == packets[0]


def test_pending_work_is_empty_for_inventory_only_runs(engine: EngineHarness) -> None:
    prepared = engine.prepare(prepare_request())
    engine.run_to(prepared.run_id, DiagnosisStage.JOBS_CONFIRMED)
    assert engine.engine.pending_work(prepared.run_id) == ()


def test_pending_work_keeps_sceptical_locked_until_normals_are_final(
    engine: EngineHarness,
) -> None:
    """The sceptical packet never joins the list while a normal packet is open."""

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    packets = engine.engine.pending_work(prepared.run_id)
    assert len(packets) == len(NORMAL_ROLES)

    for index, packet in enumerate(packets[:-1]):
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())
        remaining = engine.engine.pending_work(prepared.run_id)
        assert remaining == packets[index + 1 :]
        assert all(
            item.role is not SpecialistRole.SCEPTICAL_RECONCILER for item in remaining
        )

    engine.engine.submit_work(prepared.run_id, packets[-1].packet_id, ())
    unlocked = engine.engine.pending_work(prepared.run_id)
    assert len(unlocked) == 1
    assert unlocked[0].role is SpecialistRole.SCEPTICAL_RECONCILER

    engine.engine.submit_work(prepared.run_id, unlocked[0].packet_id, ())
    assert engine.engine.pending_work(prepared.run_id) == ()


def test_issued_packets_accept_out_of_order_interleaved_submission(
    engine: EngineHarness,
) -> None:
    """Responses for one issued round may return in any order.

    Tripwire, not a guard demonstration: ``submit_work`` already matched
    packets by identity rather than queue position, so this behaviour was
    observed green before any change. It pins the property that makes
    parallel fan-out legal — a host may submit whichever specialist
    finishes first.
    """

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    packets = engine.engine.pending_work(prepared.run_id)
    assert len(packets) == len(NORMAL_ROLES)

    interleaved = (3, 0, 7, 2, 5, 1, 6, 4)
    assert sorted(interleaved) == list(range(len(packets)))
    for position, index in enumerate(interleaved):
        packet = packets[index]
        proposals: tuple[SpecialistProposal, ...] = ()
        if position == 2:
            proposals = (
                _bound_proposal(
                    packet,
                    kind=ProposalKind.STRENGTH,
                    catalogue_id=CATALOGUE_ID,
                    capability_id=CAPABILITY_ID,
                    disposition=Disposition.STRONG_HERE,
                    evidence_ids=(packet.evidence_ids[0],),
                    reason="The approved evidence shows a distinctive reliable method.",
                ),
            )
        view = engine.engine.submit_work(prepared.run_id, packet.packet_id, proposals)
        assert view.stage is DiagnosisStage.ANALYSIS_PLANNED

    unlocked = engine.engine.pending_work(prepared.run_id)
    assert tuple(item.role for item in unlocked) == (SpecialistRole.SCEPTICAL_RECONCILER,)


def test_work_context_is_refused_before_analysis_planning(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.JOBS_CONFIRMED)
    with pytest.raises(DiagnosisStateError, match="analysis planning"):
        engine.engine.work_context(prepared.run_id)


def test_work_context_is_empty_for_inventory_only_runs(engine: EngineHarness) -> None:
    prepared = engine.prepare(prepare_request())
    engine.run_to(prepared.run_id, DiagnosisStage.JOBS_CONFIRMED)
    assert engine.engine.work_context(prepared.run_id) == ()


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


def test_guided_work_fails_closed_for_tampered_stored_diagnosis_input(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    packet = engine.engine.work(prepared.run_id)
    assert packet is not None
    checkpoint = engine.run_store.load(prepared.run_id)
    payload = engine.engine._find_kind(checkpoint, "diagnosis-input")  # noqa: SLF001
    assert isinstance(payload, dict)
    tampered = dict(payload)
    tampered["analysis_mode"] = AnalysisMode.INVENTORY_ONLY.value
    replacement = engine.engine._put("diagnosis-input", tampered)  # noqa: SLF001
    kept = tuple(
        digest
        for digest in checkpoint.artifact_digests
        if engine.engine._get(digest).get("kind") != "diagnosis-input"  # noqa: SLF001
    )
    engine.run_store.save(
        checkpoint.model_copy(update={"artifact_digests": (*kept, replacement)})
    )

    with pytest.raises(DiagnosisStateError, match="identity"):
        engine.engine.work(prepared.run_id)
    with pytest.raises(DiagnosisStateError, match="identity"):
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


def test_disputed_guided_recommendation_keeps_sceptical_work_resumable(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    first = engine.engine.work(prepared.run_id)
    assert first is not None

    candidate_id = candidate_id_for(
        ProposalKind.RECOMMENDATION,
        CATALOGUE_ID,
        CAPABILITY_ID,
    )
    evidence_id = first.evidence_ids[0]
    observation_id = first.observation_ids[0]
    factors_a = RecommendationFactors(
        reliability_risk=1,
        job_relevance=2,
        workflow_leverage=2,
        evidence_strength=2,
        adoption_effort=2,
    )
    factors_b = factors_a.model_copy(update={"job_relevance": 3})

    def recommendation_for(packet: object, factors: RecommendationFactors) -> SpecialistProposal:
        return SpecialistProposal(
            role=packet.role,
            kind=ProposalKind.RECOMMENDATION,
            run_id=packet.run_id,
            fingerprint_digest=packet.fingerprint_digest,
            catalogue_digest=packet.catalogue_digest,
            packet_id=packet.packet_id,
            packet_digest=packet.packet_digest,
            catalogue_id=CATALOGUE_ID,
            capability_id=CAPABILITY_ID,
            candidate_id=candidate_id,
            disposition=Disposition.WORTH_BORROWING,
            recommendation_factors=factors,
            evidence_ids=(evidence_id,),
            observation_ids=(observation_id,),
            reason="The approved evidence supports this bounded Dex addition.",
        )

    engine.engine.submit_work(
        prepared.run_id,
        first.packet_id,
        (recommendation_for(first, factors_a),),
    )
    second = engine.engine.work(prepared.run_id)
    assert second is not None
    engine.engine.submit_work(
        prepared.run_id,
        second.packet_id,
        (recommendation_for(second, factors_b),),
    )
    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            sceptical = packet
            break
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    engine.engine.submit_work(prepared.run_id, sceptical.packet_id, ())
    completed = engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED

    engine.advance(prepared.run_id)
    disputed = next(
        item
        for item in engine.comparer.calls[-1]["proposals"]
        if item.candidate_id == candidate_id
    )
    assert disputed.disposition is Disposition.NOT_ASSESSED
    assert disputed.recommendation_factors is None
    # Evolved from the fixed DISAGREEMENT_REASON: an unadjudicated factor
    # dispute now names the agreed disposition and the disagreeing factors.
    assert disputed.reason == (
        "Specialist proposals agreed on worth-borrowing but disagreed on "
        "recommendation factors; the sceptical review did not adjudicate, so "
        "the comparison remains Unknown."
    )


def _drive_disputed_strength_run(engine: EngineHarness) -> tuple[str, WorkPacket, str]:
    """Real guided run where two normal packets disagree on one candidate.

    Packet one claims ``strong-here``; packet two claims
    ``fragile-or-contradictory`` for the same STRENGTH candidate.  Returns the
    run, the issued sceptical packet, and the disputed candidate identity.
    """

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    candidate_id = candidate_id_for(ProposalKind.STRENGTH, CATALOGUE_ID, CAPABILITY_ID)

    first = engine.engine.work(prepared.run_id)
    assert first is not None
    engine.engine.submit_work(
        prepared.run_id,
        first.packet_id,
        (
            _bound_proposal(
                first,
                kind=ProposalKind.STRENGTH,
                catalogue_id=CATALOGUE_ID,
                capability_id=CAPABILITY_ID,
                disposition=Disposition.STRONG_HERE,
                evidence_ids=(first.evidence_ids[0],),
                reason="The approved evidence shows a distinctive reliable method.",
            ),
        ),
    )
    second = engine.engine.work(prepared.run_id)
    assert second is not None
    engine.engine.submit_work(
        prepared.run_id,
        second.packet_id,
        (
            _bound_proposal(
                second,
                kind=ProposalKind.STRENGTH,
                catalogue_id=CATALOGUE_ID,
                capability_id=CAPABILITY_ID,
                disposition=Disposition.FRAGILE_OR_CONTRADICTORY,
                evidence_ids=(second.evidence_ids[0],),
                reason="The same approved evidence shows a material contradiction.",
            ),
        ),
    )
    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            return prepared.run_id, packet, candidate_id
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())


def test_disputed_candidate_reaches_the_sceptical_packet_as_a_disputed_baseline(
    engine: EngineHarness,
) -> None:
    """Two specialists agreeing a capability matters, differing on degree, is
    signal: the disputed candidate must reach the sceptical review as a
    baseline that carries the fact of the dispute and the proposed set.
    """

    run_id, sceptical, candidate_id = _drive_disputed_strength_run(engine)

    checkpoint = engine.run_store.load(run_id)
    queue = engine.engine._work_queue(checkpoint)  # noqa: SLF001
    packet = next(item for item in queue.packets if item.packet_id == sceptical.packet_id)
    context = engine.engine._proposal_context_for_packet(  # noqa: SLF001
        checkpoint, packet, queue
    )

    baseline = next(
        (item for item in context.accepted_candidates if item.candidate_id == candidate_id),
        None,
    )
    assert baseline is not None, "disputed candidate never reached the sceptical packet"
    assert baseline.original_disposition is Disposition.NOT_ASSESSED
    assert baseline.disputed_dispositions == (
        Disposition.FRAGILE_OR_CONTRADICTORY,
        Disposition.STRONG_HERE,
    )
    assert baseline.disputed_recommendation_factors == ()


def test_sceptical_review_adjudicates_a_dispute_only_to_a_proposed_disposition(
    engine: EngineHarness,
) -> None:
    run_id, sceptical, candidate_id = _drive_disputed_strength_run(engine)

    def sceptical_resolution(disposition: Disposition, reason: str) -> SpecialistProposal:
        return _bound_proposal(
            sceptical,
            kind=ProposalKind.STRENGTH,
            catalogue_id=CATALOGUE_ID,
            capability_id=CAPABILITY_ID,
            disposition=disposition,
            evidence_ids=(sceptical.evidence_ids[0],),
            reason=reason,
        )

    # `shared` was never proposed for this candidate: adjudication may select
    # only a proposed disposition or the ordinary downgrades, so the invented
    # position is refused and burns the bounded attempt.
    with pytest.raises(SpecialistProposalError, match="one retry remains"):
        engine.engine.submit_work(
            run_id,
            sceptical.packet_id,
            (
                sceptical_resolution(
                    Disposition.SHARED,
                    "An adjudication position nobody proposed must be refused.",
                ),
            ),
        )

    engine.engine.submit_work(
        run_id,
        sceptical.packet_id,
        (
            sceptical_resolution(
                Disposition.STRONG_HERE,
                "The contradiction claim does not survive the approved evidence.",
            ),
        ),
    )

    completed = engine.advance(run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    compared = engine.advance(run_id)
    assert compared.stage is DiagnosisStage.COMPARED
    adjudicated = next(
        item
        for item in engine.comparer.calls[-1]["proposals"]
        if item.candidate_id == candidate_id
    )
    assert adjudicated.disposition is Disposition.STRONG_HERE
    assert adjudicated.reason == (
        "The contradiction claim does not survive the approved evidence."
    )

    closed = engine.run_to(run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED


def test_sceptical_review_resolves_a_factor_dispute_to_one_proposed_tuple(
    engine: EngineHarness,
) -> None:
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    candidate_id = candidate_id_for(
        ProposalKind.RECOMMENDATION, CATALOGUE_ID, CAPABILITY_ID
    )
    factors_a = _RECOMMENDATION_FACTORS
    factors_b = factors_a.model_copy(update={"job_relevance": 3})

    def recommendation_for(
        packet: WorkPacket, factors: RecommendationFactors
    ) -> SpecialistProposal:
        return _bound_proposal(
            packet,
            kind=ProposalKind.RECOMMENDATION,
            catalogue_id=CATALOGUE_ID,
            capability_id=CAPABILITY_ID,
            disposition=Disposition.WORTH_BORROWING,
            evidence_ids=(packet.evidence_ids[0],),
            reason="The approved evidence supports this bounded Dex addition.",
            recommendation_factors=factors,
        )

    first = engine.engine.work(prepared.run_id)
    assert first is not None
    engine.engine.submit_work(
        prepared.run_id, first.packet_id, (recommendation_for(first, factors_a),)
    )
    second = engine.engine.work(prepared.run_id)
    assert second is not None
    engine.engine.submit_work(
        prepared.run_id, second.packet_id, (recommendation_for(second, factors_b),)
    )
    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            sceptical = packet
            break
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    # A factor tuple nobody proposed is refused; one of the proposed tuples,
    # with evidence, adjudicates the dispute.
    invented = factors_a.model_copy(update={"workflow_leverage": 3})
    with pytest.raises(SpecialistProposalError, match="one retry remains"):
        engine.engine.submit_work(
            prepared.run_id,
            sceptical.packet_id,
            (recommendation_for(sceptical, invented),),
        )
    engine.engine.submit_work(
        prepared.run_id,
        sceptical.packet_id,
        (recommendation_for(sceptical, factors_b),),
    )

    completed = engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    engine.advance(prepared.run_id)
    adjudicated = next(
        item
        for item in engine.comparer.calls[-1]["proposals"]
        if item.candidate_id == candidate_id
    )
    assert adjudicated.disposition is Disposition.WORTH_BORROWING
    assert adjudicated.recommendation_factors == factors_b


def test_unadjudicated_dispute_names_both_dispositions_in_the_reason(
    engine: EngineHarness,
) -> None:
    run_id, sceptical, candidate_id = _drive_disputed_strength_run(engine)

    # The sceptical review answers with nothing for the disputed candidate.
    engine.engine.submit_work(run_id, sceptical.packet_id, ())
    completed = engine.advance(run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    engine.advance(run_id)

    disputed = next(
        item
        for item in engine.comparer.calls[-1]["proposals"]
        if item.candidate_id == candidate_id
    )
    assert disputed.disposition is Disposition.NOT_ASSESSED
    # FINDING A1: the dispute reaches comparison as the engine-set structural
    # flag, so the ledger assembly never has to recognise it from reason text.
    assert disputed.disputed is True
    assert disputed.reason == (
        "Specialist proposals disagreed between fragile-or-contradictory and "
        "strong-here; the sceptical review did not adjudicate, so the "
        "comparison remains Unknown."
    )


def _wedge_fingerprint(observation_count: int = 10) -> EvidenceFingerprint:
    """An invented fingerprint wide enough to mint 9+ evidence tokens."""

    observations = tuple(
        Observation(
            kind=ObservationKind.SKILL,
            identity=f"invented-wedge-method-{index:02d}",
            label=f"Invented wedge method {index:02d}",
            operational_state=OperationalState.IMPLEMENTED,
            evidence=EvidenceItem(
                state=EvidenceState.OBSERVED,
                captured_at=NOW,
                reference=f"file-token:invented-wedge-{index:02d}.md",
            ),
            provenance={
                "source_id": f"scope:invented-wedge-method-{index:02d}",
                "source_class": "vault-authored",
                "scope_reference": "scope:sha256:" + "b" * 64,
                "relative_reference": f"synthetic/invented-wedge-{index:02d}/SKILL.md",
            },
            attributes=(SafeAttribute(key="source-kind", value="vault-authored"),),
        )
        for index in range(observation_count)
    )
    return EvidenceFingerprint(
        adapter_id="invented-local-adapter",
        collected_at=NOW,
        observations=observations,
    )


def _bound_proposal(
    packet: WorkPacket,
    *,
    kind: ProposalKind,
    catalogue_id: str,
    capability_id: str,
    disposition: Disposition,
    evidence_ids: tuple[str, ...],
    reason: str,
    recommendation_factors: RecommendationFactors | None = None,
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
        capability_id=capability_id,
        candidate_id=candidate_id_for(kind, catalogue_id, capability_id),
        disposition=disposition,
        recommendation_factors=recommendation_factors,
        evidence_ids=evidence_ids,
        reason=reason,
    )


def test_guided_run_completes_when_agreeing_specialists_overflow_the_evidence_cap(
    engine: EngineHarness,
) -> None:
    """RISK-GUIDED-RUN-WEDGE, wedge 1: normal breadth must not wedge the run.

    Five specialists each cite two distinct engine-minted tokens for the same
    candidate; the coalesced union (10) exceeds MAX_EVIDENCE_IDS (8).  The run
    must still close, with the reconciled candidate citing exactly the first
    eight of the sorted union.
    """

    engine.collector.fingerprint = _wedge_fingerprint(10)
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)

    cited: list[str] = []
    for index in range(5):
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        assert packet.role is not SpecialistRole.SCEPTICAL_RECONCILER
        pair = packet.evidence_ids[2 * index : 2 * index + 2]
        engine.engine.submit_work(
            prepared.run_id,
            packet.packet_id,
            (
                _bound_proposal(
                    packet,
                    kind=ProposalKind.STRENGTH,
                    catalogue_id=CATALOGUE_ID,
                    capability_id=CAPABILITY_ID,
                    disposition=Disposition.STRONG_HERE,
                    evidence_ids=pair,
                    reason="The approved evidence shows a distinctive reliable method.",
                ),
            ),
        )
        cited.extend(pair)
    assert len(set(cited)) == 10

    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            break
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    # Before the fix this raised a raw pydantic error while building the
    # sceptical packet's context — before any receipt was recorded — and the
    # run was wedged: advance refused as incomplete and work returned the same
    # packet forever.
    engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    completed = engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    compared = engine.advance(prepared.run_id)
    assert compared.stage is DiagnosisStage.COMPARED
    candidate_id = candidate_id_for(ProposalKind.STRENGTH, CATALOGUE_ID, CAPABILITY_ID)
    reconciled = next(
        item
        for item in engine.comparer.calls[-1]["proposals"]
        if item.candidate_id == candidate_id
    )
    assert reconciled.disposition is Disposition.STRONG_HERE
    assert reconciled.evidence_ids == tuple(sorted(set(cited)))[:8]
    assert len(reconciled.evidence_ids) == 8

    closed = engine.run_to(prepared.run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED


def test_guided_run_refuses_recommendation_overflow_at_submit_and_still_closes(
    engine: EngineHarness,
) -> None:
    """RISK-GUIDED-RUN-WEDGE, wedge 2: the eleventh recommendation is refused
    where the bounded-retry protocol can reject, not accepted to wedge later.
    """

    borrow_ids = tuple(f"invented-borrow-{index:02d}" for index in range(11))
    engine.catalogue_loader.slice = VerifiedCatalogueSlice(
        version=1,
        sha256="b" * 64,
        catalogue_ids=borrow_ids,
        capability_ids=(CAPABILITY_ID,),
        unavailable_ids=(),
        family_contract_present=False,
    )
    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)

    factors = RecommendationFactors(
        reliability_risk=1,
        job_relevance=2,
        workflow_leverage=2,
        evidence_strength=2,
        adoption_effort=2,
    )

    def recommendations(
        packet: WorkPacket, catalogue_ids: tuple[str, ...]
    ) -> tuple[SpecialistProposal, ...]:
        return tuple(
            _bound_proposal(
                packet,
                kind=ProposalKind.RECOMMENDATION,
                catalogue_id=catalogue_id,
                capability_id=CAPABILITY_ID,
                disposition=Disposition.WORTH_BORROWING,
                evidence_ids=(packet.evidence_ids[0],),
                reason="The approved evidence supports this bounded Dex addition.",
                recommendation_factors=factors,
            )
            for catalogue_id in catalogue_ids
        )

    first = engine.engine.work(prepared.run_id)
    assert first is not None
    accepted_first = recommendations(first, borrow_ids[:6])
    engine.engine.submit_work(prepared.run_id, first.packet_id, accepted_first)

    second = engine.engine.work(prepared.run_id)
    assert second is not None
    # Six accepted plus five more distinct candidates is eleven: the response
    # is refused as malformed before it is recorded, burning the bounded
    # attempt as an empty rejection — instead of being accepted and wedging
    # the run at the sceptical packet.
    with pytest.raises(SpecialistProposalError, match="one retry remains") as refusal:
        engine.engine.submit_work(
            prepared.run_id, second.packet_id, recommendations(second, borrow_ids[6:11])
        )
    assert "at most 10" in str(refusal.value.__cause__)
    queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    burned = [item for item in queue.receipts if item.packet_id == second.packet_id]
    assert [item.status for item in burned] == [WorkStatus.PENDING]
    assert burned[0].proposal_count == 0

    # A retry with fewer recommendations succeeds.
    engine.engine.submit_work(
        prepared.run_id, second.packet_id, recommendations(second, borrow_ids[6:10])
    )

    # An exact replay of the first accepted response stays idempotent even
    # though the run now holds the full ten distinct recommendations.
    engine.engine.submit_work(prepared.run_id, first.packet_id, accepted_first)

    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            break
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())
    engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    completed = engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    compared = engine.advance(prepared.run_id)
    assert compared.stage is DiagnosisStage.COMPARED
    recommended = {
        item.catalogue_id
        for item in engine.comparer.calls[-1]["proposals"]
        if item.kind is ProposalKind.RECOMMENDATION
    }
    # Every accepted recommendation is present — nothing silently dropped.
    assert recommended == set(borrow_ids[:10])

    closed = engine.run_to(prepared.run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED


def _replace_stored_artifact(
    engine: EngineHarness, run_id: str, kind: str, payload: object
) -> DiagnosisCheckpoint:
    """Replace one digest-addressed artifact, as run-store tampering would."""

    checkpoint = engine.run_store.load(run_id)
    kept = tuple(
        digest
        for digest in checkpoint.artifact_digests
        if engine.engine._get(digest).get("kind") != kind  # noqa: SLF001
    )
    replacement = engine.engine._put(kind, payload)  # noqa: SLF001
    return engine.run_store.save(
        checkpoint.model_copy(update={"artifact_digests": (*kept, replacement)})
    )


_RECOMMENDATION_FACTORS = RecommendationFactors(
    reliability_risk=1,
    job_relevance=2,
    workflow_leverage=2,
    evidence_strength=2,
    adoption_effort=2,
)


def _drive_honest_guided_analysis(engine: EngineHarness) -> str:
    """Run a real guided diagnosis to ANALYSIS_COMPLETED with two proposals."""

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    first = engine.engine.work(prepared.run_id)
    assert first is not None
    engine.engine.submit_work(
        prepared.run_id,
        first.packet_id,
        (
            _bound_proposal(
                first,
                kind=ProposalKind.STRENGTH,
                catalogue_id=CATALOGUE_ID,
                capability_id=CAPABILITY_ID,
                disposition=Disposition.STRONG_HERE,
                evidence_ids=(first.evidence_ids[0],),
                reason="The approved evidence shows a distinctive reliable method.",
            ),
        ),
    )
    second = engine.engine.work(prepared.run_id)
    assert second is not None
    engine.engine.submit_work(
        prepared.run_id,
        second.packet_id,
        (
            _bound_proposal(
                second,
                kind=ProposalKind.RECOMMENDATION,
                catalogue_id=CATALOGUE_ID,
                capability_id=CAPABILITY_ID,
                disposition=Disposition.WORTH_BORROWING,
                evidence_ids=(second.evidence_ids[0],),
                reason="The approved evidence supports this bounded Dex addition.",
                recommendation_factors=_RECOMMENDATION_FACTORS,
            ),
        ),
    )
    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            break
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())
    engine.engine.submit_work(prepared.run_id, packet.packet_id, ())
    completed = engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    return prepared.run_id


def test_guided_compare_refuses_fabricated_reconciled_proposals(
    engine: EngineHarness,
) -> None:
    """RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT: compare must re-derive, not trust.

    Red first: on the unchanged tree this manipulation was accepted — the run
    compared, closed, and carried all twenty fabricated worth-borrowing
    recommendations, each citing an evidence token never minted for the run
    and double the cap of ten, into the ledger.
    """

    run_id = _drive_honest_guided_analysis(engine)
    unminted = "evidence:sha256:" + "f" * 64
    fabricated = [
        {
            "kind": ProposalKind.RECOMMENDATION.value,
            "catalogue_id": f"forged-borrow-{index:02d}",
            "capability_id": CAPABILITY_ID,
            "disposition": Disposition.WORTH_BORROWING.value,
            "recommendation_factors": _RECOMMENDATION_FACTORS.model_dump(mode="json"),
            "evidence_ids": [unminted],
            "reason": "Fabricated recommendation the receipts never produced.",
            "observation_ids": [],
        }
        for index in range(20)
    ]
    # The hole being guarded: every fabricated entry clears shape validation
    # alone, so shape validation cannot be what stands between it and the
    # ledger.
    for item in fabricated:
        ValidatedProposal.model_validate(item)
    _replace_stored_artifact(engine, run_id, "reconciled-proposals", fabricated)

    with pytest.raises(DiagnosisStateError, match="responses this run recorded"):
        engine.advance(run_id)

    # The refusal happened before comparison: nothing fabricated reached the
    # comparer and no ledger artifact was written.
    assert engine.comparer.calls == []
    checkpoint = engine.run_store.load(run_id)
    assert checkpoint.stage is DiagnosisStage.ANALYSIS_COMPLETED
    assert engine.engine._find_kind(checkpoint, "ledger") is None  # noqa: SLF001


def test_guided_compare_refuses_a_reconciled_proposals_subset(
    engine: EngineHarness,
) -> None:
    """Dropping a derived proposal from the stored artifact is refused too.

    Red first: on the unchanged tree the truncated artifact was accepted and
    the run closed having silently lost a conclusion its receipts support.
    """

    run_id = _drive_honest_guided_analysis(engine)
    checkpoint = engine.run_store.load(run_id)
    stored = engine.engine._find_kind(checkpoint, "reconciled-proposals")  # noqa: SLF001
    assert isinstance(stored, list)
    assert len(stored) == 2
    _replace_stored_artifact(engine, run_id, "reconciled-proposals", stored[:1])

    with pytest.raises(DiagnosisStateError, match="responses this run recorded"):
        engine.advance(run_id)

    assert engine.comparer.calls == []
    after = engine.run_store.load(run_id)
    assert after.stage is DiagnosisStage.ANALYSIS_COMPLETED
    assert engine.engine._find_kind(after, "ledger") is None  # noqa: SLF001


def test_honest_guided_run_closes_and_compares_exactly_the_derived_set(
    engine: EngineHarness,
) -> None:
    """The re-derivation guard never touches an honest, untampered run."""

    run_id = _drive_honest_guided_analysis(engine)
    checkpoint = engine.run_store.load(run_id)
    stored = engine.engine._find_kind(checkpoint, "reconciled-proposals")  # noqa: SLF001
    assert isinstance(stored, list)

    closed = engine.run_to(run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED
    compared = engine.comparer.calls[-1]["proposals"]
    assert [item.model_dump(mode="json") for item in compared] == stored


def _factor_tuple(index: int) -> RecommendationFactors:
    """Deterministic distinct complete factor tuples for one candidate."""

    return RecommendationFactors(
        reliability_risk=1,
        job_relevance=index % 4,
        workflow_leverage=(index // 4) % 4,
        evidence_strength=2,
        adoption_effort=2,
    )


def _same_candidate_recommendations(
    packet: WorkPacket, tuple_indexes: range
) -> tuple[SpecialistProposal, ...]:
    """Distinct-factor recommendations that all name one semantic candidate."""

    return tuple(
        _bound_proposal(
            packet,
            kind=ProposalKind.RECOMMENDATION,
            catalogue_id=CATALOGUE_ID,
            capability_id=CAPABILITY_ID,
            disposition=Disposition.WORTH_BORROWING,
            evidence_ids=(packet.evidence_ids[0],),
            reason="The approved evidence supports this bounded Dex addition.",
            recommendation_factors=_factor_tuple(index),
        )
        for index in tuple_indexes
    )


def test_guided_run_refuses_factor_tuple_overflow_at_submit_and_still_closes(
    engine: EngineHarness,
) -> None:
    """Finding B1: ten distinct same-candidate factor tuples must not wedge.

    Red first, observed on the unchanged tree: the ten-tuple response was
    ACCEPTED as a final completed receipt (proposal_count=10); the sceptical
    packet's context then raised a raw pydantic ValidationError
    (CandidateBaseline, too_long) outside the bounded-attempt block, so the
    sceptical packet could never be answered — even empty — no retry was
    consumed, advance died identically ("specialist work remains") and work
    returned the same packet forever, with no recovery port.
    """

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    first = engine.engine.work(prepared.run_id)
    assert first is not None

    # The over-cap response is refused where the bounded-retry protocol can
    # reject: it burns the attempt as an empty rejection, never as content.
    with pytest.raises(SpecialistProposalError, match="one retry remains") as refusal:
        engine.engine.submit_work(
            prepared.run_id, first.packet_id, _same_candidate_recommendations(first, range(10))
        )
    assert (
        f"at most {MAX_FACTOR_TUPLES_PER_CANDIDATE} distinct recommendation factor tuples"
        in str(refusal.value.__cause__)
    )
    queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    burned = [item for item in queue.receipts if item.packet_id == first.packet_id]
    assert [item.status for item in burned] == [WorkStatus.PENDING]
    assert burned[0].proposal_count == 0

    # Same proposal stream, retried within the cap, is accepted.
    engine.engine.submit_work(
        prepared.run_id, first.packet_id, _same_candidate_recommendations(first, range(2))
    )
    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            break
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    # Before the fix this exact call raised the raw ValidationError.
    engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    completed = engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    compared = engine.advance(prepared.run_id)
    assert compared.stage is DiagnosisStage.COMPARED
    candidate_id = candidate_id_for(
        ProposalKind.RECOMMENDATION, CATALOGUE_ID, CAPABILITY_ID
    )
    disputed = next(
        item
        for item in engine.comparer.calls[-1]["proposals"]
        if item.candidate_id == candidate_id
    )
    assert disputed.disposition is Disposition.NOT_ASSESSED
    closed = engine.run_to(prepared.run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED


def test_factor_tuple_cap_counts_across_packets_and_admits_the_exact_bound(
    engine: EngineHarness,
) -> None:
    """Finding B1, cross-packet: the cap is prospective over final receipts of
    other packets plus this response, exact replays stay idempotent, and a run
    holding exactly the cap still builds its sceptical baseline and closes —
    proving an honest run can no longer reach the reconciliation-side
    construction, which remains only as the tamper backstop.
    """

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    first = engine.engine.work(prepared.run_id)
    assert first is not None
    accepted_first = _same_candidate_recommendations(first, range(6))
    engine.engine.submit_work(prepared.run_id, first.packet_id, accepted_first)

    second = engine.engine.work(prepared.run_id)
    assert second is not None
    # Six final tuples plus four more is ten: past the baseline cap of nine.
    with pytest.raises(SpecialistProposalError, match="one retry remains") as refusal:
        engine.engine.submit_work(
            prepared.run_id,
            second.packet_id,
            _same_candidate_recommendations(second, range(6, 10)),
        )
    assert f"at most {MAX_FACTOR_TUPLES_PER_CANDIDATE}" in str(refusal.value.__cause__)

    # A retry landing exactly on the cap (6 + 3 = 9) is accepted.
    engine.engine.submit_work(
        prepared.run_id, second.packet_id, _same_candidate_recommendations(second, range(6, 9))
    )
    # An exact replay of the first accepted response stays idempotent even
    # though the candidate now holds the full nine distinct tuples.
    engine.engine.submit_work(prepared.run_id, first.packet_id, accepted_first)

    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            break
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())

    checkpoint = engine.run_store.load(prepared.run_id)
    queue = engine.engine._work_queue(checkpoint)  # noqa: SLF001
    context = engine.engine._proposal_context_for_packet(  # noqa: SLF001
        checkpoint, packet, queue
    )
    candidate_id = candidate_id_for(
        ProposalKind.RECOMMENDATION, CATALOGUE_ID, CAPABILITY_ID
    )
    baseline = next(
        item for item in context.accepted_candidates if item.candidate_id == candidate_id
    )
    assert len(baseline.disputed_recommendation_factors) == MAX_FACTOR_TUPLES_PER_CANDIDATE

    engine.engine.submit_work(prepared.run_id, packet.packet_id, ())
    closed = engine.run_to(prepared.run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED


def _sibling_engine(
    engine: EngineHarness,
) -> tuple[DeterministicDiagnosisEngine, DiagnosisRunStore]:
    """A second engine over the same storage, standing in for another process."""

    store = DiagnosisRunStore(engine.run_store.storage)
    sibling = DeterministicDiagnosisEngine(
        run_store=store,
        consent_authority=engine.consent_authority,
        collector=engine.collector,
        catalogue_loader=engine.catalogue_loader,
        comparer=engine.comparer,
        report_store=engine.report_store,
        clock=lambda: NOW,
    )
    return sibling, store


def test_concurrent_submit_work_cannot_lose_or_replace_receipts(
    engine: EngineHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding B2: an interleaved stale save must not clobber recorded work.

    Red first, observed on the unchanged tree with this exact interleave: the
    second engine's save (built on a load that predated the first engine's
    save) was accepted, packet A's completed receipt vanished, packet A became
    pending again, and the same stale save replaced packet A's final response
    with a DIFFERENT response — defeating "a changed response for the same
    packet fails closed".
    """

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    packets = engine.engine.pending_work(prepared.run_id)
    packet_a, packet_b = packets[0], packets[1]
    sibling, sibling_store = _sibling_engine(engine)

    # Deterministic interleave: the sibling's load happens BEFORE A's save.
    stale = engine.run_store.load(prepared.run_id)
    proposal_a = _bound_proposal(
        packet_a,
        kind=ProposalKind.STRENGTH,
        catalogue_id=CATALOGUE_ID,
        capability_id=CAPABILITY_ID,
        disposition=Disposition.STRONG_HERE,
        evidence_ids=(packet_a.evidence_ids[0],),
        reason="The approved evidence shows a distinctive reliable method.",
    )
    engine.engine.submit_work(prepared.run_id, packet_a.packet_id, (proposal_a,))
    queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    receipt_a = next(item for item in queue.receipts if item.packet_id == packet_a.packet_id)
    assert receipt_a.status is WorkStatus.COMPLETED

    monkeypatch.setattr(
        sibling_store,
        "load",
        lambda run_id, *, expected_input_digest=None: stale,
    )
    # The stale submission for a different packet is refused with the typed
    # retryable conflict instead of resurrecting packet A as pending.
    with pytest.raises(DiagnosisRunConflict, match="reload the run and retry"):
        sibling.submit_work(prepared.run_id, packet_b.packet_id, ())
    queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    kept = [item for item in queue.receipts if item.packet_id == packet_a.packet_id]
    assert [item.response_digest for item in kept] == [receipt_a.response_digest]
    assert packet_a.packet_id not in {
        item.packet_id for item in engine.engine.pending_work(prepared.run_id)
    }
    assert not any(item.packet_id == packet_b.packet_id for item in queue.receipts)

    # The same stale interleave cannot replace packet A's final response with
    # a DIFFERENT response either.
    different = proposal_a.model_copy(
        update={"reason": "A changed response for the same packet must fail closed."}
    )
    with pytest.raises(DiagnosisRunConflict, match="reload the run and retry"):
        sibling.submit_work(prepared.run_id, packet_a.packet_id, (different,))
    queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    kept = [item for item in queue.receipts if item.packet_id == packet_a.packet_id]
    assert [item.response_digest for item in kept] == [receipt_a.response_digest]

    # Once the sibling reloads the real head, its submission lands too: both
    # responses are durable regardless of which engine submitted first.
    monkeypatch.undo()
    sibling.submit_work(prepared.run_id, packet_b.packet_id, ())
    queue = engine.engine._work_queue(engine.run_store.load(prepared.run_id))  # noqa: SLF001
    final_ids = {
        item.packet_id
        for item in queue.receipts
        if item.status in {WorkStatus.COMPLETED, WorkStatus.INSUFFICIENT}
    }
    assert {packet_a.packet_id, packet_b.packet_id} <= final_ids

    # And through the front door, a changed response for a final packet still
    # fails closed.
    with pytest.raises(WorkQueueError, match="different response"):
        engine.engine.submit_work(prepared.run_id, packet_a.packet_id, (different,))


def test_mutations_hold_the_run_exclusive_lock_across_persist(
    engine: EngineHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """submit_work and advance persist only while holding the per-run flock."""

    prepared = engine.prepare(
        PrepareDiagnosisRequest(roots=(_ROOT,), analysis_mode=AnalysisMode.GUIDED)
    )
    engine.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    lock_path = engine.run_store._lock_path_for(prepared.run_id)  # noqa: SLF001
    probes: list[str] = []
    original_save = engine.run_store.save

    def probing_save(
        checkpoint: DiagnosisCheckpoint, **kwargs: object
    ) -> DiagnosisCheckpoint:
        handle = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(handle)
        probes.append(checkpoint.stage.value)
        return original_save(checkpoint, **kwargs)

    monkeypatch.setattr(engine.run_store, "save", probing_save)
    while True:
        packet = engine.engine.work(prepared.run_id)
        assert packet is not None
        engine.engine.submit_work(prepared.run_id, packet.packet_id, ())
        if packet.role is SpecialistRole.SCEPTICAL_RECONCILER:
            break
    completed = engine.engine.advance(prepared.run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED
    # Every packet response plus the advance persisted under the held lock.
    assert len(probes) == len(NORMAL_ROLES) + 2


def test_guided_run_refuses_legacy_submit_at_every_stage_after_compare(
    engine: EngineHarness,
) -> None:
    """Finding C1: a GUIDED run never accepts legacy submit at any stage.

    Red first, observed on the unchanged tree: from COMPARED onward the run
    accepted an unbound legacy proposal — validated against the default
    inventory-only context — and durably retained it in the run's artifacts,
    outside the submit_work protocol the earlier stages enforce.
    """

    run_id = _drive_honest_guided_analysis(engine)
    fingerprint = engine.collector.fingerprint
    digest = fingerprint_digest_for(fingerprint)
    token = mint_evidence_token(
        run_id=run_id,
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
        run_id=run_id,
        fingerprint_digest=digest,
        catalogue_digest="sha256:" + "b" * 64,
        catalogue_id=CATALOGUE_ID,
        capability_id=CAPABILITY_ID,
        disposition=Disposition.NOT_ASSESSED,
        evidence_ids=(token,),
        reason="An unbound legacy proposal must never enter a guided run.",
    )

    for stage in (
        DiagnosisStage.COMPARED,
        DiagnosisStage.RENDERED,
        DiagnosisStage.CHECKED,
        DiagnosisStage.SAVED,
    ):
        engine.run_to(run_id, stage)
        with pytest.raises(DiagnosisStateError, match="submit_work"):
            engine.submit(run_id, proposal)
        checkpoint = engine.run_store.load(run_id)
        assert engine.engine._proposal_payloads(checkpoint) == []  # noqa: SLF001

    closed = engine.run_to(run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED
