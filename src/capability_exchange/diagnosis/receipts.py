"""Local decision and share receipts. Prose cannot invent completion."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "DecisionReceipt",
    "DecisionState",
    "DestinationClass",
    "RecommendationDecision",
    "ShareReceipt",
    "ShareState",
]

_RUN_ID = re.compile(r"^run:[a-z0-9]{16,64}$")
_CATALOGUE_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PREVIEW_RUN_ID = "run:" + "0" * 16
_PREVIEW_SESSION = "session:preview"


class DecisionState(StrEnum):
    """Closed recommendation fate. Taken requires a local receipt."""

    OFFERED = "offered"
    CHOSEN = "chosen"
    COMPLETED = "completed"


class ShareState(StrEnum):
    """Closed share fate. Shared requires destination, digest, and response."""

    NOT_OFFERED = "not-offered"
    OFFERED = "offered"
    PREVIEWED = "previewed"
    SENT = "sent"


class DestinationClass(StrEnum):
    """Bounded classes a confirmed share may name. Diagnosis does not send."""

    CONTRIBUTION_INTAKE = "contribution-intake"


def _require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be a timezone-aware UTC timestamp")
    return value


class _ClosedReceiptModel(InventoriedModel):
    """Inventoried model that keeps validators on copy and construct routes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        values = {field_name: getattr(self, field_name) for field_name in type(self).model_fields}
        if update:
            values.update(update)
        return type(self).model_validate(values)

    def copy(self, **kwargs: object) -> Self:
        raise TypeError(f"copy() is disabled for {type(self).__name__}; use validated model_copy()")

    @classmethod
    def model_construct(
        cls,
        _fields_set: set[str] | None = None,
        **values: object,
    ) -> Self:
        return cls.model_validate(values)


class DecisionReceipt(_ClosedReceiptModel):
    """Local consent-surface proof for one recommendation fate."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    catalogue_id: str = Field(pattern=_CATALOGUE_ID.pattern)
    created_at: datetime
    session_receipt_id: str = Field(min_length=8, max_length=120)
    state: DecisionState

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "created_at")


class RecommendationDecision(_ClosedReceiptModel):
    """One recommendation fate. Chosen and completed need a local receipt."""

    catalogue_id: str = Field(pattern=_CATALOGUE_ID.pattern)
    state: DecisionState
    receipt: DecisionReceipt | None = None

    @model_validator(mode="after")
    def _taken_requires_receipt(self) -> Self:
        if self.state in (DecisionState.CHOSEN, DecisionState.COMPLETED) and self.receipt is None:
            raise ValueError("chosen or completed decisions require a local decision receipt")
        if self.receipt is None:
            return self
        if self.receipt.catalogue_id != self.catalogue_id:
            raise ValueError("decision receipt catalogue_id must match the recommendation")
        if self.receipt.state is not self.state:
            raise ValueError("decision receipt state must match the recommendation")
        return self


class ShareReceipt(_ClosedReceiptModel):
    """Local proof of a share preview or a confirmed send. Preview is not sent."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    disclosure_sha256: str = Field(pattern=_HEX_SHA256.pattern)
    created_at: datetime
    session_receipt_id: str = Field(min_length=8, max_length=120)
    state: ShareState
    destination_class: DestinationClass | None = None
    response_receipt_digest: str | None = Field(default=None, pattern=_SHA256.pattern)

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "created_at")

    @model_validator(mode="after")
    def _sent_is_fully_bound(self) -> Self:
        if self.state is ShareState.NOT_OFFERED:
            raise ValueError("a share receipt cannot record not-offered")
        if self.state is ShareState.SENT:
            if self.destination_class is None:
                raise ValueError("sent share receipts require a destination class")
            if self.response_receipt_digest is None:
                raise ValueError("sent share receipts require a response receipt digest")
        elif self.response_receipt_digest is not None:
            raise ValueError("response receipt digest is only valid for sent share receipts")
        return self

    @property
    def was_sent(self) -> bool:
        return (
            self.state is ShareState.SENT
            and self.destination_class is not None
            and self.response_receipt_digest is not None
        )

    @classmethod
    def preview(
        cls,
        *,
        disclosure_sha256: str,
        created_at: datetime,
        run_id: str = _PREVIEW_RUN_ID,
        session_receipt_id: str = _PREVIEW_SESSION,
    ) -> Self:
        return cls(
            run_id=run_id,
            disclosure_sha256=disclosure_sha256,
            created_at=created_at,
            session_receipt_id=session_receipt_id,
            state=ShareState.PREVIEWED,
        )

    @classmethod
    def sent(
        cls,
        *,
        disclosure_sha256: str,
        created_at: datetime,
        destination_class: DestinationClass,
        response_receipt_digest: str,
        run_id: str,
        session_receipt_id: str,
    ) -> Self:
        return cls(
            run_id=run_id,
            disclosure_sha256=disclosure_sha256,
            created_at=created_at,
            session_receipt_id=session_receipt_id,
            state=ShareState.SENT,
            destination_class=destination_class,
            response_receipt_digest=response_receipt_digest,
        )
