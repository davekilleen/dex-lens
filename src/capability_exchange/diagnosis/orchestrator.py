"""Deep deterministic diagnosis engine. CLI and MCP are thin adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from capability_exchange.concierge.consent import (
    LocalScopeConsentAuthority,
    opaque_candidate_locator,
)
from capability_exchange.diagnosis.comparison import ComparisonLedger, Disposition
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    upgrade_stored_fingerprint_payload,
)
from capability_exchange.diagnosis.report import (
    ReportModel,
    canonical_fact_block,
    canonical_ledger_appendix,
    canonical_ledger_digest,
    canonical_ledger_payload,
    ledger_appendix_errors,
)
from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    INPUT_SCHEMA_VERSION,
    NEXT_ACTION,
    NEXT_STAGE,
    ApprovedScopeReceipt,
    DiagnosisCheckpoint,
    DiagnosisInput,
    DiagnosisRunView,
    DiagnosisStage,
    DiagnosisStateError,
    RequiredStep,
    RunIdentity,
    advance_inventory_to_compare,
    advance_to,
    canonical_json_digest,
    required_step_for_stage,
)
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    DISAGREEMENT_REASON,
    MAX_RECOMMENDATIONS,
    CandidateBaseline,
    ProposalContext,
    SpecialistProposal,
    SpecialistProposalError,
    ValidatedProposal,
    mint_evidence_token,
    reconcile_proposals,
    validate_proposal,
)
from capability_exchange.diagnosis.work import (
    AnalysisMode,
    WorkAudit,
    WorkPacket,
    WorkQueue,
    WorkQueueError,
    WorkReceipt,
    WorkStatus,
    build_work_queue,
)
from capability_exchange.reports.store import LensReportStore

__all__ = [
    "ADAPTER_VERSION",
    "ComparisonBuilder",
    "DeterministicDiagnosisEngine",
    "DiagnosisResult",
    "FingerprintCollector",
    "PrepareDiagnosisRequest",
    "VerifiedCatalogueLoader",
    "VerifiedCatalogueSlice",
    "fingerprint_digest_for",
]

ADAPTER_VERSION = "injected-collector"


def payload_digest(payload: object) -> str:
    """Return 64 hex characters over sorted compact JSON."""

    return canonical_json_digest(payload).removeprefix("sha256:")


def fingerprint_digest_for(fingerprint: EvidenceFingerprint) -> str:
    """Stable sha256: digest of one fingerprint payload."""

    return "sha256:" + payload_digest(fingerprint.model_dump(mode="json"))


@dataclass(frozen=True)
class PrepareDiagnosisRequest:
    """Candidate folders recorded without reading them."""

    roots: tuple[Path, ...]
    analysis_mode: AnalysisMode = AnalysisMode.GUIDED

    @classmethod
    def from_roots(cls, roots: Sequence[Path | str]) -> PrepareDiagnosisRequest:
        if not roots:
            raise DiagnosisStateError("diagnosis prepare requires at least one candidate root")
        return cls(roots=tuple(Path(root) for root in roots))


@dataclass(frozen=True)
class VerifiedCatalogueSlice:
    """Lawful catalogue facts the engine may consume. Not a second catalogue."""

    version: int
    sha256: str
    catalogue_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    unavailable_ids: tuple[str, ...] = ()
    family_contract_present: bool = False
    core_release: str | None = None


@dataclass(frozen=True)
class DiagnosisResult:
    """Closed typed result. Markdown is rendered from the bound report and ledger."""

    report: ReportModel
    ledger: ComparisonLedger

    def dump_for_storage(self) -> dict[str, object]:
        return {
            "ledger": canonical_ledger_payload(self.ledger),
            "ledger_appendix": canonical_ledger_appendix(self.ledger),
            "ledger_sha256": self.report.ledger_sha256,
            "report": self.report.model_dump(mode="json"),
            "run_id": self.report.run_identity.run_id,
            "stage": DiagnosisStage.CLOSED.value,
        }

    def render_markdown(self) -> str:
        return self.report.render_markdown(self.ledger)

    def ledger_json(self) -> str:
        return json.dumps(
            canonical_ledger_payload(self.ledger),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def with_report_location(self, path: Path) -> DiagnosisResult:
        """Bind the exact app-storage destination before canonical rendering."""

        return DiagnosisResult(
            report=self.report.with_report_location(path),
            ledger=self.ledger,
        )


class FingerprintCollector(Protocol):
    """Constructor-injected wrap over existing collection. Not a second stack."""

    def collect(self, receipt: ApprovedScopeReceipt) -> EvidenceFingerprint: ...


class VerifiedCatalogueLoader(Protocol):
    """Constructor-injected wrap over VerifiedCatalogueStore."""

    def load(self, *, run_id: str, fingerprint_digest: str) -> VerifiedCatalogueSlice: ...


class ComparisonBuilder(Protocol):
    """Constructor-injected wrap over ComparisonLedger construction."""

    def compare(
        self,
        *,
        fingerprint: EvidenceFingerprint,
        catalogue: VerifiedCatalogueSlice,
        jobs: tuple[object, ...],
        proposals: tuple[ValidatedProposal, ...],
        work_audit: WorkAudit | None = None,
    ) -> ComparisonLedger: ...


class DeterministicDiagnosisEngine:
    """Owns lawful diagnosis transitions. Dependencies are injected."""

    def __init__(
        self,
        *,
        run_store: DiagnosisRunStore,
        consent_authority: LocalScopeConsentAuthority,
        collector: FingerprintCollector,
        catalogue_loader: VerifiedCatalogueLoader,
        comparer: ComparisonBuilder,
        report_store: LensReportStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._runs = run_store
        self._consent = consent_authority
        self._collector = collector
        self._catalogues = catalogue_loader
        self._compare = comparer
        self._reports = report_store
        self._clock = clock

    @property
    def consent_authority(self) -> LocalScopeConsentAuthority:
        """The only authority CLI/MCP may attach to the local /approve surface."""

        return self._consent

    @property
    def run_store(self) -> DiagnosisRunStore:
        """The durable checkpoint store later CLI commands resume from."""

        return self._runs

    def prepare(self, request: object) -> DiagnosisRunView:
        """Record candidate folders. Read nothing and do not collect."""

        roots = tuple(Path(root).expanduser().resolve() for root in request.roots)
        try:
            analysis_mode = AnalysisMode(
                # Requests from pre-guided adapters have no mode field.  Treat
                # that missing field as the explicit compatibility path; the
                # engine request model itself defaults new runs to guided.
                getattr(request, "analysis_mode", AnalysisMode.INVENTORY_ONLY)
            )
        except ValueError as exc:
            raise DiagnosisStateError("unsupported diagnosis analysis mode") from exc
        view = self._consent.prepare(candidate_roots=roots)
        self._runs.save_candidate_scope(
            view.run_id,
            candidate_roots=tuple(str(root) for root in roots),
            locators=tuple(opaque_candidate_locator(root) for root in roots),
            analysis_mode=analysis_mode,
        )
        now = self._clock()
        run_identity = RunIdentity(
            run_id=view.run_id,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            analysis_mode=analysis_mode.value,
            created_at=now,
        )
        identity = canonical_json_digest(
            {"engine_version": ENGINE_VERSION, "run_id": view.run_id}
        )
        artifact = self._put("run-identity", run_identity.dump_for_storage())
        self._runs.save(
            DiagnosisCheckpoint(
                run_id=view.run_id,
                stage=DiagnosisStage.CREATED,
                previous_digest=None,
                input_identity=identity,
                artifact_digests=(artifact,),
                next_action=NEXT_ACTION[DiagnosisStage.CREATED],
                engine_version=ENGINE_VERSION,
                created_at=now,
            )
        )
        return view

    def status(self, run_id: str) -> DiagnosisRunView:
        return self._view(self._load(run_id))

    def advance(self, run_id: str) -> DiagnosisRunView:
        checkpoint = self._load(run_id)
        if checkpoint.stage is DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis is closed; it exposes no mutation port")
        # Legacy checkpoints predate the guided queue.  Their missing mode is
        # explicitly migrated to inventory-only and retains the old direct
        # jobs-confirmed -> compared path.
        if (
            checkpoint.stage is DiagnosisStage.JOBS_CONFIRMED
            and self._analysis_mode(checkpoint) is AnalysisMode.INVENTORY_ONLY
        ):
            return self._view(self._compare_ledger(checkpoint))
        target = NEXT_STAGE[checkpoint.stage]
        handlers = {
            DiagnosisStage.SCOPE_APPROVED: self._approve_scope,
            DiagnosisStage.CAPTURED: self._capture,
            DiagnosisStage.CATALOGUE_VERIFIED: self._verify_catalogue,
            DiagnosisStage.JOBS_CONFIRMED: self._confirm_jobs,
            DiagnosisStage.ANALYSIS_PLANNED: self._plan_analysis,
            DiagnosisStage.ANALYSIS_COMPLETED: self._complete_analysis,
            DiagnosisStage.COMPARED: self._compare_ledger,
            DiagnosisStage.RENDERED: self._render,
            DiagnosisStage.CHECKED: self._check,
            DiagnosisStage.SAVED: self._save,
            DiagnosisStage.CLOSED: self._close,
        }
        return self._view(handlers[target](checkpoint))

    def submit(self, run_id: str, proposal: object) -> DiagnosisRunView:
        checkpoint = self._load(run_id)
        if checkpoint.stage is DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis is closed; it exposes no mutation port")
        if checkpoint.stage in {
            DiagnosisStage.CREATED,
            DiagnosisStage.SCOPE_APPROVED,
            DiagnosisStage.CAPTURED,
        }:
            raise DiagnosisStateError(
                "specialist proposals require a captured fingerprint and verified catalogue"
            )
        if (
            checkpoint.stage in {
                DiagnosisStage.CATALOGUE_VERIFIED,
                DiagnosisStage.JOBS_CONFIRMED,
                DiagnosisStage.ANALYSIS_PLANNED,
                DiagnosisStage.ANALYSIS_COMPLETED,
            }
            and self._analysis_mode(checkpoint) is AnalysisMode.GUIDED
        ):
            raise DiagnosisStateError(
                "guided analysis accepts specialist responses only through submit_work"
            )
        typed = (
            proposal
            if isinstance(proposal, SpecialistProposal)
            else SpecialistProposal.model_validate(proposal)
        )
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        validate_proposal(typed, self._proposal_context(checkpoint, fingerprint, catalogue))
        stored = [*self._proposal_payloads(checkpoint), typed.model_dump(mode="json")]
        artifact = self._put("proposals", stored)
        updated = checkpoint.model_copy(
            update={"artifact_digests": (*checkpoint.artifact_digests, artifact)}
        )
        self._runs.save(updated)
        return self._view(updated)

    def work(self, run_id: str) -> WorkPacket | None:
        """Return the deterministic next packet, or ``None`` when none exists.

        Inventory-only runs intentionally expose no semantic work.  Guided
        runs expose packets only from the persisted analysis-planned queue;
        reopening the engine therefore returns byte-identical packet content.
        """

        checkpoint = self._load(run_id)
        mode = self._analysis_mode(checkpoint)
        if mode is AnalysisMode.INVENTORY_ONLY:
            return None
        if checkpoint.stage is not DiagnosisStage.ANALYSIS_PLANNED:
            raise DiagnosisStateError(
                "specialist work is available only after analysis planning"
            )
        queue = self._work_queue(checkpoint)
        pending = queue.pending_packets()
        return pending[0] if pending else None

    def submit_work(
        self,
        run_id: str,
        packet_id: str,
        proposals: tuple[SpecialistProposal, ...] = (),
    ) -> DiagnosisRunView:
        """Validate and durably record one engine-issued packet response.

        A malformed response consumes the first attempt as a non-terminal
        ``pending`` receipt and may be retried once.  A second malformed
        response becomes terminal ``unresolved``.  Valid responses and exact
        replays are idempotent; a changed response for the same packet fails
        closed.
        """

        checkpoint = self._load(run_id)
        if checkpoint.stage is DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis is closed; it exposes no mutation port")
        if self._analysis_mode(checkpoint) is AnalysisMode.INVENTORY_ONLY:
            raise DiagnosisStateError(
                "inventory-only diagnosis runs do not accept specialist work"
            )
        if checkpoint.stage is not DiagnosisStage.ANALYSIS_PLANNED:
            raise DiagnosisStateError(
                "specialist work is accepted only during analysis planning"
            )
        queue = self._work_queue(checkpoint)
        matches = tuple(item for item in queue.packets if item.packet_id == packet_id)
        if len(matches) != 1:
            raise WorkQueueError("packet is not in this work queue")
        packet = matches[0]
        existing = tuple(item for item in queue.receipts if item.packet_id == packet_id)
        # A final response can be replayed only when its response digest is
        # exactly the same.  We compute the candidate digest after validation
        # below; malformed replays are deliberately allowed to consume the
        # one retry so the bounded failure history remains honest.
        final_existing = next(
            (item for item in existing if item.status in {
                WorkStatus.COMPLETED,
                WorkStatus.INSUFFICIENT,
                WorkStatus.UNRESOLVED,
            }),
            None,
        )
        attempt = final_existing.attempt_count if final_existing is not None else 1 + max(
            (item.attempt_count for item in existing), default=0
        )
        if attempt > 2:
            raise WorkQueueError("packet already has a response")

        # Loading the packet context reads engine-owned artifacts and may
        # uncover tampering.  Such a failure is a run-state error, not a
        # malformed assistant response, so it must never consume a retry.
        context = self._proposal_context_for_packet(checkpoint, packet, queue)
        try:
            typed = tuple(
                item
                if isinstance(item, SpecialistProposal)
                else SpecialistProposal.model_validate(item)
                for item in proposals
            )
            if len(typed) > packet.max_proposals:
                raise SpecialistProposalError(
                    f"a work response may contain at most {packet.max_proposals} proposals"
                )
            validated = tuple(validate_proposal(item, context) for item in typed)
        except (TypeError, ValueError) as exc:
            status = WorkStatus.PENDING if attempt == 1 else WorkStatus.UNRESOLVED
            receipt = WorkReceipt(
                packet_id=packet.packet_id,
                packet_digest=packet.packet_digest,
                response_digest=canonical_json_digest(
                    {
                        "attempt_count": attempt,
                        "packet_digest": packet.packet_digest,
                        "status": status.value,
                    }
                ),
                status=status,
                attempt_count=attempt,
                proposal_count=0,
            )
            updated_queue = queue.record(receipt)
            records = self._response_records(checkpoint)
            records.append(
                {
                    "packet_id": packet.packet_id,
                    "packet_digest": packet.packet_digest,
                    "attempt_count": attempt,
                    "receipt": receipt.model_dump(mode="json"),
                    "proposals": [],
                }
            )
            self._persist_work_state(checkpoint, updated_queue, records)
            message = (
                "specialist response was rejected; one retry remains"
                if status is WorkStatus.PENDING
                else "specialist response was rejected twice and is unresolved"
            )
            raise SpecialistProposalError(message) from exc

        # Empty is a valid, explicit evidence-insufficient response.  It is a
        # final receipt rather than a silent omission.
        status = WorkStatus.INSUFFICIENT if not validated else WorkStatus.COMPLETED
        response_payload = [item.model_dump(mode="json") for item in validated]
        response_payload.sort(key=lambda item: json.dumps(item, sort_keys=True))
        response_digest = canonical_json_digest(
            {
                "attempt_count": attempt,
                "packet_digest": packet.packet_digest,
                "proposals": response_payload,
                "status": status.value,
            }
        )
        if existing and any(
            item.status in {WorkStatus.COMPLETED, WorkStatus.INSUFFICIENT, WorkStatus.UNRESOLVED}
            and item.response_digest == response_digest
            for item in existing
        ):
            return self._view(checkpoint)
        if final_existing is not None:
            raise WorkQueueError("packet already has a different response")
        # ``record`` repeats the queue's lock and retry checks after the
        # response digest has been established.
        queue.require_pending(packet_id)
        receipt = WorkReceipt(
            packet_id=packet.packet_id,
            packet_digest=packet.packet_digest,
            response_digest=response_digest,
            status=status,
            attempt_count=attempt,
            proposal_count=len(validated),
        )
        updated_queue = queue.record(receipt)
        records = self._response_records(checkpoint)
        records.append(
            {
                "packet_id": packet.packet_id,
                "packet_digest": packet.packet_digest,
                "attempt_count": attempt,
                "receipt": receipt.model_dump(mode="json"),
                "proposals": [item.model_dump(mode="json") for item in typed],
                "validated": response_payload,
            }
        )
        persisted = self._persist_work_state(checkpoint, updated_queue, records)
        return self._view(persisted)

    def result(self, run_id: str) -> DiagnosisResult:
        checkpoint = self._load(run_id)
        if checkpoint.stage is not DiagnosisStage.CLOSED:
            raise DiagnosisStateError("diagnosis result is not closed")
        return self._diagnosis_result(checkpoint)

    def _load(self, run_id: str) -> DiagnosisCheckpoint:
        checkpoint = self._runs.load(run_id)
        return self._runs.load(run_id, expected_input_digest=checkpoint.input_identity)

    def _view(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisRunView:
        return DiagnosisRunView(
            run_id=checkpoint.run_id,
            stage=checkpoint.stage,
            next_action=checkpoint.next_action,
            required_step=required_step_for_stage(checkpoint.stage),
            input_identity=checkpoint.input_identity,
            approval_url=None,
        )

    def _diagnosis_input(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisInput:
        """Load and validate the content-bound input for a confirmed run.

        Inputs written before ``analysis_mode`` existed are upgraded in memory
        to inventory-only.  New inputs must still match the checkpoint's
        content identity; accepting an altered input would make the issued
        queue and its evidence bindings stale.
        """

        payload = self._find_kind(checkpoint, "diagnosis-input")
        if not isinstance(payload, dict):
            raise DiagnosisStateError(
                "diagnosis input is missing from this diagnosis checkpoint"
            )
        legacy = "analysis_mode" not in payload
        try:
            from capability_exchange.diagnosis.run import upgrade_stored_input_payload

            upgraded = upgrade_stored_input_payload(payload)
            diagnosis_input = DiagnosisInput.model_validate(upgraded)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored diagnosis input is unreadable") from exc
        if legacy:
            # The old identity was calculated over the payload without the
            # newly-added mode field.  Preserve it while making the mode
            # explicit for all subsequent decisions.
            expected_identity = canonical_json_digest(payload)
        else:
            expected_identity = diagnosis_input.identity_digest
        if checkpoint.input_identity != expected_identity:
            raise DiagnosisStateError("stored diagnosis input identity is invalid")
        return diagnosis_input

    def _run_identity(self, checkpoint: DiagnosisCheckpoint) -> RunIdentity:
        payload = self._find_kind(checkpoint, "run-identity")
        if not isinstance(payload, dict):
            raise DiagnosisStateError("run identity is missing from this diagnosis checkpoint")
        try:
            from capability_exchange.diagnosis.run import upgrade_stored_run_identity_payload

            upgraded = upgrade_stored_run_identity_payload(payload)
            return RunIdentity.model_validate(upgraded)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored run identity is unreadable") from exc

    def _analysis_mode(self, checkpoint: DiagnosisCheckpoint) -> AnalysisMode:
        """Return the persisted mode, migrating old inputs conservatively."""

        # Only a genuinely absent diagnosis-input artifact may use the
        # candidate-scope sidecar as its pre-confirmation mode authority.  If
        # an artifact exists, let every parse or identity failure propagate so
        # tampered state cannot be silently reinterpreted as compatibility.
        if self._has_kind(checkpoint, "diagnosis-input"):
            return AnalysisMode(self._diagnosis_input(checkpoint).analysis_mode)
        identity_mode = AnalysisMode(self._run_identity(checkpoint).analysis_mode)
        # The candidate-scope sidecar mirrors the digest-chain mode authority
        # before job confirmation materialises ``diagnosis-input``.  A missing
        # or contradictory sidecar must fail closed rather than downgrade a
        # guided run back to inventory-only semantics.
        candidate_scope = self._runs.load_candidate_scope(checkpoint.run_id)
        if candidate_scope is None:
            if identity_mode is AnalysisMode.GUIDED:
                raise DiagnosisStateError(
                    "candidate scope is missing for this guided diagnosis run"
                )
            return identity_mode
        if candidate_scope.analysis_mode is not identity_mode:
            raise DiagnosisStateError(
                "stored candidate scope analysis mode does not match this run"
            )
        return identity_mode

    def _require_receipt(self, checkpoint: DiagnosisCheckpoint) -> ApprovedScopeReceipt:
        receipt = self._consent.receipt_for(checkpoint.run_id)
        if receipt is not None:
            return receipt
        stored = self._find_kind(checkpoint, "scope-receipt")
        if stored is not None:
            return ApprovedScopeReceipt.model_validate(stored)
        approval = self._runs.load_scope_approval(checkpoint.run_id)
        if approval is not None:
            return approval.receipt
        raise DiagnosisStateError(
            "approve the exact scope in this chat with dex-lens diagnosis approve",
            required_step=RequiredStep.APPROVE_SCOPE,
        )

    def _advance(
        self,
        checkpoint: DiagnosisCheckpoint,
        stage: DiagnosisStage,
        *,
        artifacts: tuple[str, ...] = (),
        input_identity: str | None = None,
    ) -> DiagnosisCheckpoint:
        moved = advance_to(
            checkpoint,
            stage,
            now=self._clock(),
            artifact_digests=(*checkpoint.artifact_digests, *artifacts),
        )
        if input_identity is not None:
            moved = moved.model_copy(update={"input_identity": input_identity})
        return self._runs.save(moved)

    def _approve_scope(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        receipt = self._require_receipt(checkpoint)
        artifact = self._put("scope-receipt", receipt.dump_for_storage())
        identity = canonical_json_digest(
            {"engine_version": ENGINE_VERSION, "scope_digest": receipt.scope_digest}
        )
        return self._advance(
            checkpoint,
            DiagnosisStage.SCOPE_APPROVED,
            artifacts=(artifact,),
            input_identity=identity,
        )

    def _capture(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        receipt = self._require_receipt(checkpoint)
        fingerprint = self._collector.collect(receipt)
        payload = fingerprint.model_dump(mode="json")
        artifact = self._put("fingerprint", payload)
        identity = canonical_json_digest(
            {
                "engine_version": ENGINE_VERSION,
                "fingerprint_sha256": payload_digest(payload),
                "scope_digest": receipt.scope_digest,
            }
        )
        return self._advance(
            checkpoint,
            DiagnosisStage.CAPTURED,
            artifacts=(artifact,),
            input_identity=identity,
        )

    def _verify_catalogue(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        fingerprint = self._fingerprint(checkpoint)
        loaded = self._catalogues.load(
            run_id=checkpoint.run_id,
            fingerprint_digest=fingerprint_digest_for(fingerprint),
        )
        artifact = self._put(
            "catalogue",
            {
                "capability_ids": list(loaded.capability_ids),
                "catalogue_ids": list(loaded.catalogue_ids),
                "core_release": loaded.core_release,
                "family_contract_present": loaded.family_contract_present,
                "sha256": loaded.sha256,
                "unavailable_ids": list(loaded.unavailable_ids),
                "version": loaded.version,
            },
        )
        identity = canonical_json_digest(
            {
                "catalogue_sha256": loaded.sha256,
                "engine_version": ENGINE_VERSION,
                "fingerprint_digest": fingerprint_digest_for(fingerprint),
            }
        )
        return self._advance(
            checkpoint,
            DiagnosisStage.CATALOGUE_VERIFIED,
            artifacts=(artifact,),
            input_identity=identity,
        )

    def _confirm_jobs(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        receipt = self._require_receipt(checkpoint)
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        analysis_mode = self._analysis_mode(checkpoint)
        diagnosis_input = DiagnosisInput(
            run_id=checkpoint.run_id,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            adapter_version=ADAPTER_VERSION,
            approved_scope_receipt=receipt,
            fingerprint_sha256=payload_digest(fingerprint.model_dump(mode="json")),
            catalogue_version=catalogue.version,
            catalogue_sha256=catalogue.sha256,
            confirmed_jobs=(),
            analysis_mode=analysis_mode.value,
            assessed_at=self._clock(),
        )
        artifact = self._put("diagnosis-input", diagnosis_input.dump_for_storage())
        return self._advance(
            checkpoint,
            DiagnosisStage.JOBS_CONFIRMED,
            artifacts=(artifact,),
            input_identity=diagnosis_input.identity_digest,
        )

    def _plan_analysis(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        """Issue and persist the exact guided queue for this pinned input."""

        mode = self._analysis_mode(checkpoint)
        if mode is AnalysisMode.INVENTORY_ONLY:
            # This branch is normally handled in ``advance`` so old runs keep
            # their direct comparison semantics.  Refuse a forged transition
            # rather than emitting an empty queue for a run that was not
            # created in guided mode.
            raise DiagnosisStateError("inventory-only diagnosis runs do not issue specialist work")
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        context = self._proposal_context(checkpoint, fingerprint, catalogue)
        queue = build_work_queue(context=context, mode=mode)
        queue_artifact = self._put("work-queue", queue.model_dump(mode="json"))
        # The response log is cumulative.  Keeping an explicit empty artifact
        # makes a missing/tampered log distinguishable from a pristine queue.
        responses_artifact = self._put("work-responses", [])
        audit_artifact = self._put("work-audit", queue.audit().model_dump(mode="json"))
        return self._advance(
            checkpoint,
            DiagnosisStage.ANALYSIS_PLANNED,
            artifacts=(queue_artifact, responses_artifact, audit_artifact),
        )

    def _complete_analysis(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        """Reconcile all normal work and the locked sceptical response."""

        if self._analysis_mode(checkpoint) is AnalysisMode.INVENTORY_ONLY:
            raise DiagnosisStateError("inventory-only diagnosis runs have no guided analysis")
        queue = self._work_queue(checkpoint)
        if not queue.complete():
            raise DiagnosisStateError(
                "specialist work remains before analysis can complete",
                required_step=RequiredStep.SUBMIT_WORK,
            )
        normal = self._normal_reconciled_proposals(checkpoint, queue)
        sceptical = self._sceptical_reconciled_proposals(checkpoint, queue)
        sceptical_by_candidate = {
            item.candidate_id: item
            for item in sceptical
            if item.candidate_id is not None
        }
        final = tuple(
            sceptical_by_candidate.get(item.candidate_id, item)
            for item in normal
        )
        # A sceptical response may only refer to a baseline issued by normal
        # work.  Validation already enforces this, but retaining the set check
        # here makes a forged response log fail closed before comparison.
        normal_candidate_ids = {candidate.candidate_id for candidate in normal}
        if any(item.candidate_id not in normal_candidate_ids for item in sceptical):
            raise DiagnosisStateError(
                "sceptical work references an unknown normal candidate"
            )
        proposals_artifact = self._put(
            "reconciled-proposals",
            [item.model_dump(mode="json") for item in final],
        )
        return self._advance(
            checkpoint,
            DiagnosisStage.ANALYSIS_COMPLETED,
            artifacts=(proposals_artifact,),
        )

    def _compare_ledger(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        mode = self._analysis_mode(checkpoint)
        if mode is AnalysisMode.GUIDED:
            if checkpoint.stage is not DiagnosisStage.ANALYSIS_COMPLETED:
                raise DiagnosisStateError(
                    "guided analysis must be completed before comparison"
                )
            payload = self._find_kind(checkpoint, "reconciled-proposals")
            if not isinstance(payload, list):
                raise DiagnosisStateError("reconciled specialist proposals are missing")
            try:
                reconciled = tuple(ValidatedProposal.model_validate(item) for item in payload)
            except (TypeError, ValueError) as exc:
                raise DiagnosisStateError(
                    "stored reconciled specialist proposals are unreadable"
                ) from exc
        else:
            proposals = tuple(
                SpecialistProposal.model_validate(item)
                for item in self._proposal_payloads(checkpoint)
            )
            reconciled = reconcile_proposals(
                proposals,
                context=self._proposal_context(checkpoint, fingerprint, catalogue),
            )
        work_audit = None
        if mode is AnalysisMode.GUIDED:
            audit_payload = self._find_kind(checkpoint, "work-audit")
            if audit_payload is None:
                # Closing without it scored the run's autonomy as zero and
                # silently stopped the incomplete-packets gate from firing, so
                # a run with unanswered packets graded as clean.
                raise DiagnosisStateError("guided analysis cannot close without its work audit")
            try:
                work_audit = WorkAudit.model_validate(audit_payload)
            except (TypeError, ValueError) as exc:
                raise DiagnosisStateError("stored work audit is unreadable") from exc
        ledger = self._compare.compare(
            fingerprint=fingerprint,
            catalogue=catalogue,
            jobs=(),
            proposals=reconciled,
            work_audit=work_audit,
        )
        artifact = self._put("ledger", ledger.model_dump(mode="json"))
        if (
            mode is AnalysisMode.INVENTORY_ONLY
            and checkpoint.stage is DiagnosisStage.JOBS_CONFIRMED
        ):
            moved = advance_inventory_to_compare(
                checkpoint,
                now=self._clock(),
                artifact_digests=(artifact,),
            )
            return self._runs.save(moved)
        return self._advance(checkpoint, DiagnosisStage.COMPARED, artifacts=(artifact,))

    def _render(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        self._diagnosis_result(checkpoint)
        return self._advance(checkpoint, DiagnosisStage.RENDERED)

    def _check(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        result = self._diagnosis_result(checkpoint)
        expected = canonical_fact_block(result.ledger)
        if expected not in result.render_markdown():
            raise DiagnosisStateError("report is missing exact ledger-derived facts")
        if result.report.ledger_sha256 != canonical_ledger_digest(result.ledger):
            raise DiagnosisStateError("report is missing exact ledger-derived facts")
        if ledger_appendix_errors(result.render_markdown(), result.ledger):
            raise DiagnosisStateError("report is missing the complete ledger appendix")
        return self._advance(checkpoint, DiagnosisStage.CHECKED)

    def _save(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        result = self._diagnosis_result(checkpoint)
        saved = self._reports.save_result(
            result, label=result.report.run_identity.run_id, now=self._clock()
        )
        artifact = self._put("saved-report", {"path": str(saved.path)})
        return self._advance(
            checkpoint,
            DiagnosisStage.SAVED,
            artifacts=(artifact,),
        )

    def _close(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        return self._advance(checkpoint, DiagnosisStage.CLOSED)

    def _diagnosis_result(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisResult:
        ledger = ComparisonLedger.model_validate(self._find_kind(checkpoint, "ledger"))
        identity = RunIdentity.model_validate(self._find_kind(checkpoint, "run-identity"))
        fingerprint = self._fingerprint(checkpoint)
        saved_report = self._find_kind(checkpoint, "saved-report")
        report_location = (
            str(saved_report["path"])
            if isinstance(saved_report, dict) and saved_report.get("path")
            else None
        )
        report = ReportModel.from_result(
            run_identity=identity,
            ledger=ledger,
            ledger_sha256=canonical_ledger_digest(ledger),
            limits=fingerprint.limits,
            report_location=report_location,
        )
        return DiagnosisResult(report=report, ledger=ledger)

    def _fingerprint(self, checkpoint: DiagnosisCheckpoint) -> EvidenceFingerprint:
        payload = self._find_kind(checkpoint, "fingerprint")
        if payload is None:
            raise DiagnosisStateError("fingerprint is missing from this diagnosis checkpoint")
        try:
            migrated = upgrade_stored_fingerprint_payload(payload)
            return EvidenceFingerprint.model_validate(migrated)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored evidence fingerprint is unreadable") from exc

    def _catalogue(self, checkpoint: DiagnosisCheckpoint) -> VerifiedCatalogueSlice:
        payload = self._find_kind(checkpoint, "catalogue")
        if payload is None:
            raise DiagnosisStateError(
                "verified catalogue is missing from this diagnosis checkpoint"
            )
        return VerifiedCatalogueSlice(
            version=int(payload["version"]),
            sha256=str(payload["sha256"]),
            catalogue_ids=tuple(payload["catalogue_ids"]),
            capability_ids=tuple(payload["capability_ids"]),
            unavailable_ids=tuple(payload.get("unavailable_ids") or ()),
            family_contract_present=bool(payload.get("family_contract_present", False)),
            core_release=(
                str(payload["core_release"])
                if payload.get("core_release") is not None
                else None
            ),
        )

    def _proposal_context(
        self,
        checkpoint: DiagnosisCheckpoint,
        fingerprint: EvidenceFingerprint,
        catalogue: VerifiedCatalogueSlice,
    ) -> ProposalContext:
        digest = fingerprint_digest_for(fingerprint)
        evidence_ids = tuple(
            mint_evidence_token(
                run_id=checkpoint.run_id,
                fingerprint_digest=digest,
                observation_key=(
                    f"{item.kind.value}:{item.identity}:{item.provenance.source_id}"
                ),
            )
            for item in fingerprint.observations
        )
        observation_ids = tuple(item.observation_id for item in fingerprint.observations)
        return ProposalContext(
            run_id=checkpoint.run_id,
            fingerprint_digest=digest,
            catalogue_digest="sha256:" + catalogue.sha256,
            evidence_ids=evidence_ids,
            catalogue_ids=catalogue.catalogue_ids,
            capability_ids=catalogue.capability_ids,
            observation_ids=observation_ids,
            held_ids=catalogue.unavailable_ids,
            family_contract_present=catalogue.family_contract_present,
        )

    def _proposal_context_for_packet(
        self,
        checkpoint: DiagnosisCheckpoint,
        packet: WorkPacket,
        queue: WorkQueue,
    ) -> ProposalContext:
        """Bind proposal validation to one issued packet and its role."""

        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        base = self._proposal_context(checkpoint, fingerprint, catalogue)
        accepted: tuple[CandidateBaseline, ...] = ()
        accepted_ids: tuple[str, ...] = ()
        if packet.role.value == "sceptical-reconciler":
            normal = self._normal_reconciled_proposals(checkpoint, queue)
            accepted = tuple(
                CandidateBaseline(
                    candidate_id=item.candidate_id or "",
                    kind=item.kind,
                    catalogue_id=item.catalogue_id,
                    capability_id=item.capability_id,
                    original_disposition=item.disposition,
                    recommendation_factors=item.recommendation_factors,
                    evidence_ids=item.evidence_ids,
                    observation_ids=item.observation_ids,
                )
                for item in normal
                if item.candidate_id is not None
                and item.disposition is not Disposition.NOT_ASSESSED
            )
            accepted_ids = tuple(item.candidate_id for item in accepted)
        return base.model_copy(
            update={
                "analysis_mode": AnalysisMode.GUIDED.value,
                "packet_id": packet.packet_id,
                "packet_digest": packet.packet_digest,
                "packet_role": packet.role,
                "accepted_candidate_ids": accepted_ids,
                "accepted_candidates": accepted,
            }
        )

    def _work_queue(self, checkpoint: DiagnosisCheckpoint) -> WorkQueue:
        """Load the latest queue and prove it is the queue for this input."""

        payload = self._find_kind(checkpoint, "work-queue")
        if not isinstance(payload, dict):
            raise DiagnosisStateError("stored specialist work queue is missing")
        try:
            queue = WorkQueue.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored specialist work queue is unreadable") from exc
        if queue.mode is not AnalysisMode.GUIDED:
            raise DiagnosisStateError("stored specialist work queue has an invalid mode")
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        expected = build_work_queue(
            context=self._proposal_context(checkpoint, fingerprint, catalogue),
            mode=AnalysisMode.GUIDED,
        )
        if (
            queue.packets != expected.packets
            or queue.sceptical_packet_id != expected.sceptical_packet_id
        ):
            raise DiagnosisStateError(
                "stored specialist work queue does not match the pinned context"
            )
        self._validate_work_records(checkpoint, queue)
        return queue

    def _response_records(self, checkpoint: DiagnosisCheckpoint) -> list[dict[str, object]]:
        payload = self._find_kind(checkpoint, "work-responses")
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise DiagnosisStateError("stored specialist responses are unreadable")
        records: list[dict[str, object]] = []
        seen: set[tuple[str, int]] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise DiagnosisStateError("stored specialist responses are unreadable")
            packet_id = item.get("packet_id")
            attempt = item.get("attempt_count")
            receipt = item.get("receipt")
            proposals = item.get("proposals")
            if not isinstance(packet_id, str) or not isinstance(attempt, int):
                raise DiagnosisStateError("stored specialist responses are unreadable")
            if (packet_id, attempt) in seen:
                raise DiagnosisStateError("stored specialist responses contain a duplicate attempt")
            if not isinstance(receipt, dict) or not isinstance(proposals, list):
                raise DiagnosisStateError("stored specialist responses are unreadable")
            try:
                typed_receipt = WorkReceipt.model_validate(receipt)
            except (TypeError, ValueError) as exc:
                raise DiagnosisStateError(
                    "stored specialist response receipt is unreadable"
                ) from exc
            if (
                typed_receipt.packet_id != packet_id
                or typed_receipt.attempt_count != attempt
            ):
                raise DiagnosisStateError("stored specialist response receipt is inconsistent")
            record = dict(item)
            record["receipt"] = typed_receipt.model_dump(mode="json")
            records.append(record)
            seen.add((packet_id, attempt))
        return sorted(
            records,
            key=lambda item: (str(item["packet_id"]), int(item["attempt_count"])),
        )

    def _validate_work_records(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
    ) -> None:
        """Cross-check cumulative response artifacts against queue receipts."""

        records = self._response_records(checkpoint)
        by_key = {
            (str(item["packet_id"]), int(item["attempt_count"])): item for item in records
        }
        expected_keys = {
            (receipt.packet_id, receipt.attempt_count) for receipt in queue.receipts
        }
        if set(by_key) != expected_keys:
            raise DiagnosisStateError("stored specialist responses do not match work receipts")
        packets = {packet.packet_id: packet for packet in queue.packets}
        for receipt in queue.receipts:
            record = by_key[(receipt.packet_id, receipt.attempt_count)]
            if record.get("packet_digest") != receipt.packet_digest:
                raise DiagnosisStateError("stored specialist response packet digest is invalid")
            if record.get("receipt") != receipt.model_dump(mode="json"):
                raise DiagnosisStateError("stored specialist response receipt is invalid")
            proposals = record.get("proposals")
            if not isinstance(proposals, list):
                raise DiagnosisStateError("stored specialist response proposals are unreadable")
            if receipt.status in {WorkStatus.PENDING, WorkStatus.UNRESOLVED} and proposals:
                raise DiagnosisStateError("non-final specialist response contains proposals")
            if receipt.proposal_count != len(proposals):
                raise DiagnosisStateError("specialist response proposal count is invalid")
            if receipt.status in {WorkStatus.COMPLETED, WorkStatus.INSUFFICIENT}:
                if receipt.status is WorkStatus.INSUFFICIENT and proposals:
                    raise DiagnosisStateError("insufficient specialist response contains proposals")
                if receipt.status is WorkStatus.COMPLETED and not proposals:
                    raise DiagnosisStateError("completed specialist response is empty")
                packet = packets[receipt.packet_id]
                if receipt.status is WorkStatus.COMPLETED:
                    try:
                        typed = tuple(SpecialistProposal.model_validate(item) for item in proposals)
                        context = self._proposal_context_for_packet(checkpoint, packet, queue)
                        validated = tuple(validate_proposal(item, context) for item in typed)
                    except (TypeError, ValueError) as exc:
                        raise DiagnosisStateError(
                            "stored specialist response proposal is invalid"
                        ) from exc
                    payload = [item.model_dump(mode="json") for item in validated]
                    payload.sort(key=lambda item: json.dumps(item, sort_keys=True))
                else:
                    payload = []
                expected_digest = canonical_json_digest(
                    {
                        "attempt_count": receipt.attempt_count,
                        "packet_digest": receipt.packet_digest,
                        "proposals": payload,
                        "status": receipt.status.value,
                    }
                )
            else:
                expected_digest = canonical_json_digest(
                    {
                        "attempt_count": receipt.attempt_count,
                        "packet_digest": receipt.packet_digest,
                        "status": receipt.status.value,
                    }
                )
            if receipt.response_digest != expected_digest:
                raise DiagnosisStateError("stored specialist response digest is invalid")

    def _persist_work_state(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
        records: list[dict[str, object]],
    ) -> DiagnosisCheckpoint:
        queue_artifact = self._put("work-queue", queue.model_dump(mode="json"))
        responses_artifact = self._put("work-responses", sorted(
            records,
            key=lambda item: (str(item["packet_id"]), int(item["attempt_count"])),
        ))
        audit_artifact = self._put("work-audit", queue.audit().model_dump(mode="json"))
        updated = checkpoint.model_copy(
            update={
                "artifact_digests": (
                    *checkpoint.artifact_digests,
                    queue_artifact,
                    responses_artifact,
                    audit_artifact,
                )
            }
        )
        return self._runs.save(updated)

    def _normal_reconciled_proposals(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
    ) -> tuple[ValidatedProposal, ...]:
        """Reconcile final normal responses before sceptical review."""

        packets = {packet.packet_id: packet for packet in queue.packets}
        validated: list[ValidatedProposal] = []
        for record in self._response_records(checkpoint):
            receipt = WorkReceipt.model_validate(record["receipt"])
            packet = packets.get(receipt.packet_id)
            if packet is None or packet.role.value == "sceptical-reconciler":
                continue
            if receipt.status not in {WorkStatus.COMPLETED, WorkStatus.INSUFFICIENT}:
                continue
            proposals = record.get("proposals")
            if not isinstance(proposals, list):
                raise DiagnosisStateError("stored specialist response proposals are unreadable")
            for item in proposals:
                try:
                    validated.append(
                        validate_proposal(
                            SpecialistProposal.model_validate(item),
                            self._proposal_context_for_packet(checkpoint, packet, queue),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    raise DiagnosisStateError(
                        "stored normal specialist proposal is invalid"
                    ) from exc
        groups: dict[tuple[str, str, str, str], list[ValidatedProposal]] = {}
        for item in validated:
            key = (
                item.kind.value,
                item.catalogue_id,
                item.capability_id,
                item.candidate_id or "",
            )
            groups.setdefault(key, []).append(item)
        reconciled: list[ValidatedProposal] = []
        for key in sorted(groups):
            group = sorted(groups[key], key=lambda item: (item.packet_id or "", item.reason))
            sample = group[0]
            dispositions = {item.disposition for item in group}
            factors = {item.recommendation_factors for item in group}
            recommendation_factors = next(iter(factors)) if len(factors) == 1 else None
            if len(dispositions) != 1 or (
                any(item.recommendation_factors is not None for item in group)
                and len(factors) != 1
            ):
                disposition = Disposition.NOT_ASSESSED
                recommendation_factors = None
                reason = DISAGREEMENT_REASON
            else:
                disposition = sample.disposition
                reason = sorted(item.reason for item in group)[0]
            evidence_ids = tuple(
                sorted({token for item in group for token in item.evidence_ids})
            )
            observation_ids = tuple(
                sorted({token for item in group for token in item.observation_ids})
            )
            reconciled.append(
                ValidatedProposal(
                    kind=sample.kind,
                    catalogue_id=sample.catalogue_id,
                    capability_id=sample.capability_id,
                    packet_id=sample.packet_id,
                    packet_digest=sample.packet_digest,
                    candidate_id=sample.candidate_id,
                    disposition=disposition,
                    recommendation_factors=recommendation_factors,
                    evidence_ids=evidence_ids,
                    reason=reason,
                    observation_ids=observation_ids,
                )
            )
        if sum(
            item.kind.value == "recommendation" or item.disposition.value == "worth-borrowing"
            for item in reconciled
        ) > MAX_RECOMMENDATIONS:
            raise SpecialistProposalError(
                f"a diagnosis may recommend at most {MAX_RECOMMENDATIONS} Dex additions"
            )
        return tuple(reconciled)

    def _sceptical_reconciled_proposals(
        self,
        checkpoint: DiagnosisCheckpoint,
        queue: WorkQueue,
    ) -> tuple[ValidatedProposal, ...]:
        packet = next(
            item for item in queue.packets if item.role.value == "sceptical-reconciler"
        )
        context = self._proposal_context_for_packet(checkpoint, packet, queue)
        proposals: list[SpecialistProposal] = []
        for record in self._response_records(checkpoint):
            receipt = WorkReceipt.model_validate(record["receipt"])
            if receipt.packet_id != packet.packet_id or receipt.status not in {
                WorkStatus.COMPLETED,
                WorkStatus.INSUFFICIENT,
            }:
                continue
            payload = record.get("proposals")
            if not isinstance(payload, list):
                raise DiagnosisStateError("stored sceptical response proposals are unreadable")
            try:
                proposals.extend(SpecialistProposal.model_validate(item) for item in payload)
            except (TypeError, ValueError) as exc:
                raise DiagnosisStateError(
                    "stored sceptical specialist proposal is invalid"
                ) from exc
        if not proposals:
            return ()
        try:
            return reconcile_proposals(proposals, context=context)
        except (TypeError, ValueError) as exc:
            raise DiagnosisStateError("stored sceptical specialist proposals are invalid") from exc

    def _proposal_payloads(self, checkpoint: DiagnosisCheckpoint) -> list[object]:
        payload = self._find_kind(checkpoint, "proposals")
        if not isinstance(payload, list):
            return []
        return list(payload)

    def _artifact_root(self) -> Path:
        return self._runs.storage / "artifacts"

    def _artifact_path(self, digest: str) -> Path:
        hex_digest = digest.removeprefix("sha256:")
        path = (self._artifact_root() / f"{hex_digest}.json").resolve(strict=False)
        if path.parent != self._artifact_root().resolve(strict=False):
            raise DiagnosisStateError("diagnosis artifact escaped the run store")
        return path

    def _put(self, kind: str, payload: object) -> str:
        envelope = {"kind": kind, "payload": payload}
        digest = canonical_json_digest(envelope)
        path = self._artifact_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(envelope, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        return digest

    def _get(self, digest: str) -> dict[str, object]:
        path = self._artifact_path(digest)
        if not path.is_file():
            raise DiagnosisStateError("stored diagnosis artifact is missing")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DiagnosisStateError("stored diagnosis artifact is unreadable") from exc
        if canonical_json_digest(envelope) != digest:
            raise DiagnosisStateError("stored diagnosis artifact digest is invalid")
        if not isinstance(envelope, dict):
            raise DiagnosisStateError("stored diagnosis artifact digest is invalid")
        return envelope

    def _find_kind(self, checkpoint: DiagnosisCheckpoint, kind: str) -> object | None:
        for digest in reversed(checkpoint.artifact_digests):
            envelope = self._get(digest)
            if envelope.get("kind") == kind:
                return envelope.get("payload")
        return None

    def _has_kind(self, checkpoint: DiagnosisCheckpoint, kind: str) -> bool:
        """Return whether a digest-bound artifact of ``kind`` exists."""

        for digest in reversed(checkpoint.artifact_digests):
            if self._get(digest).get("kind") == kind:
                return True
        return False
