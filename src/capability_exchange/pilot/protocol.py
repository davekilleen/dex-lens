"""Versioned pilot protocol and immutable consent records (R6).

The protocol hash is calculated from the substantive protocol only.  Derived
metadata (the hash itself and creation timestamp) is excluded, which makes the
hash stable when the same protocol is loaded from JSON on another machine.
Enrollment must cite both the version and this exact hash; a protocol label
alone is never enough.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.pilot._common import (
    clean_text,
    content_hash,
    tuple_text,
    utc_now,
)

__all__ = [
    "Consent",
    "ConsentRecord",
    "ConsentStatus",
    "PilotConsentRecord",
    "PilotProtocol",
    "Protocol",
    "ProtocolClause",
    "ProtocolError",
    "ProtocolStratum",
    "canonical_protocol_hash",
]


class ProtocolError(ValueError):
    """A protocol or enrollment precondition could not be proven."""


class ConsentStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class ProtocolStratum(InventoriedModel):
    """One declared cohort stratum and its permitted range."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    stratum_id: str = Field(alias="id")
    label: str
    minimum: int = Field(ge=0)
    maximum: int = Field(ge=0)
    description: str

    @field_validator("stratum_id")
    @classmethod
    def _id(cls, value: str) -> str:
        return clean_text(value, label="stratum_id", max_length=64)

    @field_validator("label", "description")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name)

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.maximum < self.minimum:
            raise ValueError("protocol stratum maximum must be >= minimum")
        return self


