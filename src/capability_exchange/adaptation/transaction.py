"""Crash-recoverable M4 transaction and bounded undo (G3, T1–T9)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import ConfigDict, field_validator

from capability_exchange.adaptation.approval import ApprovalAuthority
from capability_exchange.adaptation.incidents import IncidentKind, IncidentRecord
from capability_exchange.adaptation.preview import (
    AdaptationPreview,
    assert_preview_current,
)
from capability_exchange.adaptation.receipt import (
    TransactionReceipt,
    read_receipt,
    write_receipt,
)
from capability_exchange.adaptation.recovery import (
    RecoveryConflictError,
    RecoveryUnavailableError,
    create_recovery_point,
    restore_absent_target,
    validate_recovery_point,
)
from capability_exchange.adaptation.verification import (
    VerificationResult,
    VerificationVerdict,
    verify_created_skill,
)
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.jobs.contract import SuccessContract

__all__ = [
    "AutomationHardStoppedError",
    "InjectedCrash",
    "JournalState",
    "RecoveryFailedError",
    "TransactionConflictError",
    "TransactionEngine",
    "TransactionFailedError",
    "TransactionJournal",
    "TransactionResult",
    "UndoConflictError",
    "UndoResult",
    "UndoStatus",
]


class InjectedCrash(BaseException):
    """Fault-injection stand-in for an uncatchable process death."""


class TransactionFailedError(Exception):
    """The change did not complete and was rolled back."""


class TransactionConflictError(Exception):
    """Recovery found bytes it cannot prove belong to this transaction."""


class AutomationHardStoppedError(Exception):
    """The session cannot perform another automated change."""


class RecoveryFailedError(Exception):
    """Undo cannot prove a safe restoration path."""


class UndoConflictError(Exception):
    """Undo would clobber later unrelated work."""


class JournalState(StrEnum):
    APPROVED = "approved"
    RECOVERY_READY = "recovery-ready"
    APPLYING = "applying"
    APPLIED = "applied"
    VERIFIED = "verified"
    HARD_STOPPED = "hard-stopped"
    ROLLED_BACK = "rolled-back"
    UNDONE = "undone"


class TransactionJournal(InventoriedModel):
    """Durable minimal state needed to reconcile a killed process."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transaction_id: str
    state: JournalState
    preview_digest: str
    approval_id: str
    target_path: str
    content_sha256: str
    recovery_manifest_path: str
    receipt_path: str
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _updated_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("journal updated_at must be timezone-aware")
        return value


@dataclass(frozen=True, slots=True)
class TransactionResult:
    transaction_id: str
    receipt_path: Path
    verification: VerificationResult | None
    hard_stopped: bool


class UndoStatus(StrEnum):
    UNDONE = "undone"
    ALREADY_UNDONE = "already-undone"


@dataclass(frozen=True, slots=True)
class UndoResult:
    transaction_id: str
    target_path: Path
    status: UndoStatus


