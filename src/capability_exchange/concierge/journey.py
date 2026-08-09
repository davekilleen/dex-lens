"""The local, read-only M3 concierge journey domain.

This module owns product state, not HTTP transport.  A server integration only
needs to call the small transition methods on :class:`ConciergeJourney` and
render the corresponding view.  In particular, the journey never constructs a
``SuccessContract`` itself: every confirmed contract is created by
``InspectionJobStore.confirm`` from the person's supplied fields.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, TypeAlias

from capability_exchange.adapter import AdapterContract, AdapterResultEnvelope
from capability_exchange.capmap.model import CapabilityMap
from capability_exchange.capmap.render import render_capability_map
from capability_exchange.diagnosis import assess
from capability_exchange.evidence import EvidenceLevel
from capability_exchange.jobs import (
    CandidateJobProposal,
    InspectionJob,
    InspectionJobStore,
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
    propose_candidate_jobs,
    to_inspection_job,
)
from capability_exchange.jobs.inspection import delete_inspection_jobs

__all__ = [
    "CollectionFallback",
    "ConciergeAdapter",
    "ConciergeJourney",
    "ConciergeStage",
    "ContractFields",
    "InspectionPermission",
    "FallbackEvidence",
    "FallbackMode",
    "JobDraftFields",
    "PermissionMetadata",
    "SuccessContractFields",
    "JourneyError",
    "JourneyStateError",
]


class JourneyError(Exception):
    """Base class for fail-closed journey transition errors."""


class JourneyStateError(JourneyError):
    """A transition is not valid for the current explicit stage."""


class ConciergeStage(StrEnum):
    """Machine-readable stages for the read-only six-stage journey.

    ``DOORWAY`` is an alias for integrations that model opening the command as
    a transition.  A newly-created journey is already at the unscanned
    ``PERMISSION`` screen, because opening it has not read anything.
    """

    DOORWAY = "permission"
    PERMISSION = "permission"
    COLLECTING = "collecting"
    COLLECTION = "collecting"  # integration-friendly alias
    JOB_MAP = "job-map"
    JOB_CONFIRMATION = "job-map"  # integration-friendly alias
    DIAGNOSIS = "diagnosis"
    CAPABILITY_MAP = "capability-map"
    FALLBACK = "fallback"
    CLOSED = "closed"


class FallbackMode(StrEnum):
    """Evidence collection paths when a deep adapter is unavailable."""

    GUIDED = "guided"
    EXPORT_ASSISTED = "export-assisted"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _lines(value: Iterable[str], field: str) -> tuple[str, ...]:
    result = tuple(str(item) for item in value)
    for item in result:
        if not item.strip():
            raise ValueError(f"{field} entries must be non-empty")
        if any(ord(char) < 32 or ord(char) == 127 for char in item):
            raise ValueError(f"{field} entries cannot contain control characters")
    return result


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field} cannot contain control characters")
    return value


@dataclass(frozen=True, slots=True)
class PermissionMetadata:
    """The exact pre-read boundary shown on the permission screen.

    ``approved_artifacts`` contains probe/artifact identifiers rather than
    inferred file contents.  ``exclusions`` is the explicit deny list.  The
    local/offline/no-catalog fields are affirmative facts the UI must show,
    not assumptions hidden in copy.
    """

    adapter_id: str
    adapter_version: str
    approved_roots: tuple[str, ...]
    approved_artifacts: tuple[str, ...]
    exclusions: tuple[str, ...]
    local_only: bool
    offline_capable: bool
    no_catalog: bool
    next_action: str

    def __post_init__(self) -> None:
        _text(self.adapter_id, "adapter_id")
        _text(self.adapter_version, "adapter_version")
        _lines(self.approved_roots, "approved_roots")
        _lines(self.approved_artifacts, "approved_artifacts")
        _lines(self.exclusions, "exclusions")
        _text(self.next_action, "next_action")
        if not isinstance(self.local_only, bool):
            raise ValueError("local_only must be a boolean")
        if not isinstance(self.offline_capable, bool):
            raise ValueError("offline_capable must be a boolean")
        if not isinstance(self.no_catalog, bool):
            raise ValueError("no_catalog must be a boolean")
        # Freeze normalised tuples so callers cannot smuggle a mutable list into
        # the consent record after the page has been rendered.
        object.__setattr__(self, "approved_roots", tuple(map(str, self.approved_roots)))
        object.__setattr__(self, "approved_artifacts", tuple(map(str, self.approved_artifacts)))
        object.__setattr__(self, "exclusions", tuple(map(str, self.exclusions)))

    @classmethod
    def from_contract(
        cls,
        contract: AdapterContract,
        *,
        approved_roots: Iterable[str | Path] | None = None,
        approved_artifacts: Iterable[str] | None = None,
        next_action: str = "Approve this read-only inspection",
        no_catalog: bool = True,
        offline_capable: bool = True,
    ) -> PermissionMetadata:
        """Build display metadata from a versioned adapter contract."""

        roots = tuple(str(root) for root in (approved_roots or contract.read_scope))
        artifacts = tuple(approved_artifacts or contract.evidence_probes)
        return cls(
            adapter_id=contract.adapter_id,
            adapter_version=contract.contract_version,
            approved_roots=roots,
            approved_artifacts=artifacts,
            exclusions=tuple(contract.denied_paths),
            local_only=True,
            offline_capable=offline_capable,
            no_catalog=no_catalog,
            next_action=next_action,
        )

    # These aliases keep integration code aligned with AdapterContract's
    # vocabulary while retaining the person-facing names above.
    @property
    def contract_version(self) -> str:
        return self.adapter_version

    @property
    def read_scope(self) -> tuple[str, ...]:
        return self.approved_roots

    @property
    def approved_paths(self) -> tuple[str, ...]:
        return self.approved_roots

    @property
    def denied_paths(self) -> tuple[str, ...]:
        return self.exclusions

    @property
    def excluded_paths(self) -> tuple[str, ...]:
        return self.exclusions

    @property
    def offline(self) -> bool:
        return self.offline_capable

    @property
    def local(self) -> bool:
        return self.local_only

    @property
    def catalog_available(self) -> bool:
        return not self.no_catalog

    @property
    def next_step(self) -> str:
        return self.next_action

    @property
    def version(self) -> str:
        """Short alias used by adapters that call this the adapter version."""

        return self.adapter_version

    @property
    def no_verified_catalog(self) -> bool:
        """Alias for integrations that spell out the offline catalog state."""

        return self.no_catalog

    @property
    def catalog_status(self) -> str:
        return "none" if self.no_catalog else "verified"


@dataclass(frozen=True, slots=True)
class JobDraftFields:
    """Editable, provisional text used to create an ``InspectionJob``."""

    title: str
    situation: str
    desired_outcome: str
    job_id: str | None = None
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.title, "title")
        _text(self.situation, "situation")
        _text(self.desired_outcome, "desired_outcome")
        if self.job_id is not None:
            _text(self.job_id, "job_id")
        _lines(self.evidence_references, "evidence_references")
        object.__setattr__(self, "evidence_references", tuple(self.evidence_references))


@dataclass(frozen=True, slots=True)
class ContractFields:
    """All person-supplied fields required to leave ``Inspection``."""

    success_evidence: tuple[str, ...]
    importance: JobImportance | str
    cadence: JobCadence | str
    privacy_limits: tuple[str, ...] = ()
    approval_limits: tuple[str, ...] = ()
    autonomy_limits: tuple[str, ...] = ()
    confirmed_at: datetime | None = None
    situation: str | None = None
    desired_outcome: str | None = None
    boundaries: JobBoundaries | None = None

    def __post_init__(self) -> None:
        # Do not invent evidence, limits, importance, or cadence. Empty tuples
        # remain meaningful explicit user input and are rejected by the store
        # only where the Success Contract requires at least one signal.
        object.__setattr__(self, "success_evidence", tuple(self.success_evidence))
        object.__setattr__(self, "privacy_limits", tuple(self.privacy_limits))
        object.__setattr__(self, "approval_limits", tuple(self.approval_limits))
        object.__setattr__(self, "autonomy_limits", tuple(self.autonomy_limits))
        object.__setattr__(self, "importance", JobImportance(self.importance))
        object.__setattr__(self, "cadence", JobCadence(self.cadence))
        for field_name in (
            "success_evidence",
            "privacy_limits",
            "approval_limits",
            "autonomy_limits",
        ):
            _lines(getattr(self, field_name), field_name)
        if self.situation is not None:
            _text(self.situation, "situation")
        if self.desired_outcome is not None:
            _text(self.desired_outcome, "desired_outcome")
        if self.confirmed_at is not None and (
            self.confirmed_at.tzinfo is None
            or self.confirmed_at.tzinfo.utcoffset(self.confirmed_at) is None
        ):
            raise ValueError("confirmed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FallbackEvidence:
    """One fallback claim with an honest, capped Evidence Level."""

    label: str
    level: EvidenceLevel | str
    detail: str

    def __post_init__(self) -> None:
        _text(self.label, "label")
        _text(self.detail, "detail")
        level = EvidenceLevel(self.level)
        # Guided/export-assisted material is never direct inspection.  A
        # caller attempting to claim Verified is downgraded to Unknown rather
        # than allowing an unsafe display claim.
        if level is EvidenceLevel.VERIFIED:
            level = EvidenceLevel.UNKNOWN
        object.__setattr__(self, "level", level)


@dataclass(frozen=True, slots=True)
class CollectionFallback:
    """Honest result when no contained deep adapter can collect evidence."""

    mode: FallbackMode | str
    reason: str
    evidence: tuple[FallbackEvidence, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", FallbackMode(self.mode))
        _text(self.reason, "reason")
        object.__setattr__(self, "evidence", tuple(self.evidence))


CollectionResult: TypeAlias = AdapterResultEnvelope | CollectionFallback

# Naming aliases keep the narrow integration surface discoverable without
# creating duplicate state models.
InspectionPermission = PermissionMetadata
SuccessContractFields = ContractFields


class ConciergeAdapter(Protocol):
    """The deliberately narrow adapter surface consumed by the journey."""

    permission: PermissionMetadata | AdapterContract

    def collect(self) -> CollectionResult:
        """Collect under the already approved scope, or return a fallback."""


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "manual-job"


class ConciergeJourney:
    """Explicit state machine for M3 stages 1–6.

    The class has no HTTP, filesystem-read, or mutation capability.  Its only
    filesystem writes are the local ``InspectionJobStore`` records required by
    R1; ``close``/``decline`` verifiably remove every remaining draft.
    """

    def __init__(
        self,
        *,
        permission: PermissionMetadata | AdapterContract | None = None,
        adapter: ConciergeAdapter | object | None = None,
        collector: Callable[[], CollectionResult] | None = None,
        job_store: InspectionJobStore | Path,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.now = now
        if isinstance(job_store, Path):
            job_store = InspectionJobStore(job_store)
        self.job_store = job_store
        self.permission = self._resolve_permission(permission, adapter)
        self._collector = self._resolve_collector(collector, adapter)

        self.stage = ConciergeStage.PERMISSION
        self.envelope: AdapterResultEnvelope | None = None
        self.fallback: CollectionFallback | None = None
        self.proposals: tuple[CandidateJobProposal, ...] = ()
        self._confirmed: dict[str, SuccessContract] = {}
        self._selected: set[str] = set()
        self.capability_map: CapabilityMap | None = None
        self.capability_map_markdown = ""

    @staticmethod
    def _resolve_permission(
        permission: PermissionMetadata | AdapterContract | None,
        adapter: ConciergeAdapter | object | None,
    ) -> PermissionMetadata:
        candidate: object | None = permission
        if candidate is None and adapter is not None:
            candidate = getattr(adapter, "permission", None)
            if candidate is None:
                candidate = getattr(adapter, "contract", None)
        if isinstance(candidate, PermissionMetadata):
            return candidate
        if isinstance(candidate, AdapterContract):
            return PermissionMetadata.from_contract(candidate)
        raise ValueError(
            "a permission metadata record or versioned AdapterContract is required"
        )

    @staticmethod
    def _resolve_collector(
        collector: Callable[[], CollectionResult] | None,
        adapter: ConciergeAdapter | object | None,
    ) -> Callable[[], CollectionResult]:
        if collector is not None:
            return collector
        if adapter is not None:
            candidate = getattr(adapter, "collect", None)
            if callable(candidate):
                return candidate
        raise ValueError("a narrow adapter collect() callable is required")

    @property
    def metadata(self) -> PermissionMetadata:
        """Integration-friendly alias for the permission record."""

        return self.permission

    @property
    def job_ids(self) -> tuple[str, ...]:
        return self.job_store.job_ids()

    @property
    def inspection_jobs(self) -> tuple[InspectionJob, ...]:
        jobs: list[InspectionJob] = []
        for job_id in self.job_store.job_ids():
            try:
                jobs.append(self.job_store.load(job_id))
            except Exception:
                # Corrupt records are still fail-closed Inspection state, but
                # cannot be rendered as editable fields.
                continue
        return tuple(jobs)

    @property
    def contracts(self) -> tuple[SuccessContract, ...]:
        return tuple(self._confirmed[job_id] for job_id in sorted(self._confirmed))

    @property
    def confirmed_contracts(self) -> tuple[SuccessContract, ...]:
        return self.contracts

    @property
    def selected_job_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._selected))

    @property
    def pending_job_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._selected - self._confirmed.keys()))

    def _require(self, *allowed: ConciergeStage) -> None:
        if self.stage is ConciergeStage.CLOSED:
            raise JourneyStateError("the concierge session is closed")
        if self.stage not in allowed:
            names = ", ".join(stage.value for stage in allowed)
            raise JourneyStateError(
                f"stage {self.stage.value!r} does not permit this action; expected {names}"
            )

    def approve(self) -> CollectionResult:
        """Approve the exact scope and run the adapter once.

        The collector is not called by construction or rendering.  Only this
        explicit transition can move a journey beyond the unscanned screen.
        """

        self.begin_collection()
        try:
            result = self._collector()
        except Exception:
            # A collector that can safely continue without direct evidence
            # returns an explicit CollectionFallback. Exceptions are terminal:
            # cancellation, scope drift, or an unexpected adapter failure must
            # never be turned into a resumable state by this layer.
            self.close()
            raise

        return self.complete_collection(result)

    def begin_collection(self) -> None:
        """Enter collection synchronously before work moves off-thread."""

        self._require(ConciergeStage.PERMISSION)
        self.stage = ConciergeStage.COLLECTING

    def complete_collection(self, result: CollectionResult) -> CollectionResult:
        """Publish one completed result while the session owns its state lock."""

        self._require(ConciergeStage.COLLECTING)

        if isinstance(result, CollectionFallback):
            self.envelope = None
            self.proposals = ()
            self.fallback = result
            self.stage = ConciergeStage.FALLBACK
            return result
        if not isinstance(result, AdapterResultEnvelope):
            self.close()
            raise JourneyError("adapter returned neither an envelope nor an honest fallback")

        self.envelope = result
        self.proposals = propose_candidate_jobs(result)
        created_at = self.now()
        for proposal in self.proposals:
            self.job_store.save(to_inspection_job(proposal, created_at=created_at))
        self._selected = set(self.job_store.job_ids())
        self.stage = ConciergeStage.JOB_MAP
        return result

    def add_job(
        self,
        fields: JobDraftFields | None = None,
        **kwargs: Any,
    ) -> InspectionJob:
        """Add a manual ``Inspection`` draft; no confirmation is implied."""

        self._require(ConciergeStage.JOB_MAP)
        if fields is not None and kwargs:
            raise TypeError("pass JobDraftFields or keyword fields, not both")
        if fields is None:
            fields = JobDraftFields(**kwargs)
        job_id = fields.job_id or _slug(fields.title)
        existing = set(self.job_store.job_ids()) | set(self._confirmed)
        if fields.job_id is not None and job_id in existing:
            raise JourneyStateError("a job with that id already exists in this session")
        if fields.job_id is None:
            suffix = 1
            candidate = job_id
            while candidate in existing:
                suffix += 1
                candidate = f"{job_id}-{suffix}"
            job_id = candidate
        job = InspectionJob(
            job_id=job_id,
            title=fields.title,
            situation=fields.situation,
            desired_outcome=fields.desired_outcome,
            evidence_references=fields.evidence_references,
            created_at=self.now(),
        )
        self.job_store.save(job)
        self._selected.add(job.job_id)
        return job

    def edit_job(
        self,
        job_id: str,
        fields: JobDraftFields | None = None,
        **kwargs: Any,
    ) -> InspectionJob:
        """Edit only the provisional text through ``InspectionJobStore``."""

        self._require(ConciergeStage.JOB_MAP)
        if fields is not None and kwargs:
            raise TypeError("pass JobDraftFields or keyword fields, not both")
        if fields is None:
            current = self.job_store.load(job_id)
            fields = JobDraftFields(
                job_id=job_id,
                title=str(kwargs.get("title", current.title)),
                situation=str(kwargs.get("situation", current.situation)),
                desired_outcome=str(
                    kwargs.get("desired_outcome", current.desired_outcome)
                ),
                evidence_references=current.evidence_references,
            )
        return self.job_store.edit(
            job_id,
            title=fields.title,
            situation=fields.situation,
            desired_outcome=fields.desired_outcome,
        )

    def discard_job(self, job_id: str) -> None:
        """Discard one draft and remove it from the selected set."""

        self._require(ConciergeStage.JOB_MAP)
        self.job_store.discard(job_id)
        self._selected.discard(job_id)

    def select_jobs(self, job_ids: Iterable[str]) -> tuple[str, ...]:
        """Choose which retained drafts must be confirmed for diagnosis."""

        self._require(ConciergeStage.JOB_MAP)
        requested = set(job_ids)
        known = set(self.job_store.job_ids()) | set(self._confirmed)
        unknown = requested - known
        if unknown:
            raise JourneyStateError("selection references a job that is not in this session")
        self._selected = requested | set(self._confirmed)
        return self.selected_job_ids

    def confirm_job(
        self,
        job_id: str,
        fields: ContractFields | None = None,
        **kwargs: Any,
    ) -> SuccessContract:
        """Confirm one draft with every contract field supplied by the person."""

        self._require(ConciergeStage.JOB_MAP)
        if fields is not None and kwargs:
            raise TypeError("pass ContractFields or keyword fields, not both")
        if fields is None:
            fields = ContractFields(**kwargs)
        if job_id not in self._selected:
            raise JourneyStateError("confirm the job only after selecting it for diagnosis")
        confirmed_at = self.now() if fields.confirmed_at is None else fields.confirmed_at
        boundaries = fields.boundaries or JobBoundaries(
            privacy_limits=fields.privacy_limits,
            approval_limits=fields.approval_limits,
            autonomy_limits=fields.autonomy_limits,
        )
        # Deliberately no direct contract construction here.  This is the sole
        # confirmation exit and the store owns validation + byte deletion.
        contract = self.job_store.confirm(
            job_id,
            success_evidence=fields.success_evidence,
            boundaries=boundaries,
            importance=fields.importance,
            cadence=fields.cadence,
            confirmed_at=confirmed_at,
            situation=fields.situation,
            desired_outcome=fields.desired_outcome,
        )
        self._confirmed[job_id] = contract
        self._selected.discard(job_id)
        return contract

    def diagnose(self) -> CapabilityMap:
        """Run diagnosis only after every selected draft is confirmed."""

        self._require(ConciergeStage.JOB_MAP, ConciergeStage.DIAGNOSIS)
        if self.envelope is None:
            raise JourneyStateError("diagnosis requires a collected adapter envelope")
        if self.pending_job_ids:
            raise JourneyStateError(
                "diagnosis is unavailable until every selected job is confirmed"
            )
        if not self._confirmed:
            raise JourneyStateError("diagnosis requires at least one confirmed Success Contract")
        self.stage = ConciergeStage.DIAGNOSIS
        self.capability_map = assess(
            self.contracts,
            self.envelope,
            assessed_at=self.now(),
        )
        self.capability_map_markdown = render_capability_map(self.capability_map)
        self.stage = ConciergeStage.CAPABILITY_MAP
        return self.capability_map

    def close(self) -> None:
        """Close and clean up local state, regardless of the current stage."""

        if self.stage is ConciergeStage.CLOSED:
            return
        # The registered deletion path applies the same verified unlink
        # discipline as the underlying store.  Confirmed drafts are already
        # gone; unconfirmed drafts are removed here at every exit.
        try:
            delete_inspection_jobs(self.job_store.directory)
        finally:
            # Terminal in-memory state is unconditional even when byte-level
            # deletion reports an incident to the owning session.
            self.envelope = None
            self.fallback = None
            self.proposals = ()
            self._confirmed.clear()
            self._selected.clear()
            self.capability_map = None
            self.capability_map_markdown = ""
            self.stage = ConciergeStage.CLOSED

    def decline(self) -> None:
        """Alias used by the permission screen's leave action."""

        self.close()

    def cancel(self) -> None:
        """Alias used by an in-flight collection cancellation control."""

        self.close()
