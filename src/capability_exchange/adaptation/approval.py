"""Fresh, exact, single-use adaptation approval (T3)."""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.adaptation.preview import AdaptationPreview
from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "AdaptationApproval",
    "ApprovalAuthority",
    "ApprovalExpiredError",
    "ApprovalMismatchError",
    "ApprovalReplayError",
    "IssuedApproval",
]


class ApprovalMismatchError(Exception):
    """Approval is unknown or bound to different preview fields."""


class ApprovalExpiredError(Exception):
    """Approval is no longer fresh."""


class ApprovalReplayError(Exception):
    """Approval has already authorized its single change."""


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AdaptationApproval(InventoriedModel):
    """Persistable approval record; the bearer token itself is never a field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    token_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    host_id: str
    job_id: str
    capability_id: str
    target_path: str
    issued_at: datetime
    expires_at: datetime
    limits: tuple[str, ...]

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approval timestamps must be timezone-aware")
        return value


@dataclass(frozen=True, slots=True)
class IssuedApproval:
    token: str
    record: AdaptationApproval


class ApprovalAuthority:
    """In-memory single-session token authority with atomic consumption."""

    def __init__(self) -> None:
        self._records: dict[str, AdaptationApproval] = {}
        self._consumed: set[str] = set()
        self._lock = threading.Lock()

    def issue(
        self, preview: AdaptationPreview, *, now: datetime, ttl: timedelta
    ) -> IssuedApproval:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("approval issue time must be timezone-aware")
        if ttl <= timedelta(0):
            raise ValueError("approval ttl must be positive")
        token = secrets.token_urlsafe(32)
        digest = _token_digest(token)
        record = AdaptationApproval(
            approval_id=digest[:24],
            token_digest=digest,
            preview_digest=preview.preview_digest,
            host_id=preview.host_id,
            job_id=preview.job_id,
            capability_id=preview.capability_id,
            target_path=preview.target_path,
            issued_at=now,
            expires_at=now + ttl,
            limits=("one-change", "create-only", "no-network"),
        )
        with self._lock:
            self._records[digest] = record
        return IssuedApproval(token=token, record=record)

    def consume(
        self, token: str, preview: AdaptationPreview, *, now: datetime
    ) -> AdaptationApproval:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("approval consumption time must be timezone-aware")
        digest = _token_digest(token)
        with self._lock:
            if digest in self._consumed:
                raise ApprovalReplayError("approval token was already consumed")
            record = self._records.get(digest)
            if record is None:
                raise ApprovalMismatchError("unknown approval token")
            if now >= record.expires_at:
                raise ApprovalExpiredError("approval expired before the change began")
            expected = (
                preview.preview_digest,
                preview.host_id,
                preview.job_id,
                preview.capability_id,
                preview.target_path,
            )
            actual = (
                record.preview_digest,
                record.host_id,
                record.job_id,
                record.capability_id,
                record.target_path,
            )
            if actual != expected:
                raise ApprovalMismatchError(
                    "approval is bound to a different preview, host, job, capability, or target"
                )
            self._consumed.add(digest)
            return record

