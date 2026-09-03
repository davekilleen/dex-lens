"""Golden replay of one sanitised diagnosis through every adapter.

The three runners share one ``ReplayBundle``. They may wrap a different
transport; they must not construct a different engine input.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from unittest.mock import patch

import anyio
from mcp import Client

from capability_exchange.concierge.collection import ScopeSnapshot
from capability_exchange.concierge.consent import (
    InMemoryConsentStore,
    LocalScopeConsentAuthority,
    opaque_candidate_locator,
)
from capability_exchange.diagnosis import cli as diagnosis_cli
from capability_exchange.diagnosis.comparison import ComparisonLedger
from capability_exchange.diagnosis.mcp_server import (
    build_mcp_server,
    canonical_result_bytes,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    upgrade_stored_fingerprint_payload,
)
from capability_exchange.diagnosis.orchestrator import (
    DeterministicDiagnosisEngine,
    DiagnosisResult,
    PrepareDiagnosisRequest,
    VerifiedCatalogueSlice,
)
from capability_exchange.diagnosis.receipts import DecisionState, ShareState
from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    NEXT_ACTION,
    ApprovedScopeReceipt,
    DiagnosisCheckpoint,
    DiagnosisRunView,
    DiagnosisStage,
    DiagnosisStateError,
    canonical_json_digest,
)
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.work import AnalysisMode
from capability_exchange.reports.store import LensReportStore

__all__ = [
    "FIXED_CLOCK",
    "FIXED_RUN_ID",
    "NON_TERMINAL_STAGES",
    "ReplayBundle",
    "ReplayHarness",
    "canonical_replay_bytes",
    "run_cli",
    "run_direct",
    "run_mcp",
]

FIXED_CLOCK = datetime(2026, 8, 27, tzinfo=UTC)
FIXED_RUN_ID = "run:cafef00dcafe0001"
DiscoverOrder = Literal["listed", "claude", "codex"]
NON_TERMINAL_STAGES: tuple[DiagnosisStage, ...] = tuple(
    stage for stage in DiagnosisStage if stage is not DiagnosisStage.CLOSED
)


@dataclass(frozen=True)
class ReplayBundle:
    """One sanitised engine input shared by every transport."""

    fingerprint: EvidenceFingerprint
    catalogue: VerifiedCatalogueSlice
    ledger: ComparisonLedger
    proposals: tuple[object, ...] = ()
    clock: datetime = FIXED_CLOCK
    run_id: str = FIXED_RUN_ID


class _FixedRunConsentAuthority(LocalScopeConsentAuthority):
    """Issue the same run id for the same sanitised replay."""

    def __init__(
        self,
        run_id: str,
        storage: InMemoryConsentStore | None = None,
        *,
        now: Callable[[], datetime],
    ) -> None:
        super().__init__(storage=storage, now=now)
        self._fixed_run_id = run_id

    def prepare(self, candidate_roots: tuple[Path, ...]) -> DiagnosisRunView:
        if not candidate_roots:
            raise DiagnosisStateError("diagnosis prepare requires at least one candidate root")
        locators = tuple(opaque_candidate_locator(root) for root in candidate_roots)
        if len(set(locators)) != len(locators):
            raise DiagnosisStateError("candidate roots must be distinct")
        self._store.pending[self._fixed_run_id] = locators
        return DiagnosisRunView(
            run_id=self._fixed_run_id,
            stage=DiagnosisStage.CREATED,
            next_action=NEXT_ACTION[DiagnosisStage.CREATED],
            input_identity=None,
            approval_url=None,
        )


@dataclass
class _RecordingCollector:
    fingerprint: EvidenceFingerprint
    calls: list[ApprovedScopeReceipt] = field(default_factory=list)

    def collect(self, receipt: ApprovedScopeReceipt) -> EvidenceFingerprint:
        self.calls.append(receipt)
        return self.fingerprint


@dataclass
class _FixedCatalogueLoader:
    slice: VerifiedCatalogueSlice

    def load(self, *, run_id: str, fingerprint_digest: str) -> VerifiedCatalogueSlice:
        del run_id, fingerprint_digest
        return self.slice


@dataclass
class _FixedComparer:
    ledger: ComparisonLedger

    def compare(
        self,
        *,
        fingerprint: object,
        catalogue: VerifiedCatalogueSlice,
        jobs: tuple[object, ...],
        proposals: tuple[object, ...],
        work_audit: object | None = None,
    ) -> ComparisonLedger:
        del fingerprint, catalogue, jobs, proposals, work_audit
        return self.ledger


class _IntegrityReportStore(LensReportStore):
    """Refuse a save that no longer matches the sanitised replay input."""

    def __init__(self, directory: Path, bundle: ReplayBundle, harness: ReplayHarness) -> None:
        super().__init__(directory)
        self._bundle = bundle
        self._harness = harness

    def save_result(self, result: object, **kwargs: object) -> object:
        self._harness.assert_result_matches_bundle(result)
        return super().save_result(result, **kwargs)


class ReplayHarness:
    """One engine, one store, and the sanitised dependencies for a replay."""

    def __init__(
        self,
        bundle: ReplayBundle,
        directory: Path,
        *,
        analysis_mode: AnalysisMode = AnalysisMode.INVENTORY_ONLY,
    ) -> None:
        self.bundle = bundle
        self.directory = Path(directory)
        self.analysis_mode = AnalysisMode(analysis_mode)
        self.root = self.directory / "invented-vault"
        self.root.mkdir(parents=True)
        (self.root / "README.md").write_text("invented\n", encoding="utf-8")
        self.consent_store = InMemoryConsentStore()
        self.consent = _FixedRunConsentAuthority(
            bundle.run_id,
            storage=self.consent_store,
            now=lambda: bundle.clock,
        )
        self.collector = _RecordingCollector(bundle.fingerprint)
        self.catalogue_loader = _FixedCatalogueLoader(bundle.catalogue)
        self.comparer = _FixedComparer(bundle.ledger)
        self.reports = _IntegrityReportStore(self.directory / "reports", bundle, self)
        self.run_store = DiagnosisRunStore(self.directory / "state" / "diagnosis-runs")
        self.engine = self._build_engine()
        self._proposals_submitted = False

    def _build_engine(self) -> DeterministicDiagnosisEngine:
        return DeterministicDiagnosisEngine(
            run_store=self.run_store,
            consent_authority=self.consent,
            collector=self.collector,
            catalogue_loader=self.catalogue_loader,
            comparer=self.comparer,
            report_store=self.reports,
            clock=lambda: self.bundle.clock,
        )

    def rebuild_engine(self) -> DeterministicDiagnosisEngine:
        """Rebuild over the same run store and consent store."""

        self.engine = self._build_engine()
        return self.engine

    def prepare(self) -> DiagnosisRunView:
        return self.engine.prepare(
            PrepareDiagnosisRequest(
                roots=(self.root,),
                analysis_mode=self.analysis_mode,
            )
        )

    def approve(self) -> ApprovedScopeReceipt:
        return self.consent.approve_from_local_session(
            run_id=self.bundle.run_id,
            scope_snapshot=ScopeSnapshot.capture((self.root,)),
            authenticated_session_id="local-session",
        )

    def submit_proposals(self) -> None:
        if self._proposals_submitted:
            return
        for proposal in self.bundle.proposals:
            self.engine.submit(self.bundle.run_id, proposal)
        self._proposals_submitted = True

    def run_to(self, stage: DiagnosisStage) -> DiagnosisRunView:
        view = self.engine.status(self.bundle.run_id)
        while view.stage is not stage:
            if view.stage is DiagnosisStage.CREATED:
                self.approve()
            if (
                view.stage is DiagnosisStage.CATALOGUE_VERIFIED
                and self.bundle.proposals
                and not self._proposals_submitted
            ):
                self.submit_proposals()
            if view.stage is DiagnosisStage.ANALYSIS_PLANNED:
                self.complete_guided_work()
            view = self.engine.advance(self.bundle.run_id)
        return view

    def complete_guided_work(self) -> None:
        """Submit explicit empty responses for every replay work packet."""

        while True:
            packet = self.engine.work(self.bundle.run_id)
            if packet is None:
                return
            self.engine.submit_work(self.bundle.run_id, packet.packet_id, ())

    def run_to_closed(self) -> DiagnosisResult:
        self.prepare()
        self.run_to(DiagnosisStage.CLOSED)
        return self.engine.result(self.bundle.run_id)

    def resume_to_closed(self) -> DiagnosisResult:
        """Resume from the last checkpoint, refusing a stale scope digest."""

        checkpoint = self.run_store.load(self.bundle.run_id)
        expected = self.expected_input_identity(checkpoint)
        if expected is not None:
            self.run_store.load(self.bundle.run_id, expected_input_digest=expected)
        self.run_to(DiagnosisStage.CLOSED)
        return self.engine.result(self.bundle.run_id)

    def expected_input_identity(self, checkpoint: DiagnosisCheckpoint) -> str | None:
        """Recompute the scope-bound identity from the stored receipt."""

        if checkpoint.stage is not DiagnosisStage.SCOPE_APPROVED:
            return checkpoint.input_identity
        receipt = self._stored_receipt(checkpoint)
        if receipt is None:
            return checkpoint.input_identity
        return canonical_json_digest(
            {"engine_version": ENGINE_VERSION, "scope_digest": receipt.scope_digest}
        )

    def _stored_receipt(self, checkpoint: DiagnosisCheckpoint) -> ApprovedScopeReceipt | None:
        live = self.consent.receipt_for(checkpoint.run_id)
        if live is not None:
            stored = self._artifact_payload(checkpoint, "scope-receipt")
            if stored is None:
                return live
            artifact = ApprovedScopeReceipt.model_validate(stored)
            if artifact.scope_digest != live.scope_digest:
                return artifact
            return live
        stored = self._artifact_payload(checkpoint, "scope-receipt")
        if stored is None:
            return None
        return ApprovedScopeReceipt.model_validate(stored)

    def _artifact_payload(self, checkpoint: DiagnosisCheckpoint, kind: str) -> object | None:
        for digest in reversed(checkpoint.artifact_digests):
            envelope = self.engine._get(digest)  # noqa: SLF001 - digest-addressed store
            if envelope.get("kind") == kind:
                return envelope.get("payload")
        return None

    def replace_artifact(self, kind: str, payload: object) -> DiagnosisCheckpoint:
        checkpoint = self.run_store.load(self.bundle.run_id)
        kept: list[str] = []
        for digest in checkpoint.artifact_digests:
            envelope = self.engine._get(digest)  # noqa: SLF001
            if envelope.get("kind") != kind:
                kept.append(digest)
        replacement = self.engine._put(kind, payload)  # noqa: SLF001
        updated = checkpoint.model_copy(update={"artifact_digests": (*kept, replacement)})
        return self.run_store.save(updated)

    def checkpoint(self) -> DiagnosisCheckpoint:
        return self.run_store.load(self.bundle.run_id)

    def retained_text(self) -> str:
        parts: list[str] = []
        storage = self.run_store.storage
        if storage.is_dir():
            for path in sorted(storage.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    parts.append(path.read_text(encoding="utf-8", errors="replace"))
        reports = self.reports.directory
        if reports.is_dir():
            for path in sorted(reports.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    parts.append(path.read_text(encoding="utf-8", errors="replace"))
        parts.append(self.bundle.fingerprint.model_dump_json())
        parts.append(self.bundle.ledger.model_dump_json())
        return "\n".join(parts)

    def assert_result_matches_bundle(self, result: object) -> None:
        ledger = getattr(result, "ledger", None)
        report = getattr(result, "report", None)
        if not isinstance(ledger, ComparisonLedger) or report is None:
            raise DiagnosisStateError("save requires the typed diagnosis result")
        expected_counts = Counter(item.disposition for item in self.bundle.ledger.entries)
        actual_counts = Counter(item.disposition for item in ledger.entries)
        if actual_counts != expected_counts:
            raise DiagnosisStateError("hostile count mutation")
        if ledger.catalogue_sha256 != self.bundle.ledger.catalogue_sha256:
            raise DiagnosisStateError("hostile catalogue hash mutation")
        expected_local = {
            item.observation_id: (
                item.kind,
                item.identity,
                item.configuration_state,
                item.runtime_state,
                item.health_state,
            )
            for item in self.bundle.ledger.local_entries
        }
        actual_local = {
            item.observation_id: (
                item.kind,
                item.identity,
                item.configuration_state,
                item.runtime_state,
                item.health_state,
            )
            for item in ledger.local_entries
        }
        if actual_local != expected_local:
            raise DiagnosisStateError("hostile local axes mutation")
        if ledger.mcp_tools_by_server != self.bundle.ledger.mcp_tools_by_server:
            raise DiagnosisStateError("hostile tool appendix mutation")
        allowed_refs = _evidence_references(self.bundle.fingerprint, self.bundle.ledger)
        actual_refs = {
            reference
            for item in (*ledger.entries, *ledger.local_entries)
            for reference in item.evidence_references
        }
        if not actual_refs.issubset(allowed_refs):
            raise DiagnosisStateError("hostile evidence reference mutation")
        fingerprint = self._loaded_fingerprint()
        expected_classes = {
            item.provenance.source_class.value for item in self.bundle.fingerprint.observations
        }
        actual_classes = {item.provenance.source_class.value for item in fingerprint.observations}
        if actual_classes != expected_classes:
            raise DiagnosisStateError("hostile source class mutation")
        for decision in getattr(report, "decisions", ()):
            if decision.state in {DecisionState.CHOSEN, DecisionState.COMPLETED}:
                if decision.receipt is None:
                    raise DiagnosisStateError("hostile decision state mutation")
        share_state = getattr(report, "share_state", ShareState.NOT_OFFERED)
        share_receipt = getattr(report, "share_receipt", None)
        if share_state in {ShareState.PREVIEWED, ShareState.SENT} and share_receipt is None:
            raise DiagnosisStateError("hostile share state mutation")

    def _loaded_fingerprint(self) -> EvidenceFingerprint:
        checkpoint = self.run_store.load(self.bundle.run_id)
        payload = self._artifact_payload(checkpoint, "fingerprint")
        if payload is None:
            return self.bundle.fingerprint
        try:
            migrated = upgrade_stored_fingerprint_payload(payload)
            return EvidenceFingerprint.model_validate(migrated)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored replay fingerprint is unreadable") from exc


def canonical_replay_bytes(result: DiagnosisResult) -> bytes:
    """Sorted compact JSON of the closed typed result."""

    return canonical_result_bytes(result.dump_for_storage())


def run_direct(
    replay: ReplayBundle,
    *,
    analysis_mode: AnalysisMode = AnalysisMode.INVENTORY_ONLY,
) -> bytes:
    """Drive the engine interface with no adapter translation."""

    with TemporaryDirectory(prefix="lens-replay-direct-") as tmp:
        harness = ReplayHarness(
            replay,
            Path(tmp),
            analysis_mode=analysis_mode,
        )
        return canonical_replay_bytes(harness.run_to_closed())


def run_cli(replay: ReplayBundle) -> bytes:
    """Drive ``diagnosis_main`` against the same injected engine factory."""

    with TemporaryDirectory(prefix="lens-replay-cli-") as tmp:
        harness = ReplayHarness(
            replay,
            Path(tmp),
            analysis_mode=AnalysisMode.INVENTORY_ONLY,
        )
        diagnosis_cli.bind_consent_surface(_SilentSession(), _SilentServer())
        try:
            with patch.object(diagnosis_cli, "build_engine", lambda: harness.engine):
                _cli_json(
                    [
                        "prepare",
                        "--root",
                        str(harness.root),
                        "--mode",
                        harness.analysis_mode.value,
                    ]
                )
                harness.approve()
                view = _cli_json(["status", "--run", replay.run_id, "--json"])
                while view["stage"] != DiagnosisStage.CLOSED.value:
                    if (
                        view["stage"] == DiagnosisStage.CATALOGUE_VERIFIED.value
                        and replay.proposals
                        and not harness._proposals_submitted
                    ):
                        _cli_submit(replay, harness)
                    if view["stage"] == DiagnosisStage.ANALYSIS_PLANNED.value:
                        if harness.analysis_mode is AnalysisMode.GUIDED:
                            _complete_guided_work_cli(harness)
                        else:
                            harness.complete_guided_work()
                    view = _cli_json(["advance", "--run", replay.run_id, "--json"])
                payload = _cli_json(["result", "--run", replay.run_id, "--format", "json"])
        finally:
            diagnosis_cli.reset_consent_surface()
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return encoded


def run_mcp(replay: ReplayBundle, *, discover: DiscoverOrder = "listed") -> bytes:
    """Drive the MCP adapter with an in-process client over the same engine."""

    with TemporaryDirectory(prefix="lens-replay-mcp-") as tmp:
        harness = ReplayHarness(
            replay,
            Path(tmp),
            analysis_mode=AnalysisMode.INVENTORY_ONLY,
        )
        return anyio.run(_drive_mcp, harness, discover)


async def _drive_mcp(harness: ReplayHarness, discover: DiscoverOrder) -> bytes:
    server = build_mcp_server(harness.engine)
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        names = [item.name for item in listed.tools]
        ordered = _discover_tool_names(names, discover)
        if set(ordered) != set(names):
            raise DiagnosisStateError("MCP tool discovery lost a diagnosis tool")
        prepared = await client.call_tool(
            "prepare_diagnosis",
            {"roots": [str(harness.root)]},
        )
        _tool_payload(prepared)
        harness.approve()
        view = _tool_payload(
            await client.call_tool(
                "get_diagnosis_status",
                {"run_id": harness.bundle.run_id},
            )
        )
        while view["stage"] != DiagnosisStage.CLOSED.value:
            if (
                view["stage"] == DiagnosisStage.CATALOGUE_VERIFIED.value
                and harness.bundle.proposals
                and not harness._proposals_submitted
            ):
                harness.submit_proposals()
            if view["stage"] == DiagnosisStage.ANALYSIS_PLANNED.value:
                if harness.analysis_mode is AnalysisMode.GUIDED:
                    await _complete_guided_work_mcp(client, harness)
                else:
                    harness.complete_guided_work()
            view = _tool_payload(
                await client.call_tool(
                    "advance_diagnosis",
                    {"run_id": harness.bundle.run_id},
                )
            )
        result = await client.call_tool(
            "get_diagnosis_result",
            {"run_id": harness.bundle.run_id},
        )
        return canonical_result_bytes(_tool_payload(result))


def _discover_tool_names(names: Sequence[str], discover: DiscoverOrder) -> list[str]:
    if discover == "claude":
        return sorted(names, reverse=True)
    if discover == "codex":
        return sorted(names)
    return list(names)


def _complete_guided_work_cli(harness: ReplayHarness) -> None:
    while True:
        work = _cli_json(["work", "--run", harness.bundle.run_id, "--json"])
        packet = work.get("packet")
        if packet is None:
            return
        assert isinstance(packet, dict)
        _cli_json(
            [
                "submit",
                "--run",
                harness.bundle.run_id,
                "--packet",
                str(packet["packet_id"]),
            ]
        )


async def _complete_guided_work_mcp(client: Client, harness: ReplayHarness) -> None:
    while True:
        work = _tool_payload(
            await client.call_tool(
                "get_diagnosis_work",
                {"run_id": harness.bundle.run_id},
            )
        )
        packet = work.get("packet")
        if packet is None:
            return
        assert isinstance(packet, dict)
        await client.call_tool(
            "submit_specialist_proposal",
            {
                "run_id": harness.bundle.run_id,
                "packet_id": packet["packet_id"],
                "proposals": [],
            },
        )


def _cli_json(argv: list[str]) -> dict[str, object]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = diagnosis_cli.diagnosis_main(argv)
    if code != 0:
        raise DiagnosisStateError(f"diagnosis CLI refused the command: {argv[0]}")
    return json.loads(buffer.getvalue())


def _cli_submit(replay: ReplayBundle, harness: ReplayHarness) -> None:
    for index, proposal in enumerate(replay.proposals):
        path = harness.directory / f"proposal-{index}.json"
        dump = getattr(proposal, "model_dump", None)
        payload = dump(mode="json") if callable(dump) else proposal
        path.write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        _cli_json(["submit", "--run", replay.run_id, "--proposal", str(path)])
    harness._proposals_submitted = True


def _tool_payload(result: object) -> dict[str, object]:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or ()
    for block in content:
        text = getattr(block, "text", None)
        if text:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded
    raise DiagnosisStateError("MCP tool result had no JSON object payload")


def _evidence_references(
    fingerprint: EvidenceFingerprint,
    ledger: ComparisonLedger,
) -> set[str]:
    refs = {item.evidence.reference for item in fingerprint.observations}
    refs.update(
        reference for item in ledger.entries for reference in item.evidence_references
    )
    return refs


class _SilentSession:
    server_port = None
    bootstrap_token = ""
    diagnosis_consent = None
    diagnosis_run_id = None


class _SilentServer:
    server_port = None
