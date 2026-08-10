"""Private-value-free, standard JSON M4 transaction receipts (T5/T6)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.verification import VerificationVerdict
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence import EvidenceLevel

__all__ = ["TransactionReceipt", "read_receipt", "write_receipt"]


class TransactionReceipt(InventoriedModel):
    """Durable local receipt containing structure and digests, never source bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transaction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    approval_issued_at: datetime
    operation: OperationKind
    target_path: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_id: str
    adapter_version: str
    recovery_manifest_path: str
    applied_at: datetime
    verification_verdict: VerificationVerdict
    evidence_level: EvidenceLevel
    verification_procedure_id: str | None = None
    verification_evidence_reference: str | None = None
    verification_evidence_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    verification_contract_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    verification_observed_at: datetime | None = None

    @field_validator("approval_issued_at", "applied_at", "verification_observed_at")
    @classmethod
    def _applied_at_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approval_issued_at and applied_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _working_requires_outcome_evidence(self) -> TransactionReceipt:
        if self.verification_verdict in {
            VerificationVerdict.WORKING,
            VerificationVerdict.PARTIAL,
        } and not all(
            (
                self.verification_procedure_id,
                self.verification_evidence_reference,
                self.verification_evidence_sha256,
                self.verification_contract_digest,
                self.verification_observed_at,
            )
        ):
            raise ValueError("Working or Partial receipt requires outcome-procedure evidence")
        return self


def write_receipt(receipt: TransactionReceipt, directory: Path) -> Path:
    """Write one canonical, create-only JSON receipt and fsync it."""

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"receipt-{receipt.transaction_id}.json"
    payload = receipt.dump_for_storage()
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def read_receipt(path: Path) -> TransactionReceipt:
    return TransactionReceipt.model_validate_json(path.read_text(encoding="utf-8"))
