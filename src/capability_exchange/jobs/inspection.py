"""The provisional ``Inspection`` state for candidate jobs (gates.md R1).

Candidate jobs carry a distinct, machine-readable ``Inspection`` state,
separate from ``Diagnosis``. While in ``Inspection`` a job is:

- **local-only** — stored as one JSON file per job in a local directory,
  through the G2 typed serialization boundary (every stored field is
  inventoried with ``sharing: never``, so transmission structurally
  refuses);
- **editable** — :meth:`InspectionJobStore.edit` replaces the draft text;
  editing can never change the lifecycle, because :meth:`InspectionJob.edited`
  simply has no lifecycle parameter and the field's Literal type admits no
  other value;
- **discardable** — :meth:`InspectionJobStore.discard` verifiably removes
  the job's bytes from disk, using the same overwrite-unlink-verify
  discipline as the M1 deletion registry, where the ``delete-inspection-jobs``
  path is registered for full (withdrawal-drill) deletion;
- **type-level excluded from every sharing, Card, export, and telemetry
  payload** — :class:`ConfirmedJobExport`, the only job payload any such
  surface may reference, holds ``SuccessContract`` values only. An
  ``InspectionJob`` fails its validation (unrepresentable, not filtered),
  and a crafted request referencing an ``Inspection`` job **id** is
  rejected by :func:`resolve_export_request` (fail closed: an id that does
  not name a confirmed contract is refused, whatever it names).

The only exit from ``Inspection`` is an explicit user confirmation call:
:meth:`InspectionJobStore.confirm` — which produces the
:class:`~capability_exchange.jobs.contract.SuccessContract` and removes the
``Inspection`` record's bytes. Detection proposes; it never enrolls.

Fail closed (R1): a stored job record with missing or corrupt lifecycle
metadata — including a record that *claims* ``diagnosis`` on disk — loads
as ``Inspection``. Confirmation is a fresh human act recorded through
:meth:`confirm`, never a disk flag.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal, Self, final

from pydantic import ConfigDict, Field, ValidationError, field_validator

from capability_exchange.boundary.deletion import (
    DeletionVerificationError,
    register_deletion_path,
)
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence.item import reference_rejection_reason
from capability_exchange.jobs.contract import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
    validate_contract_text,
    validate_job_id,
)

__all__ = [
    "INSPECTION_JOB_GLOB",
    "ConfirmedJobExport",
    "CorruptJobRecordError",
    "InspectionExclusionError",
    "InspectionJob",
    "InspectionJobStore",
    "JobStoreError",
    "delete_inspection_jobs",
    "resolve_export_request",
]


class JobStoreError(Exception):
    """Base class for job-store refusals."""


class CorruptJobRecordError(JobStoreError):
    """A stored job record is unreadable beyond its lifecycle metadata.

    The record is still *treated* as ``Inspection`` for every sharing
    decision (nothing unreadable is ever shareable); it just cannot be
    loaded as data. The message names the file, never its contents.
    """


class InspectionExclusionError(JobStoreError):
    """A sharing/export/telemetry request referenced a non-confirmed job id.

    Raised for ``Inspection``-state ids and for unknown ids alike — the
    refusal never confirms whether an id exists (fail closed either way).
    """


@final
class InspectionJob(InventoriedModel):
    """One candidate job in the provisional ``Inspection`` state (R1).

    Distinct type from :class:`SuccessContract` — different lifecycle
    literal, different required fields — so the two are never mutually
    coercible. This type carries drafts the person may edit or discard;
    it carries no confirmation record, no boundaries, no importance, no
    cadence: those exist only on a contract the person explicitly confirms.

    Evidence attribution is by non-raw reference only (G2): a proposal's
    evidence items stay ephemeral; what persists is the locator, never
    content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Machine-readable lifecycle marker (R1): the literal type admits only
    #: ``inspection``. Guarded on every construction route below.
    lifecycle: Literal["inspection"] = "inspection"

    #: Stable kebab-case identity of the candidate job.
    job_id: str

    #: Short human-readable name for the candidate job.
    title: str

    #: Draft situation text (editable until confirmed or discarded).
    situation: str

    #: Draft desired-outcome text (editable until confirmed or discarded).
    desired_outcome: str

    #: Non-raw references to the evidence this candidate derives from —
    #: locators/digests under the G2 boundary, never content. Empty for a
    #: job the person added themselves.
    evidence_references: tuple[str, ...] = ()

    #: When the candidate entered ``Inspection``. Timezone-aware, required.
    created_at: datetime

    @field_validator("job_id")
    @classmethod
    def _kebab_job_id(cls, value: str) -> str:
        return validate_job_id(value)

    @field_validator("title")
    @classmethod
    def _title_text(cls, value: str) -> str:
        return validate_contract_text(value, "title")

    @field_validator("situation")
    @classmethod
    def _situation_text(cls, value: str) -> str:
        return validate_contract_text(value, "situation")

    @field_validator("desired_outcome")
    @classmethod
    def _desired_outcome_text(cls, value: str) -> str:
        return validate_contract_text(value, "desired_outcome")

    @field_validator("evidence_references")
    @classmethod
    def _non_raw_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for reference in value:
            if not reference.strip():
                raise ValueError("evidence reference must be a non-empty locator or digest")
            reason = reference_rejection_reason(reference)
            if reason is not None:
                raise ValueError(reason)
        return value

    @field_validator("created_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "created_at must be timezone-aware; a naive timestamp is an "
                "unverifiable record age (fail closed)"
            )
        return value

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: object
    ) -> InspectionJob:
        # model_construct skips validation by design; the lifecycle literal
        # must hold on that route too, or a candidate could impersonate a
        # confirmed job (R1 hostile route).
        job = super().model_construct(_fields_set, **values)  # type: ignore[arg-type]
        job._assert_lifecycle_is_inspection()
        return job

    def model_copy(self, *, update: dict[str, object] | None = None, deep: bool = False) -> Self:
        # model_copy also skips validation; an update that swaps the
        # lifecycle must refuse the same way.
        copied = super().model_copy(update=update, deep=deep)  # type: ignore[arg-type]
        copied._assert_lifecycle_is_inspection()
        return copied

    def _assert_lifecycle_is_inspection(self) -> None:
        if self.__dict__.get("lifecycle") != "inspection":
            raise ValueError(
                "an InspectionJob's lifecycle is 'inspection'; only an explicit "
                "user confirmation call produces a Success Contract (R1)"
            )

    def edited(
        self,
        *,
        title: str | None = None,
        situation: str | None = None,
        desired_outcome: str | None = None,
    ) -> InspectionJob:
        """A new draft with the given text replaced. Fully re-validated.

        There is deliberately no lifecycle parameter: editing never exits
        ``Inspection`` (the only exit is explicit confirmation).
        """
        return InspectionJob(
            job_id=self.job_id,
            title=self.title if title is None else title,
            situation=self.situation if situation is None else situation,
            desired_outcome=(
                self.desired_outcome if desired_outcome is None else desired_outcome
            ),
            evidence_references=self.evidence_references,
            created_at=self.created_at,
        )


