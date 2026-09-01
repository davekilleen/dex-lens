"""Immutable diagnosis run identity and the closed stage machine."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, StrictBool, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.jobs.contract import SuccessContract

__all__ = [
    "ENGINE_VERSION",
    "INPUT_SCHEMA_VERSION",
    "NEXT_ACTION",
    "NEXT_STAGE",
    "ApprovedScopeReceipt",
    "DiagnosisCheckpoint",
    "DiagnosisInput",
    "DiagnosisRunView",
    "DiagnosisStage",
    "DiagnosisStateError",
    "RequiredStep",
    "RunIdentity",
    "advance_to",
    "canonical_json_digest",
    "required_step_for_stage",
]

ENGINE_VERSION = "0.1.16-diagnosis-engine"
# Version 2 replaces the collapsed observation operational scalar with the
# independent configuration/runtime/health axes.  Stored v1 fingerprints are
# read through the explicit stored-payload upgrade in ``observations``.
INPUT_SCHEMA_VERSION = "2"
_RUN_ID = re.compile(r"^run:[a-z0-9]{16,64}$")
_SCOPE_REF = re.compile(r"^scope:sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RequiredStep(StrEnum):
    """Typed next action exposed by the engine and MCP adapter."""

    APPROVE_SCOPE = "approve_scope"
    CAPTURE_FINGERPRINT = "capture_fingerprint"
    VERIFY_CATALOGUE = "verify_catalogue"
    CONFIRM_JOBS = "confirm_jobs"
    COMPARE = "compare"
    RENDER = "render"
    CHECK = "check"
    SAVE = "save"
    CLOSE = "close"
    REQUIRED_STEP = "required_step"


class DiagnosisStateError(ValueError):
    """A diagnosis run was asked to take an unlawful step."""

    def __init__(
        self,
        message: str,
        *,
        required_step: RequiredStep = RequiredStep.REQUIRED_STEP,
    ) -> None:
        super().__init__(message)
        self.required_step = required_step


class DiagnosisStage(StrEnum):
    """Closed diagnosis stages. The order is the product contract."""

    CREATED = "created"
    SCOPE_APPROVED = "scope-approved"
    CAPTURED = "captured"
    CATALOGUE_VERIFIED = "catalogue-verified"
    JOBS_CONFIRMED = "jobs-confirmed"
    COMPARED = "compared"
    RENDERED = "rendered"
    CHECKED = "checked"
    SAVED = "saved"
    CLOSED = "closed"


_REQUIRED_STEP_BY_STAGE: dict[DiagnosisStage, RequiredStep] = {
    DiagnosisStage.CREATED: RequiredStep.APPROVE_SCOPE,
    DiagnosisStage.SCOPE_APPROVED: RequiredStep.CAPTURE_FINGERPRINT,
    DiagnosisStage.CAPTURED: RequiredStep.VERIFY_CATALOGUE,
    DiagnosisStage.CATALOGUE_VERIFIED: RequiredStep.CONFIRM_JOBS,
    DiagnosisStage.JOBS_CONFIRMED: RequiredStep.COMPARE,
    DiagnosisStage.COMPARED: RequiredStep.RENDER,
    DiagnosisStage.RENDERED: RequiredStep.CHECK,
    DiagnosisStage.CHECKED: RequiredStep.SAVE,
    DiagnosisStage.SAVED: RequiredStep.CLOSE,
    DiagnosisStage.CLOSED: RequiredStep.REQUIRED_STEP,
}


def required_step_for_stage(stage: DiagnosisStage) -> RequiredStep:
    """Return the typed action needed from one deterministic stage."""

    return _REQUIRED_STEP_BY_STAGE[stage]


NEXT_STAGE: dict[DiagnosisStage, DiagnosisStage] = {
    DiagnosisStage.CREATED: DiagnosisStage.SCOPE_APPROVED,
    DiagnosisStage.SCOPE_APPROVED: DiagnosisStage.CAPTURED,
    DiagnosisStage.CAPTURED: DiagnosisStage.CATALOGUE_VERIFIED,
    DiagnosisStage.CATALOGUE_VERIFIED: DiagnosisStage.JOBS_CONFIRMED,
    DiagnosisStage.JOBS_CONFIRMED: DiagnosisStage.COMPARED,
    DiagnosisStage.COMPARED: DiagnosisStage.RENDERED,
    DiagnosisStage.RENDERED: DiagnosisStage.CHECKED,
    DiagnosisStage.CHECKED: DiagnosisStage.SAVED,
    DiagnosisStage.SAVED: DiagnosisStage.CLOSED,
}

NEXT_ACTION: dict[DiagnosisStage, str] = {
    DiagnosisStage.CREATED: (
        "Approve the exact scope in this chat with dex-lens diagnosis approve."
    ),
    DiagnosisStage.SCOPE_APPROVED: "Capture the consented fingerprint.",
    DiagnosisStage.CAPTURED: "Verify the exact catalogue bytes.",
    DiagnosisStage.CATALOGUE_VERIFIED: "Confirm the jobs this diagnosis may use.",
    DiagnosisStage.JOBS_CONFIRMED: "Compare the fingerprint with the catalogue.",
    DiagnosisStage.COMPARED: "Render the typed report from the ledger.",
    DiagnosisStage.RENDERED: "Check the report against ledger-derived facts.",
    DiagnosisStage.CHECKED: "Save the canonical result outside inspected roots.",
    DiagnosisStage.SAVED: "Close the diagnosis without starting follow-on work.",
    DiagnosisStage.CLOSED: (
        "Diagnosis is closed. Start a new authorised flow for any follow-on work."
    ),
}


def canonical_json_digest(payload: object) -> str:
    """Return sha256: plus 64 hex characters over sorted compact JSON."""

    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware UTC timestamp")
    return value


class _ValidatedInventoried(InventoriedModel):
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


class ApprovedScopeReceipt(_ValidatedInventoried):
    """Non-raw proof that the local consent surface approved one scope."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    scope_references: tuple[str, ...] = Field(min_length=1)
    scope_digest: str = Field(pattern=_SHA256.pattern)
    session_receipt_id: str = Field(min_length=8, max_length=120)
    approved_at: datetime
    include_live_state: StrictBool = False

    @field_validator("scope_references")
    @classmethod
    def _scope_references_are_opaque(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("approved scope references must be unique")
        for value in values:
            if _SCOPE_REF.fullmatch(value) is None:
                raise ValueError("approved scope references must be non-raw scope digests")
        return values

    @field_validator("approved_at")
    @classmethod
    def _approved_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "approved_at")

    @model_validator(mode="after")
    def _digest_matches_references(self) -> Self:
        expected = canonical_json_digest(list(self.scope_references))
        if self.scope_digest != expected:
            raise ValueError("scope_digest must bind the exact approved scope references")
        return self


