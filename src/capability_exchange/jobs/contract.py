"""Success Contract schema: the person-confirmed Job Map entry (M-C, #352).

A :class:`SuccessContract` is one confirmed job in the Job Map — the
person-confirmed set of outcomes their system is intended to help achieve.
Per non-negotiable rule (gates.md R1, HANDOFF 2.3 M-C): **confirmed Success
Contracts are the only input diagnosis may consume.** System-inferred
candidates remain suggestions in the provisional ``Inspection`` state
(:mod:`capability_exchange.jobs.inspection`) until the person confirms them.

The contract records, per confirmed job: Situation, Desired outcome,
Success evidence, Boundaries (privacy / approval / autonomy limits), and
Importance and cadence.

Machine-readable lifecycle separation (R1): a Success Contract carries the
literal lifecycle value ``diagnosis`` and an ``Inspection``-state job
carries ``inspection``. The two are distinct pydantic types with distinct
required fields, so one is never coercible into the other — separation is
structural, not a runtime flag check.

No aggregate score, maturity rank, or resemblance percentage is
representable anywhere in this schema (``extra="forbid"``; there is no
field for one — M2 criterion: structurally impossible, not reviewed away).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self, final

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "CONTRACT_TEXT_MAX_LENGTH",
    "JobBoundaries",
    "JobCadence",
    "JobImportance",
    "SuccessContract",
]

#: A contract text value is bounded, single-line prose — never a payload.
CONTRACT_TEXT_MAX_LENGTH = 512

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def validate_contract_text(value: str, field_label: str) -> str:
    """One bounded, non-empty, single-line text value (shared rule).

    Public so the ``Inspection``-state schema applies **the same** rule
    rather than a similar one — drift between the two would let a draft
    survive editing but explode at confirmation time.
    """
    if not value.strip():
        raise ValueError(f"{field_label} must be non-empty")
    if len(value) > CONTRACT_TEXT_MAX_LENGTH:
        raise ValueError(
            f"{field_label} exceeds {CONTRACT_TEXT_MAX_LENGTH} characters; "
            f"contract text is bounded prose, never a payload"
        )
    if _CONTROL_RE.search(value):
        raise ValueError(f"{field_label} contains line breaks or control characters")
    return value


def validate_job_id(value: str) -> str:
    """Kebab-case job id (shared with the ``Inspection`` schema)."""
    if not _KEBAB_RE.match(value):
        raise ValueError(f"job_id {value!r} must be kebab-case")
    return value


class JobImportance(StrEnum):
    """Closed importance vocabulary. Unknown input is rejected, never guessed."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class JobCadence(StrEnum):
    """Closed cadence vocabulary: how often the job recurs."""

    ON_DEMAND = "on-demand"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    IRREGULAR = "irregular"


@final
class JobBoundaries(InventoriedModel):
    """The job's declared limits: privacy, approval, and autonomy.

    All three axes are required fields — a confirmation flow must state each
    explicitly (an empty tuple is an explicit "no limits declared", which the
    person typed, not a silent default the product assumed).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: What may never be read, derived, or surfaced for this job.
    privacy_limits: tuple[str, ...]
    #: What always requires a fresh human approval for this job.
    approval_limits: tuple[str, ...]
    #: What the system may never do on its own for this job.
    autonomy_limits: tuple[str, ...]

    @field_validator("privacy_limits", "approval_limits", "autonomy_limits")
    @classmethod
    def _bounded_lines(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_contract_text(item, "boundary limit") for item in value)


@final
class SuccessContract(InventoriedModel):
    """One confirmed job: the only input diagnosis may consume (R1).

    Construction is itself the record of an explicit human confirmation —
    ``confirmed_at`` is required and timezone-aware, and there is no
    unconfirmed variant of this type. Candidate jobs live in the separate
    ``Inspection`` type until :meth:`InspectionJobStore.confirm` is called.

    Frozen and closed: no field outside this schema is representable, so an
    aggregate score or rank cannot be attached to a contract by anyone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Machine-readable lifecycle marker (R1): confirmed contracts belong to
    #: Diagnosis. The literal type admits no other value.
    lifecycle: Literal["diagnosis"] = "diagnosis"

    #: Stable kebab-case identity of the job within the Job Map.
    job_id: str

    #: Situation: when and where this job arises for the person.
    situation: str

    #: Desired outcome: what "done" means, in the person's terms.
    desired_outcome: str

    #: Success evidence: observable signals that the outcome was reached.
    #: At least one — a contract with no observable signal is unverifiable.
    success_evidence: tuple[str, ...] = Field(min_length=1)

    #: Privacy / approval / autonomy limits for this job.
    boundaries: JobBoundaries

    #: How much this job matters to the person (closed vocabulary).
    importance: JobImportance

    #: How often the job recurs (closed vocabulary).
    cadence: JobCadence

    #: When the person explicitly confirmed this contract. Timezone-aware,
    #: required: a naive timestamp is an unverifiable confirmation record.
    confirmed_at: datetime

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: object
    ) -> SuccessContract:
        # model_construct skips validation by design; the lifecycle literal
        # must hold on that route too, or a draft could be forged into (or
        # out of) the confirmed lifecycle (R1 hostile route; mirrors
        # InspectionJob's own guards).
        contract = super().model_construct(_fields_set, **values)  # type: ignore[arg-type]
        contract._assert_lifecycle_is_diagnosis()
        return contract

    def model_copy(self, *, update: dict[str, object] | None = None, deep: bool = False) -> Self:
        # model_copy also skips validation; a lifecycle swap refuses the
        # same way.
        copied = super().model_copy(update=update, deep=deep)  # type: ignore[arg-type]
        copied._assert_lifecycle_is_diagnosis()
        return copied

    def _assert_lifecycle_is_diagnosis(self) -> None:
        if self.__dict__.get("lifecycle") != "diagnosis":
            raise ValueError(
                "a SuccessContract's lifecycle is 'diagnosis'; candidate jobs "
                "live in the separate Inspection type until explicitly "
                "confirmed (R1)"
            )

    @field_validator("job_id")
    @classmethod
    def _kebab_job_id(cls, value: str) -> str:
        return validate_job_id(value)

    @field_validator("situation")
    @classmethod
    def _situation_text(cls, value: str) -> str:
        return validate_contract_text(value, "situation")

    @field_validator("desired_outcome")
    @classmethod
    def _desired_outcome_text(cls, value: str) -> str:
        return validate_contract_text(value, "desired_outcome")

    @field_validator("success_evidence")
    @classmethod
    def _success_evidence_lines(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_contract_text(item, "success evidence") for item in value)

    @field_validator("confirmed_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "confirmed_at must be timezone-aware; a naive timestamp is an "
                "unverifiable confirmation record (fail closed)"
            )
        return value