class ProtocolClause(InventoriedModel):
    """A machine-readable procedure clause attached to the protocol."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    owner: str
    trigger: str
    actions: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)
    exit_criteria: tuple[str, ...] = Field(min_length=1)

    @field_validator("owner", "trigger")
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name)

    @field_validator("actions", "evidence", "exit_criteria")
    @classmethod
    def _items(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple_text(value, label=info.field_name)


class PilotConsentRecord(InventoriedModel):
    """Immutable participant consent bound to one protocol hash."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    participant_id: str
    protocol_version: str
    protocol_hash: str
    stratum_id: str
    evidence_scope: tuple[str, ...] = Field(min_length=1)
    consented_at: datetime
    status: ConsentStatus = ConsentStatus.ACTIVE
    withdrawal_requested_at: datetime | None = None
    deletion_confirmed_at: datetime | None = None

    @field_validator("participant_id", "protocol_version", "protocol_hash", "stratum_id")
    @classmethod
    def _bounded(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("evidence_scope")
    @classmethod
    def _scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple_text(value, label="evidence_scope")

    @field_validator("consented_at", "withdrawal_requested_at", "deletion_confirmed_at")
    @classmethod
    def _aware(cls, value: datetime | None, info: Any) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _withdrawal_fields(self) -> Self:
        if self.status is ConsentStatus.WITHDRAWN and self.withdrawal_requested_at is None:
            raise ValueError("withdrawn consent must record withdrawal_requested_at")
        return self

    def withdraw(self, *, at: datetime | None = None) -> PilotConsentRecord:
        """Return a new withdrawn record; the original remains immutable."""

        when = at or utc_now()
        if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
            raise ValueError("withdrawal time must be timezone-aware")
        return PilotConsentRecord(
            participant_id=self.participant_id,
            protocol_version=self.protocol_version,
            protocol_hash=self.protocol_hash,
            stratum_id=self.stratum_id,
            evidence_scope=self.evidence_scope,
            consented_at=self.consented_at,
            status=ConsentStatus.WITHDRAWN,
            withdrawal_requested_at=when,
            deletion_confirmed_at=self.deletion_confirmed_at,
        )

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if update:
            raise ProtocolError("consent records are immutable; withdraw creates a new record")
        return super().model_copy(update=update, deep=deep)


class PilotProtocol(InventoriedModel):
    """The versioned R6 protocol that must precede participant inspection."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    protocol_version: str = Field(alias="version")
    strata: tuple[ProtocolStratum, ...] = Field(min_length=1)
    exclusions: tuple[str, ...] = ()
    evidence_consent: ProtocolClause
    withdrawal: ProtocolClause
    deletion: ProtocolClause
    adverse_event_reporting: ProtocolClause
    incident_response: ProtocolClause
    red_team_result_ids: tuple[str, ...] = ()
    red_team_complete: bool = False
    synthetic_only: bool = False
    participant_evidence: str | None = None
    independent_signoff: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    content_hash: str | None = None

    @field_validator("protocol_version")
    @classmethod
    def _version(cls, value: str) -> str:
        return clean_text(value, label="protocol_version", max_length=64)

    @field_validator("exclusions", "red_team_result_ids")
    @classmethod
    def _lists(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple_text(value, label=info.field_name)

    @field_validator("participant_evidence", "independent_signoff")
    @classmethod
    def _optional_marker(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else clean_text(value, label=info.field_name, max_length=1024)

    @field_validator("created_at")
    @classmethod
    def _created_at_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _hash_and_strata(self) -> Self:
        if len({item.stratum_id for item in self.strata}) != len(self.strata):
            raise ValueError("protocol strata ids must be unique")
        expected = self.canonical_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("protocol content_hash does not match canonical protocol")
        if self.content_hash is None:
            object.__setattr__(self, "content_hash", expected)
        return self

    def canonical_payload(self) -> dict[str, Any]:
        """Substantive protocol fields, excluding derived hash and timestamp."""

        return self.model_dump(
            mode="json",
            by_alias=False,
            exclude={"content_hash", "created_at"},
        )

    def canonical_hash(self) -> str:
        return content_hash(self.canonical_payload())

    @property
    def protocol_hash(self) -> str:
        """Alias used by consent and enrollment callers."""

        return self.content_hash or self.canonical_hash()

    @property
    def hash(self) -> str:
        return self.protocol_hash

    def stratum(self, stratum_id: str) -> ProtocolStratum:
        for item in self.strata:
            if item.stratum_id == stratum_id:
                return item
        raise ProtocolError(
            f"stratum {stratum_id!r} is not declared by protocol {self.protocol_version}"
        )

    def assert_red_team_ready(self) -> None:
        """Refuse participant use without attached, complete synthetic evidence."""

        if not self.red_team_complete or not self.red_team_result_ids:
            raise ProtocolError(
                "pilot protocol has no complete synthetic red-team result; "
                "participant systems must not be touched"
            )

    def attach_red_team(self, report: Any) -> PilotProtocol:
        """Return a protocol bound to an observed :class:`RedTeamReport`.

        The report is intentionally accepted by structural attributes to keep
        this module independent from the red-team runner.  A non-complete
        report can be attached for audit, but it never unlocks enrollment.
        """

        complete = bool(getattr(report, "complete", False))
        cases = tuple(getattr(report, "cases", ()))
        result_ids = tuple(
            f"{getattr(case, 'gate', 'unknown')}:{getattr(case, 'test_id', 'unknown')}"
            for case in cases
        )
        return self.model_copy(
            update={"red_team_result_ids": result_ids, "red_team_complete": complete}
        )

    def model_copy(self, *, update: dict[str, object] | None = None, deep: bool = False) -> Self:
        """Do not allow a post-hash protocol edit to masquerade as current."""

        copied = super().model_copy(update=update, deep=deep)
        if len({item.stratum_id for item in copied.strata}) != len(copied.strata):
            raise ProtocolError("protocol strata ids must be unique")
        # Recompute rather than silently preserving an old hash.  This means a
        # copied protocol is a new versioned value and callers must explicitly
        # use its new hash in consent.
        object.__setattr__(copied, "content_hash", copied.canonical_hash())
        return copied


# Compatibility names for protocol-facing integrations.  These are aliases,
# not duplicate model classes, so the inventory namespace remains unique.
Protocol = PilotProtocol
ConsentRecord = PilotConsentRecord
Consent = PilotConsentRecord


def canonical_protocol_hash(protocol: PilotProtocol) -> str:
    """Hash helper for enrollment stores that persist only protocol bytes."""

    return protocol.canonical_hash()
