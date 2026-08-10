"""Private-value-free, standard JSON M4 transaction receipts (T5/T6)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import ConfigDict, Field, field_validator

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
    operation: OperationKind
    target_path: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_id: str
    adapter_version: str
    recovery_manifest_path: str
    applied_at: datetime
    verification_verdict: VerificationVerdict
    evidence_level: EvidenceLevel

    @field_validator("applied_at")
    @classmethod
    def _applied_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("applied_at must be timezone-aware")
        return value


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