class RunIdentity(_ValidatedInventoried):
    """Stable public identity for one diagnosis run."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    engine_version: str = Field(min_length=1, max_length=64)
    input_schema_version: str = Field(min_length=1, max_length=16)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "created_at")


class DiagnosisInput(_ValidatedInventoried):
    """Content-bound execution input once jobs are confirmed."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    engine_version: str = Field(min_length=1, max_length=64)
    input_schema_version: str = Field(min_length=1, max_length=16)
    adapter_version: str = Field(min_length=1, max_length=64)
    approved_scope_receipt: ApprovedScopeReceipt
    fingerprint_sha256: str = Field(pattern=_HEX_SHA256.pattern)
    catalogue_version: int = Field(ge=1)
    catalogue_sha256: str = Field(pattern=_HEX_SHA256.pattern)
    confirmed_jobs: tuple[SuccessContract, ...] = ()
    assessed_at: datetime

    @field_validator("assessed_at")
    @classmethod
    def _assessed_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "assessed_at")

    @property
    def identity_digest(self) -> str:
        """Digest that changes when scope, catalogue, fingerprint or engine changes."""

        return canonical_json_digest(self.dump_for_storage())


class DiagnosisCheckpoint(_ValidatedInventoried):
    """One lawful, content-bound diagnosis checkpoint."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    stage: DiagnosisStage
    previous_digest: str | None = Field(default=None, pattern=_SHA256.pattern)
    input_identity: str = Field(pattern=_SHA256.pattern)
    artifact_digests: tuple[str, ...] = ()
    next_action: str = Field(min_length=1, max_length=240)
    engine_version: str = Field(min_length=1, max_length=64)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "created_at")

    @field_validator("artifact_digests")
    @classmethod
    def _artifact_digests_are_sha256(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("checkpoint artifact digests must be unique")
        for value in values:
            if _SHA256.fullmatch(value) is None:
                raise ValueError("checkpoint artifact digests must be sha256 bindings")
        return values

    def canonical_digest(self) -> str:
        return canonical_json_digest(self.dump_for_storage())


class DiagnosisRunView(_ValidatedInventoried):
    """Non-secret public view of one diagnosis run."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    stage: DiagnosisStage
    next_action: str = Field(min_length=1, max_length=240)
    required_step: RequiredStep = RequiredStep.REQUIRED_STEP
    input_identity: str | None = Field(default=None, pattern=_SHA256.pattern)
    approval_url: str | None = Field(default=None, max_length=240)


def advance_to(
    checkpoint: DiagnosisCheckpoint,
    stage: DiagnosisStage,
    *,
    now: datetime,
    artifact_digests: tuple[str, ...] | None = None,
) -> DiagnosisCheckpoint:
    """Move one checkpoint to the next lawful stage, or return it unchanged."""

    if stage is checkpoint.stage:
        return checkpoint
    expected = NEXT_STAGE.get(checkpoint.stage)
    if expected is None or stage is not expected:
        raise DiagnosisStateError(
            f"cannot move from {checkpoint.stage.value} to {stage.value}"
        )
    return DiagnosisCheckpoint(
        run_id=checkpoint.run_id,
        stage=stage,
        previous_digest=checkpoint.canonical_digest(),
        input_identity=checkpoint.input_identity,
        artifact_digests=(
            checkpoint.artifact_digests if artifact_digests is None else artifact_digests
        ),
        next_action=NEXT_ACTION[stage],
        engine_version=checkpoint.engine_version,
        created_at=now,
    )