FaultHook = Callable[[str], None]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class TransactionEngine:
    """Single-session journaled create-only transaction engine."""

    def __init__(
        self,
        *,
        state_root: Path,
        receipt_root: Path,
        approval_authority: ApprovalAuthority,
        adapter_id: str,
        adapter_version: str,
        fault_hook: FaultHook | None = None,
    ) -> None:
        self.state_root = state_root
        self.receipt_root = receipt_root
        self.approval_authority = approval_authority
        self.adapter_id = adapter_id
        self.adapter_version = adapter_version
        self.fault_hook = fault_hook
        self._hard_stopped = False
        self._incidents: list[IncidentRecord] = []

    @property
    def hard_stopped(self) -> bool:
        return self._hard_stopped

    @property
    def incidents(self) -> tuple[IncidentRecord, ...]:
        return tuple(self._incidents)

    def _checkpoint(self, name: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(name)

    @staticmethod
    def _transaction_id(preview: AdaptationPreview) -> str:
        return preview.preview_digest[:32]

    def _journal_path(self, transaction_id: str) -> Path:
        return self.state_root / "journals" / f"transaction-{transaction_id}.json"

    def _record_incident(
        self, kind: IncidentKind, transaction_id: str, detail: str
    ) -> None:
        self._incidents.append(
            IncidentRecord(kind=kind, transaction_id=transaction_id, detail=detail)
        )

    def _write_journal(self, journal: TransactionJournal) -> None:
        path = self._journal_path(journal.transaction_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = journal.dump_for_storage()
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        wrapper = json.dumps(
            {
                "payload": json.loads(canonical),
                "payload_sha256": _sha256(canonical),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as handle:
            handle.write(wrapper)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _read_journal(self, transaction_id: str) -> TransactionJournal | None:
        path = self._journal_path(transaction_id)
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            if set(wrapper) != {"payload", "payload_sha256"}:
                raise ValueError("unexpected journal fields")
            canonical = json.dumps(
                wrapper["payload"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            if _sha256(canonical) != wrapper["payload_sha256"]:
                raise ValueError("journal checksum mismatch")
            return TransactionJournal.model_validate(wrapper["payload"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._hard_stopped = True
            self._record_incident(
                IncidentKind.TRANSACTION_CONFLICT,
                transaction_id,
                "transaction journal is missing, truncated, or tampered",
            )
            raise TransactionConflictError("transaction journal is invalid") from exc

    def _advance(
        self,
        journal: TransactionJournal,
        state: JournalState,
        now: datetime,
        **updates: object,
    ) -> TransactionJournal:
        next_journal = TransactionJournal.model_validate(
            {
                **journal.model_dump(mode="python"),
                **updates,
                "state": state,
                "updated_at": now,
            }
        )
        self._write_journal(next_journal)
        return next_journal

    def _validate_journal_binding(
        self, journal: TransactionJournal, preview: AdaptationPreview
    ) -> None:
        if (
            journal.preview_digest != preview.preview_digest
            or journal.target_path != preview.target_path
            or journal.content_sha256 != preview.content_sha256
        ):
            self._hard_stopped = True
            self._record_incident(
                IncidentKind.TRANSACTION_CONFLICT,
                journal.transaction_id,
                "journal is bound to different preview bytes or scope",
            )
            raise TransactionConflictError("journal does not match the exact preview")

    def _apply_or_reconcile(
        self,
        journal: TransactionJournal,
        preview: AdaptationPreview,
        now: datetime,
    ) -> TransactionJournal:
        target = Path(preview.target_path)
        desired = preview.content.encode("utf-8")
        if journal.state is JournalState.RECOVERY_READY:
            assert_preview_current(preview)
            journal = self._advance(journal, JournalState.APPLYING, now)

        if journal.state is not JournalState.APPLYING:
            return journal

        if os.path.lexists(target):
            if target.is_symlink() or not target.is_file():
                return self._conflict(journal, "target shape changed during apply")
            current = target.read_bytes()
            if current == desired:
                return self._advance(journal, JournalState.APPLIED, now)
            if current and len(current) < len(desired) and desired.startswith(current):
                target.unlink()
            else:
                return self._conflict(
                    journal, "target contains bytes not provably written by this transaction"
                )

        split = max(1, len(desired) // 2)
        with target.open("xb") as handle:
            handle.write(desired[:split])
            handle.flush()
            os.fsync(handle.fileno())
            self._checkpoint("mid-write")
            handle.write(desired[split:])
            handle.flush()
            os.fsync(handle.fileno())
            self._checkpoint("before-commit")
        return self._advance(journal, JournalState.APPLIED, now)

    def _conflict(self, journal: TransactionJournal, detail: str):
        self._hard_stopped = True
        self._record_incident(
            IncidentKind.TRANSACTION_CONFLICT, journal.transaction_id, detail
        )
        raise TransactionConflictError(detail)

    def _completed_result(self, journal: TransactionJournal) -> TransactionResult:
        if not journal.receipt_path:
            return self._conflict(journal, "completed journal has no receipt path")
        receipt_path = Path(journal.receipt_path)
        try:
            receipt = read_receipt(receipt_path)
        except (OSError, ValueError) as exc:
            self._hard_stopped = True
            self._record_incident(
                IncidentKind.RECEIPT_FAILED,
                journal.transaction_id,
                "completed transaction receipt is unreadable",
            )
            raise TransactionConflictError("completed receipt is unreadable") from exc
        if receipt.preview_digest != journal.preview_digest:
            return self._conflict(journal, "receipt does not match transaction journal")
        hard_stopped = journal.state is JournalState.HARD_STOPPED
        self._hard_stopped = self._hard_stopped or hard_stopped
        return TransactionResult(
            transaction_id=journal.transaction_id,
            receipt_path=receipt_path,
            verification=None,
            hard_stopped=hard_stopped,
        )

    def execute(
        self,
        preview: AdaptationPreview,
        *,
        approval_token: str,
        contract: SuccessContract,
        observable_signal: str,
        now: datetime,
    ) -> TransactionResult:
        transaction_id = self._transaction_id(preview)
        journal = self._read_journal(transaction_id)
        if journal is not None:
            self._validate_journal_binding(journal, preview)
            if journal.state in {
                JournalState.VERIFIED,
                JournalState.HARD_STOPPED,
                JournalState.UNDONE,
            }:
                return self._completed_result(journal)
            if journal.state is JournalState.ROLLED_BACK:
                raise TransactionFailedError("transaction previously rolled back")
        elif self._hard_stopped:
            raise AutomationHardStoppedError(
                "automation is hard-stopped for this session after an incident"
            )
        else:
            approval = self.approval_authority.consume(
                approval_token, preview, now=now
            )
            journal = TransactionJournal(
                transaction_id=transaction_id,
                state=JournalState.APPROVED,
                preview_digest=preview.preview_digest,
                approval_id=approval.approval_id,
                target_path=preview.target_path,
                content_sha256=preview.content_sha256,
                recovery_manifest_path="",
                receipt_path="",
                updated_at=now,
            )
            self._write_journal(journal)

        if self._hard_stopped:
            raise AutomationHardStoppedError(
                "automation is hard-stopped for this session after an incident"
            )

        if journal.state is JournalState.APPROVED:
            self._checkpoint("before-recovery")
            assert_preview_current(preview)
            recovery = create_recovery_point(
                preview,
                state_root=self.state_root / "recovery",
                created_at=now,
            )
            journal = self._advance(
                journal,
                JournalState.RECOVERY_READY,
                now,
                recovery_manifest_path=recovery.manifest_path,
            )

        journal = self._apply_or_reconcile(journal, preview, now)
        if journal.state is JournalState.APPLIED:
            self._checkpoint("after-commit-before-receipt")
            verification = verify_created_skill(
                preview,
                contract,
                observable_signal=observable_signal,
                verified_at=now,
            )
            receipt = TransactionReceipt(
                transaction_id=transaction_id,
                preview_digest=preview.preview_digest,
                approval_id=journal.approval_id,
                operation=preview.operation,
                target_path=preview.target_path,
                content_sha256=preview.content_sha256,
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                recovery_manifest_path=journal.recovery_manifest_path,
                applied_at=now,
                verification_verdict=verification.verdict,
                evidence_level=verification.evidence_level,
            )
            try:
                receipt_path = write_receipt(receipt, self.receipt_root)
            except FileExistsError:
                receipt_path = self.receipt_root / f"receipt-{transaction_id}.json"
                existing = read_receipt(receipt_path)
                if existing != receipt:
                    return self._conflict(journal, "existing receipt does not match")
            except OSError as exc:
                try:
                    point = validate_recovery_point(
                        Path(journal.recovery_manifest_path), require_prior_state=False
                    )
                    restore_absent_target(
                        point, expected_applied_sha256=preview.content_sha256
                    )
                    self._advance(journal, JournalState.ROLLED_BACK, now)
                except (RecoveryUnavailableError, RecoveryConflictError) as recovery_exc:
                    self._hard_stopped = True
                    self._record_incident(
                        IncidentKind.RECOVERY_FAILED,
                        transaction_id,
                        "receipt failed and rollback could not be proven",
                    )
                    raise RecoveryFailedError(
                        "receipt failed and recovery also failed"
                    ) from recovery_exc
                self._record_incident(
                    IncidentKind.RECEIPT_FAILED,
                    transaction_id,
                    "receipt could not be written; exact change rolled back",
                )
                raise TransactionFailedError(
                    "receipt write failed; exact applied file was rolled back"
                ) from exc

            terminal = JournalState.VERIFIED
            hard_stopped = verification.verdict is VerificationVerdict.UNKNOWN
            if hard_stopped:
                terminal = JournalState.HARD_STOPPED
                self._hard_stopped = True
                self._record_incident(
                    IncidentKind.UNVERIFIED,
                    transaction_id,
                    "verification is Unknown/Unverified; later automation stopped",
                )
            journal = self._advance(
                journal,
                terminal,
                now,
                receipt_path=str(receipt_path),
            )
            return TransactionResult(
                transaction_id=transaction_id,
                receipt_path=receipt_path,
                verification=verification,
                hard_stopped=hard_stopped,
            )

        return self._completed_result(journal)

    def undo(self, preview: AdaptationPreview) -> UndoResult:
        transaction_id = self._transaction_id(preview)
        journal = self._read_journal(transaction_id)
        if journal is None or not journal.recovery_manifest_path:
            self._hard_stopped = True
            self._record_incident(
                IncidentKind.RECOVERY_FAILED,
                transaction_id,
                "recovery manifest is missing",
            )
            raise RecoveryFailedError("recovery manifest is missing")
        self._validate_journal_binding(journal, preview)
        if journal.state is JournalState.UNDONE and not os.path.lexists(
            preview.target_path
        ):
            return UndoResult(
                transaction_id=transaction_id,
                target_path=Path(preview.target_path),
                status=UndoStatus.ALREADY_UNDONE,
            )
        try:
            point = validate_recovery_point(
                Path(journal.recovery_manifest_path), require_prior_state=False
            )
            restore_absent_target(
                point, expected_applied_sha256=preview.content_sha256
            )
        except RecoveryConflictError as exc:
            self._hard_stopped = True
            self._record_incident(
                IncidentKind.TRANSACTION_CONFLICT,
                transaction_id,
                "undo conflicts with later unrelated work",
            )
            raise UndoConflictError("undo conflicts with later unrelated work") from exc
        except RecoveryUnavailableError as exc:
            self._hard_stopped = True
            self._record_incident(
                IncidentKind.RECOVERY_FAILED,
                transaction_id,
                "recovery manifest could not be validated",
            )
            raise RecoveryFailedError("recovery manifest could not be validated") from exc
        self._advance(journal, JournalState.UNDONE, journal.updated_at)
        return UndoResult(
            transaction_id=transaction_id,
            target_path=Path(preview.target_path),
            status=UndoStatus.UNDONE,
        )
