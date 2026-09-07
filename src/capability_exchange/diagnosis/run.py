"""Immutable diagnosis run identity and the closed stage machine."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

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
    "ExpectationState",
    "FamilyMap",
    "FamilyMapRow",
    "FamilyReleaseDelta",
    "FocusReceipt",
    "RequiredStep",
    "RunIdentity",
    "advance_to",
    "advance_inventory_to_compare",
    "canonical_json_digest",
    "required_step_for_stage",
    "upgrade_stored_input_payload",
]

ENGINE_VERSION = "0.1.16-diagnosis-engine"
# Version 2 replaces the collapsed observation operational scalar with the
# independent configuration/runtime/health axes.  Stored v1 fingerprints are
# read through the explicit stored-payload upgrade in ``observations``.
INPUT_SCHEMA_VERSION = "3"
_RUN_ID = re.compile(r"^run:[a-z0-9]{16,64}$")
_SCOPE_REF = re.compile(r"^scope:sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# The bounded SemVer forms Lens accepts for release identities, matching the
# signed lineage fields and the version-distance contract in ``comparison``.
_SEMVERISH = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_MEMBER_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")


class RequiredStep(StrEnum):
    """Typed next action exposed by the engine and MCP adapter."""

    APPROVE_SCOPE = "approve_scope"
    CAPTURE_FINGERPRINT = "capture_fingerprint"
    VERIFY_CATALOGUE = "verify_catalogue"
    MAP_FAMILIES = "map_families"
    #: A focused run cannot confirm jobs until the person's family selection
    #: is recorded as a focus receipt.  Not a stage of its own: the refusal on
    #: the family-mapped -> jobs-confirmed transition names this step.
    CONFIRM_FOCUS = "confirm_focus"
    CONFIRM_JOBS = "confirm_jobs"
    PLAN_ANALYSIS = "plan_analysis"
    SUBMIT_WORK = "submit_work"
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
    FAMILY_MAPPED = "family-mapped"
    JOBS_CONFIRMED = "jobs-confirmed"
    ANALYSIS_PLANNED = "analysis-planned"
    ANALYSIS_COMPLETED = "analysis-completed"
    COMPARED = "compared"
    RENDERED = "rendered"
    CHECKED = "checked"
    SAVED = "saved"
    CLOSED = "closed"


_REQUIRED_STEP_BY_STAGE: dict[DiagnosisStage, RequiredStep] = {
    DiagnosisStage.CREATED: RequiredStep.APPROVE_SCOPE,
    DiagnosisStage.SCOPE_APPROVED: RequiredStep.CAPTURE_FINGERPRINT,
    DiagnosisStage.CAPTURED: RequiredStep.VERIFY_CATALOGUE,
    DiagnosisStage.CATALOGUE_VERIFIED: RequiredStep.MAP_FAMILIES,
    DiagnosisStage.FAMILY_MAPPED: RequiredStep.CONFIRM_JOBS,
    DiagnosisStage.JOBS_CONFIRMED: RequiredStep.PLAN_ANALYSIS,
    DiagnosisStage.ANALYSIS_PLANNED: RequiredStep.SUBMIT_WORK,
    DiagnosisStage.ANALYSIS_COMPLETED: RequiredStep.COMPARE,
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
    DiagnosisStage.CATALOGUE_VERIFIED: DiagnosisStage.FAMILY_MAPPED,
    DiagnosisStage.FAMILY_MAPPED: DiagnosisStage.JOBS_CONFIRMED,
    DiagnosisStage.JOBS_CONFIRMED: DiagnosisStage.ANALYSIS_PLANNED,
    DiagnosisStage.ANALYSIS_PLANNED: DiagnosisStage.ANALYSIS_COMPLETED,
    DiagnosisStage.ANALYSIS_COMPLETED: DiagnosisStage.COMPARED,
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
    DiagnosisStage.CATALOGUE_VERIFIED: "Derive the deterministic family map.",
    DiagnosisStage.FAMILY_MAPPED: "Confirm the jobs this diagnosis may use.",
    DiagnosisStage.JOBS_CONFIRMED: "Plan the bounded specialist analysis.",
    DiagnosisStage.ANALYSIS_PLANNED: "Complete the issued specialist work packets.",
    DiagnosisStage.ANALYSIS_COMPLETED: "Compare the fingerprint with the catalogue.",
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


class ExpectationState(StrEnum):
    """Closed evidence states for one significant-family expectation row.

    Defined beside the stage machine (and re-exported by ``expectations``)
    because the deterministic pass-1 family map — embedded in the public run
    view below — speaks exactly this vocabulary.  ``NOT_GATED`` is the loud
    typed state a family-free catalogue yields: never a silent empty manifest.
    """

    PRESENT = "present"
    PARTIAL = "partial"
    ABSENT = "absent"
    UNKNOWN = "unknown"
    NOT_RELEVANT = "not-relevant"
    NOT_CURRENTLY_AVAILABLE = "not-currently-available"
    NOT_GATED = "not-gated"


class FamilyReleaseDelta(_ValidatedInventoried):
    """Per-family signed release gap for one map row, where derivable.

    The minimal honest subset of ``build_family_delta``: which signed skill
    members of this family are newer than the person's proven Dex Core
    lineage, which changed since it, and the family's signed ``outcome``
    string — the only lawful source for saying what having the gap closed
    would do.  Derived by the engine at map time from signed lineage fields
    plus one Verified local release observation; never host-authored, and
    re-derived on every read like the rest of the map.
    """

    inspected_release: str = Field(pattern=_SEMVERISH.pattern)
    current_release: str = Field(pattern=_SEMVERISH.pattern)
    newer_member_ids: tuple[str, ...] = ()
    changed_member_ids: tuple[str, ...] = ()
    outcome: str = Field(min_length=1, max_length=800)

    @field_validator("newer_member_ids", "changed_member_ids")
    @classmethod
    def _member_ids_are_bounded_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("family release-delta member IDs must be unique")
        if any(_MEMBER_ID.fullmatch(value) is None for value in values):
            raise ValueError("family release-delta member ID is invalid")
        return values

    @model_validator(mode="after")
    def _delta_names_a_real_signed_gap(self) -> Self:
        if not self.newer_member_ids and not self.changed_member_ids:
            raise ValueError("a family release delta must name at least one signed change")
        if set(self.newer_member_ids) & set(self.changed_member_ids):
            raise ValueError("newer and changed family members must not overlap")
        if self.inspected_release == self.current_release:
            raise ValueError("a family release delta requires two distinct releases")
        return self


class FamilyMapRow(_ValidatedInventoried):
    """One deterministic family-map row. Engine-derived, never host-authored."""

    family_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    state: ExpectationState
    evidence_references: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=600)
    #: Signed release gap for this family, present only when the run's
    #: observations establish a Verified dex-core lineage AND the signed
    #: catalogue carries this family — never invented without the contract.
    release_delta: FamilyReleaseDelta | None = None

    @field_validator("evidence_references")
    @classmethod
    def _evidence_references_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("family map evidence references must be unique")
        if tuple(sorted(values)) != tuple(values):
            raise ValueError("family map evidence references must be sorted")
        return values


class FamilyMap(_ValidatedInventoried):
    """Deterministic pass-1 family map over the verified catalogue.

    Re-derived from the stored verified inputs on every read; the stored
    ``family-map`` artifact is a digest-bound audit record, never an input
    (mirroring the RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT lesson).  Carries no
    wall-clock so two derivations of the same inputs are byte-identical.
    """

    catalogue_version: int = Field(ge=1)
    catalogue_sha256: str = Field(pattern=_HEX_SHA256.pattern)
    rows: tuple[FamilyMapRow, ...] = Field(min_length=1)
    #: Dex Core release the signed catalogue metadata names, when present.
    current_release: str | None = Field(default=None, pattern=_SEMVERISH.pattern)
    #: The one Dex Core release the approved snapshot proves, or ``None`` when
    #: lineage could not be established (no release observation, conflicting
    #: release identities, or a non-release-shaped identity).  ``None`` is the
    #: loud Unknown branch every map surface must speak, never a silence.
    inspected_release: str | None = Field(default=None, pattern=_SEMVERISH.pattern)
    #: Evidence references of the release observations proving the lineage.
    release_evidence_references: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("release_evidence_references")
    @classmethod
    def _release_evidence_is_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("family map release evidence references must be unique")
        if tuple(sorted(values)) != tuple(values):
            raise ValueError("family map release evidence references must be sorted")
        return values

    @model_validator(mode="after")
    def _rows_name_each_family_once(self) -> Self:
        family_ids = [row.family_id for row in self.rows]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("family map rows must name each family exactly once")
        if (self.inspected_release is None) != (not self.release_evidence_references):
            raise ValueError(
                "an established release lineage and its evidence references come together"
            )
        for row in self.rows:
            delta = row.release_delta
            if delta is None:
                continue
            if (
                delta.inspected_release != self.inspected_release
                or delta.current_release != self.current_release
            ):
                raise ValueError(
                    "family release deltas must share the map's proven release pair"
                )
        return self


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


_FAMILY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")


class FocusReceipt(_ValidatedInventoried):
    """Typed record of the person's family multi-select for one focused run.

    Minted by the engine after the deterministic family map: it binds the
    exact families selected AND the families explicitly not selected, plus the
    digest of the family map the choice was made against.  The engine
    re-validates the receipt against the re-derived map on every consuming
    read, so a stored receipt that no longer matches this run's map is refused
    rather than trusted (the same artifact discipline as the family map).
    """

    run_id: str = Field(pattern=_RUN_ID.pattern)
    family_map_digest: str = Field(pattern=_SHA256.pattern)
    selected_family_ids: tuple[str, ...] = Field(min_length=1)
    unselected_family_ids: tuple[str, ...] = ()
    focus_digest: str = Field(pattern=_SHA256.pattern)
    confirmed_at: datetime

    @field_validator("selected_family_ids", "unselected_family_ids")
    @classmethod
    def _family_ids_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("focus receipt family identities must be unique")
        if tuple(sorted(values)) != tuple(values):
            raise ValueError("focus receipt family identities must be sorted")
        for value in values:
            if _FAMILY_ID.fullmatch(value) is None:
                raise ValueError("focus receipt family identities must be bounded ids")
        return values

    @field_validator("confirmed_at")
    @classmethod
    def _confirmed_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "confirmed_at")

    @model_validator(mode="after")
    def _digest_binds_the_exact_selection(self) -> Self:
        if set(self.selected_family_ids) & set(self.unselected_family_ids):
            raise ValueError(
                "a family cannot be both selected and explicitly not selected"
            )
        expected = canonical_json_digest(
            {
                "family_map_digest": self.family_map_digest,
                "run_id": self.run_id,
                "selected_family_ids": list(self.selected_family_ids),
                "unselected_family_ids": list(self.unselected_family_ids),
            }
        )
        if self.focus_digest != expected:
            raise ValueError("focus_digest must bind the exact recorded selection")
        return self


class RunIdentity(_ValidatedInventoried):
    """Stable public identity for one diagnosis run."""

    run_id: str = Field(pattern=_RUN_ID.pattern)
    engine_version: str = Field(min_length=1, max_length=64)
    input_schema_version: str = Field(min_length=1, max_length=16)
    analysis_mode: Literal[
        "inventory-only", "guided-analysis", "focused-analysis"
    ] = "inventory-only"
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
    analysis_mode: Literal[
        "inventory-only", "guided-analysis", "focused-analysis"
    ] = "guided-analysis"
    assessed_at: datetime

    @field_validator("assessed_at")
    @classmethod
    def _assessed_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "assessed_at")

    @property
    def identity_digest(self) -> str:
        """Digest that changes when scope, catalogue, fingerprint or engine changes."""

        return canonical_json_digest(self.dump_for_storage())


def upgrade_stored_run_identity_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Upgrade a stored run identity without changing legacy semantics.

  ``analysis_mode`` was introduced after the original durable identity shape.
  Old checkpoints did not issue semantic work, so a missing field is
  deliberately upgraded to ``inventory-only`` rather than inheriting the guided
  default used for newly-created product runs.
    """

    upgraded = dict(payload)
    upgraded.setdefault("analysis_mode", "inventory-only")
    return upgraded