# --------------------------------------------------------------------------
# Local-only persistence, verified discard, and the confirmation exit
# --------------------------------------------------------------------------

#: Glob for Inspection-job record files (one JSON file per candidate job).
INSPECTION_JOB_GLOB = "inspection-job-*.json"

_RECORD_NAME_RE = re.compile(r"^inspection-job-[a-z][a-z0-9]*(-[a-z0-9]+)*\.json$")


def _remove_file_verified(path: Path) -> None:
    """Overwrite with zeros, unlink, verify gone (M1 deletion discipline)."""
    try:
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.write(b"\0" * size)
            handle.flush()
    except OSError:
        # Overwrite is belt-and-braces; unlink below is the verified step.
        pass
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    if path.exists():
        raise DeletionVerificationError(f"{path} still exists after deletion")


def delete_inspection_jobs(directory: Path) -> list[Path]:
    """Deletion path ``delete-inspection-jobs``: remove all Inspection jobs.

    Covers every stored ``InspectionJob`` field (each job lives in one JSON
    file). Missing directory or no files is a clean no-op; a surviving file
    raises :class:`DeletionVerificationError`.
    """
    if not directory.is_dir():
        return []
    removed: list[Path] = []
    for path in sorted(directory.glob(INSPECTION_JOB_GLOB)):
        _remove_file_verified(path)
        removed.append(path)
    return removed


