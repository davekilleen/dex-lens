"""Test-visible M4 incident triggers for fail-closed runbooks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["IncidentKind", "IncidentRecord"]


class IncidentKind(StrEnum):
    UNVERIFIED = "unverified"
    RECOVERY_FAILED = "recovery-failed"
    RECEIPT_FAILED = "receipt-failed"
    TRANSACTION_CONFLICT = "transaction-conflict"


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    kind: IncidentKind
    transaction_id: str
    detail: str

