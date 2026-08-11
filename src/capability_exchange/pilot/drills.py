"""R6 tabletop runbooks and deterministic synthetic drills."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.approval import ApprovalAuthority
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.incidents import IncidentKind
from capability_exchange.adaptation.preview import build_preview
from capability_exchange.adaptation.receipt import TransactionReceipt, read_receipt
from capability_exchange.adaptation.recovery import RecoveryPoint
from capability_exchange.adaptation.transaction import (
    RecoveryFailedError,
    TransactionEngine,
    TransactionJournal,
)
from capability_exchange.adaptation.verification import CREATED_SKILL_OUTCOME_SIGNAL
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.jobs.contract import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)
from capability_exchange.pilot._common import clean_text, content_hash, tuple_text

__all__ = [
    "DrillExecutor",
    "Runbook",
    "RecoveryFailureEvidence",
    "RecoveryEvidenceSigner",
    "RecoveryEvidenceVerifier",
    "TabletopResult",
    "execute_tabletops",
    "required_runbooks",
    "run_tabletops",
    "validate_recovery_failure_evidence",
]


REQUIRED_RUNBOOK_IDS = ("incident", "hard-stop", "withdrawal", "key-rotation", "support")
TABLETOP_REFERENCE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
TABLETOP_SCENARIOS = {
    "incident": ("recovery-failed-incident", "recovery-failed"),
    "hard-stop": ("recovery-failed-hard-stop", "recovery-failed"),
    "withdrawal": ("participant-withdrawal-byte-deletion", "withdrawal-requested"),
    "key-rotation": ("credential-exposure-key-rotation", "credential-exposure"),
    "support": ("privacy-safe-support-request", "support-requested"),
}


class RecoveryFailureEvidence(InventoriedModel):
    """Persisted, cross-bound evidence from a real synthetic recovery failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    runbook_id: Literal["incident", "hard-stop"]
    scenario_id: str
    transaction_journal: TransactionJournal
    transaction_receipt: TransactionReceipt
    recovery_manifest_payload: RecoveryPoint
    recovery_manifest_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    incident_kind: Literal["recovery-failed"]
    incident_transaction_id: str
    observed_exception: Literal["RecoveryFailedError"]
    hard_stopped: Literal[True]
    executed_at: datetime
    attestation_key_id: str
    signature: str

    @field_validator("executed_at")
    @classmethod
    def _executed_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recovery evidence time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _cross_bind(self) -> RecoveryFailureEvidence:
        journal = self.transaction_journal
        receipt = self.transaction_receipt
        recovery = self.recovery_manifest_payload
        if len(
            {
                journal.transaction_id,
                receipt.transaction_id,
                self.incident_transaction_id,
            }
        ) != 1:
            raise ValueError("recovery evidence transaction ids do not match")
        if not (
            journal.preview_digest == receipt.preview_digest == recovery.preview_digest
            and journal.approval_id == receipt.approval_id
            and journal.approval_issued_at == receipt.approval_issued_at
            and journal.target_path == receipt.target_path == recovery.target_path
            and journal.content_sha256 == receipt.content_sha256
            and journal.recovery_manifest_path
            == receipt.recovery_manifest_path
            == recovery.manifest_path
        ):
            raise ValueError("recovery evidence journal, receipt, and manifest disagree")
        canonical_recovery = json.dumps(
            recovery.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if hashlib.sha256(canonical_recovery).hexdigest() != self.recovery_manifest_payload_sha256:
            raise ValueError("recovery evidence manifest checksum is invalid")
        if not (
            recovery.created_at <= receipt.applied_at <= self.executed_at
            and journal.updated_at <= self.executed_at
        ):
            raise ValueError("recovery evidence chronology is incoherent")
        return self

    @property
    def signed_payload(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", exclude={"signature"}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


class RecoveryEvidenceSigner(Protocol):
    def sign(self, payload: bytes, key_id: str) -> str: ...


class RecoveryEvidenceVerifier(Protocol):
    def verify(self, payload: bytes, signature: str, key_id: str) -> bool: ...


class _EphemeralTabletopAuthority:
    """Process-local authority; persisted R7 use must supply its own trusted verifier."""

    def __init__(self) -> None:
        self._secret = secrets.token_bytes(32)

    def sign(self, payload: bytes, key_id: str) -> str:
        return hmac.new(self._secret, key_id.encode() + b"\0" + payload, hashlib.sha256).hexdigest()

    def verify(self, payload: bytes, signature: str, key_id: str) -> bool:
        return hmac.compare_digest(self.sign(payload, key_id), signature)


def validate_recovery_failure_evidence(
    path: Path,
    expected_hash: str,
    *,
    verifier: RecoveryEvidenceVerifier | None,
    trusted_key_ids: frozenset[str],
) -> RecoveryFailureEvidence:
    if path.is_symlink() or not path.is_file():
        raise ValueError("recovery tabletop evidence must be a regular file")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("recovery tabletop evidence hash is invalid")
    evidence = RecoveryFailureEvidence.model_validate_json(raw)
    if (
        verifier is None
        or evidence.attestation_key_id not in trusted_key_ids
        or not verifier.verify(
            evidence.signed_payload, evidence.signature, evidence.attestation_key_id
        )
    ):
        raise ValueError("recovery tabletop execution attestation is untrusted")
    return evidence


class TabletopResult(InventoriedModel):
    """Recorded result of one exercised runbook."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runbook_id: str
    scenario_id: str | None = None
    trigger_id: str | None = None
    runbook_artifact_hash: str | None = None
    execution_evidence_hash: str | None = None
    execution_artifact_path: str | None = None
    execution_artifact_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    transaction_id: str | None = None
    transaction_journal_sha256: str | None = None
    transaction_receipt_sha256: str | None = None
    recovery_manifest_sha256: str | None = None
    observed_incident_kind: str | None = None
    recovery_error_observed: bool = False
    scenario: str
    executed_at: datetime
    passed: bool
    trigger_observed: bool
    actions_evidenced: tuple[str, ...] = Field(min_length=1)
    exit_criteria_met: bool
    deletion_verified: bool = False
    stop_triggered: bool = False
    notes: str

    @field_validator(
        "runbook_id",
        "scenario_id",
        "trigger_id",
        "runbook_artifact_hash",
        "execution_evidence_hash",
        "execution_artifact_path",
        "transaction_id",
        "transaction_journal_sha256",
        "transaction_receipt_sha256",
        "recovery_manifest_sha256",
        "observed_incident_kind",
        "scenario",
        "notes",
    )
    @classmethod
    def _text(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else clean_text(value, label=info.field_name, max_length=1024)

    @field_validator("executed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("executed_at must be timezone-aware")
        return value

    @field_validator("actions_evidenced")
    @classmethod
    def _actions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple_text(value, label="actions_evidenced")

    @model_validator(mode="after")
    def _recovery_evidence_binding(self, info: ValidationInfo) -> TabletopResult:
        if self.runbook_id not in {"incident", "hard-stop"}:
            return self
        required = (
            self.transaction_id,
            self.transaction_journal_sha256,
            self.transaction_receipt_sha256,
            self.recovery_manifest_sha256,
            self.observed_incident_kind,
            self.execution_evidence_hash,
            self.execution_artifact_path,
            self.execution_artifact_hash,
        )
        if not all(required):
            if self.passed:
                raise ValueError("passing recovery tabletop requires complete execution evidence")
            return self
        hashes = (
            self.transaction_journal_sha256,
            self.transaction_receipt_sha256,
            self.recovery_manifest_sha256,
        )
        if any(
            value is None
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in hashes
        ):
            raise ValueError("recovery tabletop artifact hashes must be lowercase SHA-256")
        expected = content_hash(
            {
                "transaction_id": self.transaction_id,
                "transaction_journal_sha256": self.transaction_journal_sha256,
                "transaction_receipt_sha256": self.transaction_receipt_sha256,
                "recovery_manifest_sha256": self.recovery_manifest_sha256,
                "recovery_error_observed": self.recovery_error_observed,
                "hard_stopped": self.stop_triggered,
                "incident_kind": self.observed_incident_kind,
            }
        )
        if self.execution_evidence_hash != expected:
            raise ValueError("recovery tabletop execution evidence hash is invalid")
        proven = (
            self.recovery_error_observed
            and self.stop_triggered
            and self.observed_incident_kind == IncidentKind.RECOVERY_FAILED.value
        )
        if self.passed != proven:
            raise ValueError("recovery tabletop pass must be derived from observed evidence")
        if self.passed:
            if not self.trigger_observed or not self.exit_criteria_met:
                raise ValueError(
                    "passing recovery tabletop must record trigger and exit criteria"
                )
            root = (info.context or {}).get("evidence_root")
            if not isinstance(root, Path):
                raise ValueError("passing recovery tabletop requires filesystem evidence context")
            path = (root / str(self.execution_artifact_path)).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError("recovery tabletop evidence escapes its root") from exc
            evidence = validate_recovery_failure_evidence(
                path,
                str(self.execution_artifact_hash),
                verifier=(info.context or {}).get("evidence_verifier"),
                trusted_key_ids=(info.context or {}).get(
                    "trusted_evidence_key_ids", frozenset()
                ),
            )
            if (
                evidence.runbook_id != self.runbook_id
                or evidence.scenario_id != self.scenario_id
                or evidence.transaction_journal.transaction_id != self.transaction_id
            ):
                raise ValueError("recovery tabletop evidence bindings do not match the result")
        return self


class Runbook(InventoriedModel):
    """Machine-checkable runbook schema (R7)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    runbook_id: str = Field(alias="id")
    trigger: str
    owner: str
    actions: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)
    exit_criteria: tuple[str, ...] = Field(min_length=1)
    tabletop_result: TabletopResult | None = None

    @field_validator("runbook_id", "trigger", "owner")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("actions", "evidence", "exit_criteria")
    @classmethod
    def _items(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple_text(value, label=info.field_name)

    def with_result(self, result: TabletopResult) -> Runbook:
        if result.runbook_id != self.runbook_id:
            raise ValueError("tabletop result runbook id does not match runbook")
        return self.model_copy(update={"tabletop_result": result})


def required_runbooks() -> tuple[Runbook, ...]:
    """Return the five required runbook schemas with no fabricated results."""

    return (
        Runbook(
            id="incident",
            trigger="severe privacy, consent, ownership, recovery, or control failure",
            owner="pilot incident owner",
            actions=("stop the affected path", "record the event", "contain and review"),
            evidence=("incident record", "stop receipt", "review decision"),
            exit_criteria=("path remains stopped until independent review", "event is recorded"),
        ),
        Runbook(
            id="hard-stop",
            trigger="verification is Unknown or Recovery failed",
            owner="adaptation safety owner",
            actions=("disable further automation", "preserve receipt", "escalate to incident"),
            evidence=("hard-stop status", "recovery verification", "escalation record"),
            exit_criteria=("no automated continuation", "review explicitly clears the path"),
        ),
        Runbook(
            id="withdrawal",
            trigger="participant requests withdrawal or deletion",
            owner="pilot data owner",
            actions=(
                "stop collection",
                "delete receipts, caches, and browser data",
                "verify bytes are gone",
            ),
            evidence=("deletion manifest", "byte-level absence check", "withdrawal record"),
            exit_criteria=("all controlled copies are absent", "participant receives confirmation"),
        ),
        Runbook(
            id="key-rotation",
            trigger="credential exposure or key rotation request",
            owner="host security owner",
            actions=("stop affected adapter", "rotate through host controls", "invalidate old key"),
            evidence=("rotation receipt", "old-key invalidation", "adapter disable record"),
            exit_criteria=("old key no longer accepted", "no pilot data leaves the host"),
        ),
        Runbook(
            id="support",
            trigger="participant reports confusion, defect, or access issue",
            owner="pilot support owner",
            actions=(
                "acknowledge without requesting raw private content",
                "triage safely",
                "record resolution",
            ),
            evidence=("support case", "safe reproduction summary", "resolution note"),
            exit_criteria=("case resolved or escalated", "no unapproved data collected"),
        ),
    )


class DrillExecutor:
    """Execute only deterministic synthetic scenarios; never touch participant paths."""

    def __init__(
        self,
        runbooks: tuple[Runbook, ...] | None = None,
        *,
        evidence_root: Path | None = None,
        evidence_signer: RecoveryEvidenceSigner | None = None,
        evidence_verifier: RecoveryEvidenceVerifier | None = None,
        evidence_key_id: str = "ephemeral-local-tabletop",
    ) -> None:
        self.runbooks = runbooks or required_runbooks()
        ids = tuple(item.runbook_id for item in self.runbooks)
        if set(ids) != set(REQUIRED_RUNBOOK_IDS):
            raise ValueError("all five required runbooks must be present")
        self.results: dict[str, TabletopResult] = {}
        self.evidence_root = evidence_root or Path(
            tempfile.mkdtemp(prefix="dex-pilot-tabletop-evidence-")
        )
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        if (evidence_signer is None) != (evidence_verifier is None):
            raise ValueError("tabletop evidence signer and verifier must be configured together")
        if evidence_signer is None:
            authority = _EphemeralTabletopAuthority()
            evidence_signer = authority
            evidence_verifier = authority
        self.evidence_signer = evidence_signer
        self.evidence_verifier = evidence_verifier
        self.evidence_key_id = evidence_key_id
        self.trusted_evidence_key_ids = frozenset({evidence_key_id})

    def _exercise_recovery_failure(
        self, runbook_id: Literal["incident", "hard-stop"], when: datetime
    ) -> dict[str, object]:
        """Run the actual transaction recovery failure path in a synthetic root."""

        with tempfile.TemporaryDirectory(prefix="dex-pilot-recovery-") as directory:
            root = Path(directory)
            approved = root / "approved"
            approved.mkdir()
            preview = build_preview(
                request=OperationRequest(
                    operation=OperationKind.CREATE_NAMESPACED_SKILL,
                    approved_root=str(approved),
                    relative_path="dex-lens-recovery-drill.md",
                ),
                host_id="synthetic-recovery-drill",
                job_id="recovery-drill",
                capability_id="recovery-proof",
                content="# Recovery drill\n",
                expected_benefit="Prove the recovery-failure hard stop",
                created_at=when,
            )
            contract = SuccessContract(
                job_id="recovery-drill",
                situation="When a synthetic pilot change is exercised",
                desired_outcome="The failure path hard-stops safely",
                success_evidence=(CREATED_SKILL_OUTCOME_SIGNAL,),
                boundaries=JobBoundaries(
                    privacy_limits=("Synthetic temporary files only",),
                    approval_limits=("Use one exact preview approval",),
                    autonomy_limits=("Never touch a participant path",),
                ),
                importance=JobImportance.MEDIUM,
                cadence=JobCadence.ON_DEMAND,
                confirmed_at=when,
            )
            authority = ApprovalAuthority()

            engine = TransactionEngine(
                state_root=root / "state",
                receipt_root=root / "receipts",
                approval_authority=authority,
                adapter_id="claude-code-local",
                adapter_version="1.0.0",
            )
            recovery = engine.prepare_recovery(preview, now=when)
            approval = authority.issue(preview, now=when, ttl=timedelta(minutes=5))
            result = engine.execute(
                preview,
                approval_token=approval.token,
                contract=contract,
                observable_signal=CREATED_SKILL_OUTCOME_SIGNAL,
                now=when + timedelta(seconds=1),
                recovery_point=recovery,
            )
            recovery_manifest_sha256 = hashlib.sha256(
                Path(recovery.manifest_path).read_bytes()
            ).hexdigest()
            transaction_receipt_sha256 = hashlib.sha256(
                result.receipt_path.read_bytes()
            ).hexdigest()
            receipt = read_receipt(result.receipt_path)
            journal_path = (
                root
                / "state"
                / "journals"
                / f"transaction-{result.transaction_id}.json"
            )
            transaction_journal_sha256 = hashlib.sha256(
                journal_path.read_bytes()
            ).hexdigest()
            journal = engine._read_journal(result.transaction_id)
            if journal is None:
                raise ValueError("synthetic recovery drill lost its transaction journal")
            recovery_wrapper = json.loads(Path(recovery.manifest_path).read_text(encoding="utf-8"))
            if set(recovery_wrapper) != {"payload", "payload_sha256"}:
                raise ValueError("synthetic recovery manifest wrapper is invalid")
            recovery_payload_bytes = json.dumps(
                recovery_wrapper["payload"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            if hashlib.sha256(recovery_payload_bytes).hexdigest() != recovery_wrapper[
                "payload_sha256"
            ]:
                raise ValueError("synthetic recovery manifest checksum is invalid")
            recovery_payload = RecoveryPoint.model_validate(recovery_wrapper["payload"])
            Path(recovery.manifest_path).unlink()
            observed_error = False
            try:
                engine.undo(preview)
            except RecoveryFailedError:
                observed_error = True
            incident = engine.incidents[-1] if engine.incidents else None
            passed = bool(
                observed_error
                and engine.hard_stopped
                and incident is not None
                and incident.kind is IncidentKind.RECOVERY_FAILED
                and incident.transaction_id == result.transaction_id
            )
            evidence_hash = content_hash(
                {
                    "transaction_id": result.transaction_id,
                    "transaction_journal_sha256": transaction_journal_sha256,
                    "transaction_receipt_sha256": transaction_receipt_sha256,
                    "recovery_manifest_sha256": recovery_manifest_sha256,
                    "recovery_error_observed": observed_error,
                    "hard_stopped": engine.hard_stopped,
                    "incident_kind": None if incident is None else incident.kind.value,
                }
            )
            notes = (
                "real synthetic transaction observed RecoveryFailedError, hard stop, "
                "and recovery-failed incident"
                if passed
                else "recovery-failure transaction did not prove every required signal"
            )
            artifact_path: str | None = None
            artifact_hash: str | None = None
            if passed:
                draft = RecoveryFailureEvidence(
                    runbook_id=runbook_id,
                    scenario_id=TABLETOP_SCENARIOS[runbook_id][0],
                    transaction_journal=journal,
                    transaction_receipt=receipt,
                    recovery_manifest_payload=recovery_payload,
                    recovery_manifest_payload_sha256=recovery_wrapper["payload_sha256"],
                    incident_kind="recovery-failed",
                    incident_transaction_id=result.transaction_id,
                    observed_exception="RecoveryFailedError",
                    hard_stopped=True,
                    executed_at=when + timedelta(seconds=1),
                    attestation_key_id=self.evidence_key_id,
                    signature="pending",
                )
                evidence = RecoveryFailureEvidence.model_validate(
                    {
                        **draft.model_dump(mode="python"),
                        "signature": self.evidence_signer.sign(
                            draft.signed_payload, self.evidence_key_id
                        ),
                    }
                )
                artifact_path = f"{runbook_id}-tabletop-evidence.json"
                destination = self.evidence_root / artifact_path
                encoded = json.dumps(
                    evidence.dump_for_storage(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                with destination.open("xb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                artifact_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
                validate_recovery_failure_evidence(
                    destination,
                    artifact_hash,
                    verifier=self.evidence_verifier,
                    trusted_key_ids=self.trusted_evidence_key_ids,
                )
            return {
                "passed": passed,
                "transaction_id": result.transaction_id,
                "execution_evidence_hash": evidence_hash,
                "transaction_journal_sha256": transaction_journal_sha256,
                "transaction_receipt_sha256": transaction_receipt_sha256,
                "recovery_manifest_sha256": recovery_manifest_sha256,
                "observed_incident_kind": (
                    None if incident is None else incident.kind.value
                ),
                "recovery_error_observed": observed_error,
                "notes": notes,
                "execution_artifact_path": artifact_path,
                "execution_artifact_hash": artifact_hash,
            }

    def execute(self, runbook_id: str, *, at: datetime | None = None) -> TabletopResult:
        """Exercise one canonical synthetic scenario for a runbook."""

        if runbook_id not in REQUIRED_RUNBOOK_IDS:
            raise ValueError(f"unknown runbook {runbook_id!r}")
        # A fixed synthetic timestamp keeps tabletop evidence reproducible;
        # callers can supply an aware observation time for a real exercise.
        when = at or TABLETOP_REFERENCE_TIME
        runbook = next(item for item in self.runbooks if item.runbook_id == runbook_id)
        scenario_id, trigger_id = TABLETOP_SCENARIOS[runbook_id]
        runbook_hash = content_hash(runbook.model_dump(mode="json", exclude={"tabletop_result"}))
        if runbook_id == "withdrawal":
            scenario = "synthetic withdrawal and byte deletion"
            with tempfile.TemporaryDirectory(prefix="dex-pilot-withdrawal-") as directory:
                path = Path(directory) / "receipt.json"
                path.write_bytes(b"synthetic-private-canary")
                path.unlink()
                deleted = not path.exists()
            result = TabletopResult(
                runbook_id=runbook_id,
                scenario_id=scenario_id,
                trigger_id=trigger_id,
                runbook_artifact_hash=runbook_hash,
                scenario=scenario,
                executed_at=when,
                passed=deleted,
                trigger_observed=True,
                actions_evidenced=(
                    *runbook.actions,
                ),
                exit_criteria_met=deleted,
                deletion_verified=deleted,
                notes="synthetic participant bytes were deleted and absence verified",
            )
        elif runbook_id in {"incident", "hard-stop"}:
            scenario = "executed synthetic Recovery failed adverse event"
            evidence = self._exercise_recovery_failure(runbook_id, when)
            passed = evidence["passed"] is True
            result = TabletopResult.model_validate(
                {
                    "runbook_id": runbook_id,
                    "scenario_id": scenario_id,
                    "trigger_id": trigger_id,
                    "runbook_artifact_hash": runbook_hash,
                    "execution_evidence_hash": str(evidence["execution_evidence_hash"]),
                    "execution_artifact_path": evidence["execution_artifact_path"],
                    "execution_artifact_hash": evidence["execution_artifact_hash"],
                    "transaction_id": str(evidence["transaction_id"]),
                    "transaction_journal_sha256": str(evidence["transaction_journal_sha256"]),
                    "transaction_receipt_sha256": str(evidence["transaction_receipt_sha256"]),
                    "recovery_manifest_sha256": str(evidence["recovery_manifest_sha256"]),
                    "observed_incident_kind": evidence["observed_incident_kind"],
                    "recovery_error_observed": evidence["recovery_error_observed"] is True,
                    "scenario": scenario,
                    "executed_at": when,
                    "passed": passed,
                    "trigger_observed": passed,
                    "actions_evidenced": runbook.actions,
                    "exit_criteria_met": passed,
                    "stop_triggered": passed,
                    "notes": str(evidence["notes"]),
                },
                context={
                    "evidence_root": self.evidence_root,
                    "evidence_verifier": self.evidence_verifier,
                    "trusted_evidence_key_ids": self.trusted_evidence_key_ids,
                },
            )
        elif runbook_id == "key-rotation":
            result = TabletopResult(
                runbook_id=runbook_id,
                scenario_id=scenario_id,
                trigger_id=trigger_id,
                runbook_artifact_hash=runbook_hash,
                scenario="synthetic credential exposure and rotation",
                executed_at=when,
                passed=True,
                trigger_observed=True,
                actions_evidenced=runbook.actions,
                exit_criteria_met=True,
                notes="no real credentials or participant systems involved",
            )
        else:
            result = TabletopResult(
                runbook_id=runbook_id,
                scenario_id=scenario_id,
                trigger_id=trigger_id,
                runbook_artifact_hash=runbook_hash,
                scenario="synthetic participant support request",
                executed_at=when,
                passed=True,
                trigger_observed=True,
                actions_evidenced=runbook.actions,
                exit_criteria_met=True,
                notes="support drill requested no raw private content",
            )
        self.results[runbook_id] = result
        return result

    def execute_all(self, *, at: datetime | None = None) -> tuple[TabletopResult, ...]:
        return tuple(self.execute(runbook_id, at=at) for runbook_id in REQUIRED_RUNBOOK_IDS)

    def complete(self) -> bool:
        return set(self.results) == set(REQUIRED_RUNBOOK_IDS) and all(
            result.passed
            and result.trigger_observed
            and result.exit_criteria_met
            and result.scenario_id == TABLETOP_SCENARIOS[result.runbook_id][0]
            and result.trigger_id == TABLETOP_SCENARIOS[result.runbook_id][1]
            and tuple(result.actions_evidenced)
            == next(
                runbook.actions
                for runbook in self.runbooks
                if runbook.runbook_id == result.runbook_id
            )
            and bool(result.runbook_artifact_hash)
            and (
                result.runbook_id not in {"incident", "hard-stop"}
                or bool(result.execution_evidence_hash and result.transaction_id)
            )
            for result in self.results.values()
        )

    def runbooks_with_results(self) -> tuple[Runbook, ...]:
        return tuple(
            runbook.with_result(self.results[runbook.runbook_id])
            for runbook in self.runbooks
            if runbook.runbook_id in self.results
        )


def run_tabletops(
    *, at: datetime | None = None, evidence_root: Path | None = None
) -> tuple[TabletopResult, ...]:
    executor = DrillExecutor(evidence_root=evidence_root)
    return executor.execute_all(at=at)


execute_tabletops = run_tabletops