register_deletion_path("delete-inspection-jobs", delete_inspection_jobs)


class InspectionJobStore:
    """Local-only store: one JSON record per ``Inspection``-state job.

    Every write goes through :meth:`InspectionJob.dump_for_storage` (the G2
    boundary: only inventoried, storage-declared fields reach disk). Every
    load coerces lifecycle metadata fail-closed: anything that is not the
    literal ``inspection`` — missing, corrupt, or a crafted ``diagnosis``
    claim — loads as ``Inspection``, because confirmation is a fresh human
    act through :meth:`confirm`, never a stored flag.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        return self._directory

    def _path_for(self, job_id: str) -> Path:
        return self._directory / f"inspection-job-{validate_job_id(job_id)}.json"

    def save(self, job: InspectionJob) -> Path:
        """Persist one ``Inspection`` job locally; return its record path."""
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path_for(job.job_id)
        payload = job.dump_for_storage()
        path.write_text(
            json.dumps(payload, sort_keys=True, ensure_ascii=True), encoding="utf-8"
        )
        return path

    def job_ids(self) -> tuple[str, ...]:
        """The ids of every stored ``Inspection`` job, sorted."""
        if not self._directory.is_dir():
            return ()
        ids: list[str] = []
        for path in sorted(self._directory.glob(INSPECTION_JOB_GLOB)):
            if _RECORD_NAME_RE.match(path.name):
                ids.append(path.name[len("inspection-job-") : -len(".json")])
        return tuple(ids)

    def load(self, job_id: str) -> InspectionJob:
        """Load one job. Corrupt/missing lifecycle metadata → ``Inspection``.

        Raises :class:`CorruptJobRecordError` when the record cannot be
        represented as an :class:`InspectionJob` at all — such a record is
        unusable data but still never shareable (it has no confirmed
        contract, so :func:`resolve_export_request` refuses its id).
        """
        path = self._path_for(job_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise JobStoreError(f"no stored job record at {path}") from exc
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise CorruptJobRecordError(
                f"job record {path.name} is not readable as JSON; the record "
                f"is treated as Inspection (unshareable) but cannot be loaded"
            ) from exc
        if not isinstance(payload, dict):
            raise CorruptJobRecordError(
                f"job record {path.name} is not a mapping; the record is "
                f"treated as Inspection (unshareable) but cannot be loaded"
            )
        # Fail closed (R1): whatever the stored lifecycle claims — missing,
        # garbage, or a crafted "diagnosis" — the record loads as Inspection.
        payload["lifecycle"] = "inspection"
        try:
            return InspectionJob.model_validate(payload)
        except ValidationError as exc:
            raise CorruptJobRecordError(
                f"job record {path.name} failed validation on "
                f"{exc.error_count()} field(s); the record is treated as "
                f"Inspection (unshareable) but cannot be loaded"
            ) from exc

    def edit(
        self,
        job_id: str,
        *,
        title: str | None = None,
        situation: str | None = None,
        desired_outcome: str | None = None,
    ) -> InspectionJob:
        """Replace draft text on a stored job. Never changes the lifecycle."""
        updated = self.load(job_id).edited(
            title=title, situation=situation, desired_outcome=desired_outcome
        )
        self.save(updated)
        return updated

    def discard(self, job_id: str) -> Path:
        """Remove one ``Inspection`` job's bytes from disk, verified.

        Uses the M1 deletion discipline (overwrite, unlink, verify absence);
        a surviving file raises :class:`DeletionVerificationError` rather
        than reporting a discard that did not happen. Discarding a job that
        does not exist refuses (a discard the person asked for must be real).
        """
        path = self._path_for(job_id)
        if not path.exists():
            raise JobStoreError(
                f"no stored job record at {path}; refusing to report a "
                f"discard that removed nothing"
            )
        _remove_file_verified(path)
        return path

    def confirm(
        self,
        job_id: str,
        *,
        success_evidence: tuple[str, ...],
        boundaries: JobBoundaries,
        importance: JobImportance,
        cadence: JobCadence,
        confirmed_at: datetime,
        situation: str | None = None,
        desired_outcome: str | None = None,
    ) -> SuccessContract:
        """The ONLY exit from ``Inspection``: explicit user confirmation.

        The person supplies the contract's success evidence, boundaries,
        importance, cadence, and the confirmation moment explicitly — none
        of these exist on the draft, so no code path can synthesize a
        contract from stored data alone. Situation and desired outcome
        default to the drafts the person reviewed and edited.

        On success the ``Inspection`` record's bytes are removed from disk
        (verified) and the confirmed contract is returned. If contract
        validation fails, the job simply remains in ``Inspection``.
        """
        job = self.load(job_id)
        contract = SuccessContract(
            job_id=job.job_id,
            situation=job.situation if situation is None else situation,
            desired_outcome=(
                job.desired_outcome if desired_outcome is None else desired_outcome
            ),
            success_evidence=success_evidence,
            boundaries=boundaries,
            importance=importance,
            cadence=cadence,
            confirmed_at=confirmed_at,
        )
        self.discard(job_id)
        return contract


# --------------------------------------------------------------------------
# Type-level exclusion from every sharing / Card / export / telemetry payload
# --------------------------------------------------------------------------


@final
class ConfirmedJobExport(InventoriedModel):
    """The only job payload any sharing/Card/export/telemetry surface may hold.

    Its ``jobs`` field is typed ``tuple[SuccessContract, ...]``: an
    ``Inspection``-state job is unrepresentable here by construction — a
    distinct type with different required fields and a different lifecycle
    literal fails validation outright (R1: type-level exclusion, not
    runtime filtering). And per the M1/M2 G2 posture, even this payload's
    ``dump_for_transmission`` refuses: no field in the product declares
    sharing, so nothing leaves the machine at this milestone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Confirmed Success Contracts only. Never empty: an export of nothing
    #: is refused rather than silently sent.
    jobs: tuple[SuccessContract, ...] = Field(min_length=1)


def resolve_export_request(
    requested_job_ids: tuple[str, ...],
    confirmed_contracts: dict[str, SuccessContract],
) -> ConfirmedJobExport:
    """Resolve a by-id export request against confirmed contracts only.

    The hostile fixture this guards (R1): a crafted export request
    referencing an ``Inspection``-state job id. Any requested id that does
    not name a confirmed :class:`SuccessContract` — an ``Inspection`` job,
    a discarded job, an id that never existed — raises
    :class:`InspectionExclusionError`. The refusal is uniform: it never
    discloses which of those the id was.
    """
    missing = tuple(
        job_id for job_id in requested_job_ids if job_id not in confirmed_contracts
    )
    if missing:
        raise InspectionExclusionError(
            f"export request references {len(missing)} job id(s) with no "
            f"confirmed Success Contract; Inspection-state and unknown jobs "
            f"are excluded from every sharing, Card, export, and telemetry "
            f"payload (R1)"
        )
    if not requested_job_ids:
        raise InspectionExclusionError(
            "export request references no confirmed jobs; nothing to share"
        )
    return ConfirmedJobExport(
        jobs=tuple(confirmed_contracts[job_id] for job_id in requested_job_ids)
    )