def upgrade_stored_input_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Upgrade a stored diagnosis input without changing legacy semantics.

    ``analysis_mode`` was introduced after the original durable input shape.
    Old checkpoints did not issue semantic work, so a missing field is
    deliberately upgraded to ``inventory-only`` rather than inheriting the
    guided default used for newly-created product runs.  The operation is
    idempotent and never mutates the caller's mapping.
    """

    upgraded = dict(payload)
    upgraded.setdefault("analysis_mode", "inventory-only")
    return upgraded


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
    #: Deterministic pass-1 family map, re-derived on every status read once
    #: the run has passed the family-mapped stage.  Never loaded from the
    #: stored artifact.
    family_map: FamilyMap | None = None
    #: The recorded family multi-select for a focused run, re-validated
    #: against the re-derived family map on every status read.  ``None`` until
    #: the person's selection is recorded (and always for guided runs).
    focus: FocusReceipt | None = None


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


def advance_inventory_to_compare(
    checkpoint: DiagnosisCheckpoint,
    *,
    now: datetime,
    artifact_digests: tuple[str, ...] = (),
) -> DiagnosisCheckpoint:
    """Advance one legacy inventory-only run across the guided-era stages.

    Checkpoints written before the specialist queue existed must retain their
    direct comparison semantics.  This narrow transition is deliberately
    separate from :func:`advance_to`, so ordinary callers cannot use it to
    bypass the closed stage machine.
    """

    if checkpoint.stage is not DiagnosisStage.JOBS_CONFIRMED:
        raise DiagnosisStateError(
            "inventory-only comparison skip is valid only after jobs-confirmed"
        )
    return DiagnosisCheckpoint(
        run_id=checkpoint.run_id,
        stage=DiagnosisStage.COMPARED,
        previous_digest=checkpoint.canonical_digest(),
        input_identity=checkpoint.input_identity,
        artifact_digests=(*checkpoint.artifact_digests, *artifact_digests),
        next_action=NEXT_ACTION[DiagnosisStage.COMPARED],
        engine_version=checkpoint.engine_version,
        created_at=now,
    )
