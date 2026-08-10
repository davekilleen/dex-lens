"""Fail-closed participant enrollment (R6 + R1/P1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, Self

from pydantic import ConfigDict, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.jobs.contract import SuccessContract
from capability_exchange.jobs.inspection import InspectionJob
from capability_exchange.pilot._common import clean_text, utc_now
from capability_exchange.pilot.protocol import (
    ConsentRecord,
    ConsentStatus,
    PilotProtocol,
    ProtocolError,
)

__all__ = [
    "ConsentRequiredError",
    "EnrollmentError",
    "EnrollmentGate",
    "EnrollmentRecord",
    "ParticipantDeletionPort",
    "InvalidCohortError",
    "ProtocolHashMismatchError",
    "ProtocolVersionMismatchError",
    "SuccessContractRequiredError",
    "enroll_participant",
]


class ParticipantDeletionPort(Protocol):
    """External byte-deletion verifier for all controlled participant stores."""

    def delete_participant(self, record: EnrollmentRecord) -> bool:
        """Return true only after receipts, caches, and browser state are absent."""


class EnrollmentError(ProtocolError):
    """A participant cannot enter the pilot under current preconditions."""


class ConsentRequiredError(EnrollmentError):
    """No active consent record was supplied."""


class ProtocolVersionMismatchError(EnrollmentError):
    """Consent names a protocol version other than the current one."""


class ProtocolHashMismatchError(EnrollmentError):
    """Consent does not bind to the exact current protocol bytes."""


class InvalidCohortError(EnrollmentError):
    """Consent names an undeclared or over-capacity stratum."""


class SuccessContractRequiredError(EnrollmentError):
    """Only a confirmed Success Contract can enter the pilot."""


class EnrollmentRecord(InventoriedModel):
    """Immutable proof that one participant passed every enrollment gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    participant_id: str
    protocol_version: str
    protocol_hash: str
    contract_id: str
    stratum_id: str
    enrolled_at: datetime
    consent: ConsentRecord

    @field_validator(
        "participant_id",
        "protocol_version",
        "protocol_hash",
        "contract_id",
        "stratum_id",
    )
    @classmethod
    def _text(cls, value: str, info: Any) -> str:
        return clean_text(value, label=info.field_name, max_length=256)

    @field_validator("enrolled_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("enrolled_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _same_consent(self) -> Self:
        if self.consent.participant_id != self.participant_id:
            raise ValueError("enrollment consent participant does not match record")
        if self.consent.protocol_version != self.protocol_version:
            raise ValueError("enrollment consent protocol version does not match record")
        if self.consent.protocol_hash != self.protocol_hash:
            raise ValueError("enrollment consent protocol hash does not match record")
        if self.consent.stratum_id != self.stratum_id:
            raise ValueError("enrollment consent stratum does not match record")
        return self


class EnrollmentGate:
    """Current-protocol gate with deterministic cohort accounting.

    The gate stores no participant source data.  It keeps only immutable
    enrollment records and refuses duplicate ids, invalid strata, withdrawn
    consent, stale protocol hashes, provisional ``Inspection`` jobs, and any
    contract whose lifecycle is not the confirmed ``diagnosis`` literal.
    """

    def __init__(self, protocol: PilotProtocol) -> None:
        self.protocol = protocol
        self._records: dict[str, EnrollmentRecord] = {}

    @property
    def records(self) -> tuple[EnrollmentRecord, ...]:
        return tuple(self._records.values())

    def assert_cohort_complete(self) -> None:
        """Check the final 6–8 cohort and every declared stratum range."""

        total = len(self._records)
        if total < 6 or total > 8:
            raise InvalidCohortError("pilot cohort must contain 6–8 enrolled participants")
        for stratum in self.protocol.strata:
            count = sum(
                1
                for item in self._records.values()
                if item.stratum_id == stratum.stratum_id
            )
            if count < stratum.minimum or count > stratum.maximum:
                raise InvalidCohortError(
                    f"stratum {stratum.stratum_id!r} has {count}; "
                    f"expected {stratum.minimum}–{stratum.maximum}"
                )

    def _check_consent(self, consent: ConsentRecord | None) -> ConsentRecord:
        if consent is None:
            raise ConsentRequiredError("recorded consent is required before inspection")
        if consent.status is not ConsentStatus.ACTIVE:
            raise EnrollmentError("withdrawn consent cannot activate enrollment")
        if consent.protocol_version != self.protocol.protocol_version:
            raise ProtocolVersionMismatchError(
                "consent references protocol version "
                f"{consent.protocol_version!r}, current is {self.protocol.protocol_version!r}"
            )
        if consent.protocol_hash != self.protocol.protocol_hash:
            raise ProtocolHashMismatchError(
                "consent does not reference the exact current protocol hash"
            )
        try:
            self.protocol.stratum(consent.stratum_id)
        except ProtocolError as exc:
            raise InvalidCohortError(str(exc)) from exc
        return consent

    @staticmethod
    def _check_contract(contract: SuccessContract | None) -> SuccessContract:
        if contract is None:
            raise SuccessContractRequiredError(
                "a confirmed Success Contract is required before enrollment"
            )
        if isinstance(contract, InspectionJob):
            raise SuccessContractRequiredError(
                "an Inspection-state candidate is not a confirmed Success Contract"
            )
        if not isinstance(contract, SuccessContract) or contract.lifecycle != "diagnosis":
            raise SuccessContractRequiredError("enrollment requires a confirmed Success Contract")
        return contract

    def enroll(
        self,
        consent: ConsentRecord | None,
        contract: SuccessContract | None,
        *,
        at: datetime | None = None,
    ) -> EnrollmentRecord:
        """Validate and record one enrollment, or raise without side effects."""

        checked_consent = self._check_consent(consent)
        checked_contract = self._check_contract(contract)
        self.protocol.assert_red_team_ready()
        if checked_consent.participant_id in self._records:
            raise EnrollmentError("participant is already enrolled")
        when = at or utc_now()
        if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
            raise EnrollmentError("enrollment time must be timezone-aware")

        stratum = self.protocol.stratum(checked_consent.stratum_id)
        current_count = sum(
            1 for item in self._records.values() if item.stratum_id == stratum.stratum_id
        )
        if current_count >= stratum.maximum:
            raise InvalidCohortError(f"stratum {stratum.stratum_id!r} has reached its maximum")

        record = EnrollmentRecord(
            participant_id=checked_consent.participant_id,
            protocol_version=self.protocol.protocol_version,
            protocol_hash=self.protocol.protocol_hash,
            contract_id=checked_contract.job_id,
            stratum_id=checked_consent.stratum_id,
            enrolled_at=when,
            consent=checked_consent,
        )
        self._records[record.participant_id] = record
        return record

    def withdraw(
        self,
        participant_id: str,
        *,
        deletion_port: ParticipantDeletionPort,
        at: datetime | None = None,
    ) -> EnrollmentRecord:
        """Withdraw only after a controlled-store port proves byte deletion."""

        record = self._records.get(participant_id)
        if record is None:
            raise EnrollmentError("unknown participant; refusing to infer enrollment state")
        requested = record.consent.withdraw(at=at)
        if not deletion_port.delete_participant(record):
            raise EnrollmentError(
                "participant deletion could not be verified; enrollment remains held"
            )
        withdrawn = record.model_copy(
            update={"consent": requested.confirm_deletion(at=at)}
        )
        self._records.pop(participant_id, None)
        return withdrawn


def enroll_participant(
    protocol: PilotProtocol,
    consent: ConsentRecord | None,
    contract: SuccessContract | None,
    *,
    at: datetime | None = None,
) -> EnrollmentRecord:
    """Convenience wrapper around :class:`EnrollmentGate`."""

    return EnrollmentGate(protocol).enroll(consent, contract, at=at)
