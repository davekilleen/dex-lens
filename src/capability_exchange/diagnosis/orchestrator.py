"""Deep deterministic diagnosis engine. CLI and MCP are thin adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from capability_exchange.concierge.consent import LocalScopeConsentAuthority
from capability_exchange.diagnosis.comparison import ComparisonLedger
from capability_exchange.diagnosis.observations import EvidenceFingerprint
from capability_exchange.diagnosis.report import (
    ReportModel,
    canonical_fact_block,
    canonical_ledger_digest,
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
    RunIdentity,
    advance_to,
    canonical_json_digest,
)
from capability_exchange.diagnosis.run_store import DiagnosisRunStore
from capability_exchange.diagnosis.specialists import (
    ProposalContext,
    SpecialistProposal,
    ValidatedProposal,
    mint_evidence_token,
    reconcile_proposals,
    validate_proposal,
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


@dataclass(frozen=True)
class DiagnosisResult:
    """Closed typed result. Markdown is rendered from the bound report and ledger."""

    report: ReportModel
    ledger: ComparisonLedger

    def dump_for_storage(self) -> dict[str, object]:
        return {
            "ledger_sha256": self.report.ledger_sha256,
            "report": self.report.model_dump(mode="json"),
            "run_id": self.report.run_identity.run_id,
            "stage": DiagnosisStage.CLOSED.value,
        }

    def render_markdown(self) -> str:
        return self.report.render_markdown(self.ledger)

    def ledger_json(self) -> str:
        return json.dumps(
            self.ledger.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
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

    def prepare(self, request: object) -> DiagnosisRunView:
        """Record candidate folders. Read nothing and do not collect."""

        roots = tuple(Path(root) for root in request.roots)
        view = self._consent.prepare(candidate_roots=roots)
        now = self._clock()
        run_identity = RunIdentity(
            run_id=view.run_id,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
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
        target = NEXT_STAGE[checkpoint.stage]
        handlers = {
            DiagnosisStage.SCOPE_APPROVED: self._approve_scope,
            DiagnosisStage.CAPTURED: self._capture,
            DiagnosisStage.CATALOGUE_VERIFIED: self._verify_catalogue,
            DiagnosisStage.JOBS_CONFIRMED: self._confirm_jobs,
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
            input_identity=checkpoint.input_identity,
            approval_url=None,
        )

    def _require_receipt(self, checkpoint: DiagnosisCheckpoint) -> ApprovedScopeReceipt:
        receipt = self._consent.receipt_for(checkpoint.run_id)
        if receipt is not None:
            return receipt
        stored = self._find_kind(checkpoint, "scope-receipt")
        if stored is None:
            raise DiagnosisStateError("approve the exact scope in the local consent surface")
        return ApprovedScopeReceipt.model_validate(stored)

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
            assessed_at=self._clock(),
        )
        artifact = self._put("diagnosis-input", diagnosis_input.dump_for_storage())
        return self._advance(
            checkpoint,
            DiagnosisStage.JOBS_CONFIRMED,
            artifacts=(artifact,),
            input_identity=diagnosis_input.identity_digest,
        )

    def _compare_ledger(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        fingerprint = self._fingerprint(checkpoint)
        catalogue = self._catalogue(checkpoint)
        proposals = tuple(
            SpecialistProposal.model_validate(item)
            for item in self._proposal_payloads(checkpoint)
        )
        reconciled = reconcile_proposals(
            proposals,
            context=self._proposal_context(checkpoint, fingerprint, catalogue),
        )
        ledger = self._compare.compare(
            fingerprint=fingerprint,
            catalogue=catalogue,
            jobs=(),
            proposals=reconciled,
        )
        artifact = self._put("ledger", ledger.model_dump(mode="json"))
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
        return self._advance(checkpoint, DiagnosisStage.CHECKED)

    def _save(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        result = self._diagnosis_result(checkpoint)
        self._reports.save_result(
            result, label=result.report.run_identity.run_id, now=self._clock()
        )
        return self._advance(checkpoint, DiagnosisStage.SAVED)

    def _close(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        return self._advance(checkpoint, DiagnosisStage.CLOSED)

    def _diagnosis_result(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisResult:
        ledger = ComparisonLedger.model_validate(self._find_kind(checkpoint, "ledger"))
        identity = RunIdentity.model_validate(self._find_kind(checkpoint, "run-identity"))
        report = ReportModel.from_result(
            run_identity=identity,
            ledger=ledger,
            ledger_sha256=canonical_ledger_digest(ledger),
        )
        return DiagnosisResult(report=report, ledger=ledger)

    def _fingerprint(self, checkpoint: DiagnosisCheckpoint) -> EvidenceFingerprint:
        payload = self._find_kind(checkpoint, "fingerprint")
        if payload is None:
            raise DiagnosisStateError("fingerprint is missing from this diagnosis checkpoint")
        return EvidenceFingerprint.model_validate(payload)

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
        return ProposalContext(
            run_id=checkpoint.run_id,
            fingerprint_digest=digest,
            catalogue_digest="sha256:" + catalogue.sha256,
            evidence_ids=evidence_ids,
            catalogue_ids=catalogue.catalogue_ids,
            capability_ids=catalogue.capability_ids,
            held_ids=catalogue.unavailable_ids,
            family_contract_present=catalogue.family_contract_present,
        )

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
