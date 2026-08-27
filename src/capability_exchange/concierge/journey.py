"""The local concierge journey domain for diagnosis, adaptation, and contribution.

This module owns product state, not HTTP transport.  A server integration only
needs to call the small transition methods on :class:`ConciergeJourney` and
render the corresponding view.  In particular, the journey never constructs a
``SuccessContract`` itself: every confirmed contract is created by
``InspectionJobStore.confirm`` from the person's supplied fields.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, TypeAlias, runtime_checkable

from capability_exchange.adapter import (
    AdapterContract,
    AdapterMode,
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.capmap.model import CapabilityMap
from capability_exchange.capmap.render import render_capability_map
from capability_exchange.cards import (
    CapabilityCard,
    DisclosureManifest,
    build_disclosure_manifest,
    canonical_card_bytes,
    require_valid_card,
)
from capability_exchange.catalogue.bridge import (
    RankedCapabilityMatch,
    rank_capability_shelf,
    render_portable_brief_markdown,
)
from capability_exchange.catalogue.fetch import CatalogueFetchResult
from capability_exchange.catalogue.subscription import CatalogueSubscriptionRecord
from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.contribution import (
    ConsentLedger,
    Contribution,
    ContributionLifecycle,
    ContributionState,
    PermissionSet,
)
from capability_exchange.contribution.lifecycle import StorePort
from capability_exchange.contribution.privacy import (
    ContributionCandidate,
    ContributionDeclineStore,
    ContributionPrivacyGate,
    ContributionPrivacyPreview,
    candidate_from_proposal,
    user_initiated_candidate,
)
from capability_exchange.diagnosis import assess
from capability_exchange.evidence import EvidenceItem, EvidenceLevel, EvidenceState
from capability_exchange.evidence.item import reference_rejection_reason
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
from capability_exchange.jobs.contract import validate_job_id
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
    "FALLBACK_MAX_EVIDENCE",
    "JobDraftFields",
    "PermissionMetadata",
    "SuccessContractFields",
    "AdaptationRefusedError",
    "AdaptationSelection",
    "ContributionEgressError",
    "ContributionHandle",
    "DurableContributionIntakePort",
    "ContributionVersionComparison",
    "ContributionIdentityPort",
    "ContributionIntakePort",
    "SubmissionReceipt",
    "WithdrawalReceipt",
    "JourneyError",
    "JourneyStateError",
]


# Fallback evidence is session-only, but still needs a product bound.  These
# limits stop the guided/import path becoming an unbounded raw-data channel.
FALLBACK_TEXT_MAX_LENGTH = 512
FALLBACK_IMPORT_LINE_MAX_LENGTH = 2048
FALLBACK_MAX_EVIDENCE = 32


class JourneyError(Exception):
    """Base class for fail-closed journey transition errors."""


class JourneyStateError(JourneyError):
    """A transition is not valid for the current explicit stage."""


class AdaptationRefusedError(JourneyError):
    """An adaptation failed a named safety gate before preview or mutation."""


class ContributionEgressError(JourneyError):
    """Contribution authorization or intake confirmation failed closed."""


class ContributionIdentityPort(Protocol):
    """External identity seam used only after an explicit contribution choice."""

    def contributor_secret(self) -> bytes:
        """Return local secret material used only for pseudonymous provenance."""


@dataclass(frozen=True, slots=True)
class ContributionHandle:
    """Private control-plane handle bound to exact payload bytes.

    The Card version identifier is deliberately absent.  Intake correlates the
    payload by its manifest byte hash and proves later revocation authority with
    the private token.  The token is never rendered or included in ``repr``.
    """

    manifest_byte_hash: str
    revocation_token: str = dataclass_field(repr=False)
    consent_hash: str
    idempotency_key: str
    permissions: PermissionSet

    def __post_init__(self) -> None:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.manifest_byte_hash):
            raise ValueError("contribution handle requires an exact manifest byte hash")
        if not isinstance(self.revocation_token, str) or len(self.revocation_token) < 32:
            raise ValueError("contribution handle requires private revocation authority")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.consent_hash):
            raise ValueError("contribution handle requires an exact consent hash")
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key:
            raise ValueError("contribution handle requires an idempotency key")
        if self.permissions.is_unresolvable:
            raise ValueError("contribution handle permissions must be fully resolved")

    @property
    def receipt_binding(self) -> str:
        material = (
            self.manifest_byte_hash.encode("ascii")
            + b"\0"
            + self.revocation_token.encode("ascii")
        )
        return "sha256:" + hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class ContributionVersionComparison:
    """Exact, local comparison shown before a revised Card can be disclosed."""

    previous_version_hash: str
    revised_version_hash: str
    changed_fields: tuple[str, ...]
    previous_exact_json: str
    revised_exact_json: str


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    manifest_byte_hash: str
    handle_binding: str
    accepted: bool


@dataclass(frozen=True, slots=True)
class WithdrawalReceipt:
    manifest_byte_hash: str
    handle_binding: str
    withdrawn: bool


class ContributionIntakePort(Protocol):
    """Narrow contribution seam: exact bytes in, version withdrawal out."""

    def submit(
        self, payload: bytes, /, *, handle: ContributionHandle
    ) -> SubmissionReceipt:
        """Accept exact disclosure bytes plus a separate private control handle."""

    def withdraw(self, handle: ContributionHandle, /) -> WithdrawalReceipt:
        """Revoke the exact accepted payload and prove it was previously active."""


@runtime_checkable
class DurableContributionIntakePort(ContributionIntakePort, Protocol):
    """Intake that can prove later withdrawal authority survives this process."""

    def has_durable_withdrawal_authority(
        self, handle: ContributionHandle, /
    ) -> bool:
        """Return true only when an exact affirmative receipt is durably recoverable."""


class ConciergeStage(StrEnum):
    """Machine-readable stages for the read-only and adaptation journey.

    ``DOORWAY`` is an alias for integrations that model opening the command as
    a transition.  A newly-created journey is already at the unscanned
    ``PERMISSION`` screen, because opening it has not read anything.  The
    adaptation stages deliberately remain separate from diagnosis: each one
    permits exactly one next action and no stage carries a write capability.
    """

    DOORWAY = "permission"
    PERMISSION = "permission"
    COLLECTING = "collecting"
    COLLECTION = "collecting"  # integration-friendly alias
    JOB_MAP = "job-map"
    JOB_CONFIRMATION = "job-map"  # integration-friendly alias
    DIAGNOSIS = "diagnosis"
    CAPABILITY_MAP = "capability-map"
    CATALOGUE_SHELF = "catalogue-shelf"
    CATALOGUE_BRIEF = "catalogue-brief"
    FALLBACK = "fallback"
    CLOSED = "closed"
    ADAPTATION_SELECT = "adaptation-select"
    ADAPTATION_PREVIEW = "adaptation-preview"
    ADAPTATION_APPROVAL = "adaptation-approval"
    ADAPTATION_APPLY = "adaptation-apply"
    ADAPTATION_RECEIPT = "adaptation-receipt"
    ADAPTATION_VERIFY = "adaptation-verify"
    ADAPTATION_UNDO = "adaptation-undo"
    ADAPTATION_REFUSED = "adaptation-refused"
    ADAPTATION_HARD_STOP = "adaptation-hard-stop"
    ADAPT_SELECT = "adaptation-select"
    ADAPT_PREVIEW = "adaptation-preview"
    ADAPT_APPROVAL = "adaptation-approval"
    ADAPT_APPLY = "adaptation-apply"
    ADAPT_RECEIPT = "adaptation-receipt"
    ADAPT_VERIFY = "adaptation-verify"
    UNDO = "adaptation-undo"
    CONTRIBUTION_BUILD = "contribution-build"
    CONTRIBUTION_PRIVACY = "contribution-privacy"
    CONTRIBUTION_PRIVACY_CONFIRM = "contribution-privacy-confirm"
    CONTRIBUTION_REVIEW = "contribution-review"
    CONTRIBUTION_DISCLOSE = "contribution-disclose"
    CONTRIBUTION_APPROVE = "contribution-approve"
    CONTRIBUTION_SUBMIT = "contribution-submit"
    CONTRIBUTION_WITHDRAW = "contribution-withdraw"


@dataclass(frozen=True, slots=True)
class AdaptationSelection:
    """One explicit, bounded adaptation choice awaiting preview."""

    job_id: str
    capability_id: str
    approved_skills_root: Path
    markdown: str
    expected_benefit: str
    observable_signal: str

    def __post_init__(self) -> None:
        validate_job_id(self.job_id)
        _text(self.capability_id, "capability_id")
        if not isinstance(self.markdown, str) or not self.markdown.strip():
            raise ValueError("markdown must be non-empty text")
        if len(self.markdown.encode("utf-8")) > 262_144:
            raise ValueError("markdown exceeds the bounded adaptation preview size")
        if any(
            ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127
            for char in self.markdown
        ):
            raise ValueError("markdown contains unsupported control characters")
        _text(self.expected_benefit, "expected_benefit")
        _text(self.observable_signal, "observable_signal")
        object.__setattr__(self, "approved_skills_root", Path(self.approved_skills_root))


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


def _bounded_text(value: str, field: str, *, limit: int = FALLBACK_TEXT_MAX_LENGTH) -> str:
    """Validate one bounded fallback value without accepting a payload."""

    validated = _text(value, field)
    if len(validated) > limit:
        raise ValueError(
            f"{field} exceeds {limit} characters; fallback input is bounded "
            "and never a raw payload"
        )
    return validated


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
    #: The host family the signed catalogue uses for this adapter. Empty
    #: falls back to ``adapter_id``, which is only correct for an adapter
    #: whose implementation id and catalogue host family coincide.
    catalogue_host_adapter: str = ""

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
        catalogue_host_adapter: str = "",
    ) -> PermissionMetadata:
        """Build display metadata from a versioned adapter contract."""

        roots = tuple(str(root) for root in (approved_roots or contract.read_scope))
        artifacts = tuple(approved_artifacts or contract.evidence_probes)
        return cls(
            catalogue_host_adapter=catalogue_host_adapter,
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

    @property
    def catalogue_host(self) -> str:
        """The identifier to compare against a catalogue entry's host list."""
        return self.catalogue_host_adapter or self.adapter_id

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
    # A locator/digest supplied by the person.  It is deliberately optional
    # for backwards-compatible in-memory construction; the continuation path
    # creates a synthetic ``fallback:<label>`` locator when it is omitted.
    reference: str | None = None
    # Optional probe vocabulary lets supplied material ground a matching
    # Foundation Capability rule without ever claiming direct observation.
    probe_id: str | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.label, "label")
        detail = _bounded_text(self.detail, "detail")
        if "-----BEGIN" in detail:
            raise ValueError(
                "detail contains key/secret block markers; raw content is not evidence"
            )
        level = EvidenceLevel(self.level)
        # Guided/export-assisted material is never direct inspection.  A
        # caller attempting to claim Verified is downgraded to Unknown rather
        # than allowing an unsafe display claim.
        if level is EvidenceLevel.VERIFIED:
            level = EvidenceLevel.UNKNOWN
        object.__setattr__(self, "level", level)
        if self.reference is not None:
            if not isinstance(self.reference, str) or not self.reference.strip():
                raise ValueError("reference must be a non-empty locator or digest")
            reason = reference_rejection_reason(self.reference)
            if reason is not None:
                raise ValueError(reason)
        if self.probe_id is not None:
            object.__setattr__(self, "probe_id", validate_job_id(self.probe_id))


@dataclass(frozen=True, slots=True)
class CollectionFallback:
    """Honest result when no contained deep adapter can collect evidence."""

    mode: FallbackMode | str
    reason: str
    evidence: tuple[FallbackEvidence, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", FallbackMode(self.mode))
        _bounded_text(self.reason, "reason")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if len(self.evidence) > FALLBACK_MAX_EVIDENCE:
            raise ValueError(
                f"fallback evidence is limited to {FALLBACK_MAX_EVIDENCE} items"
            )


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
    """Explicit state machine for M3-M5 stages 1-9.

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
        adapter_contract: AdapterContract | None = None,
    ) -> None:
        self.now = now
        self.permission = self._resolve_permission(permission, adapter)
        self._adapter_contract = adapter_contract
        if isinstance(job_store, Path):
            job_store = InspectionJobStore(job_store)
        self._require_job_store_outside_scope(job_store, self.permission)
        self.job_store = job_store
        self._collector = self._resolve_collector(collector, adapter)

        self.stage = ConciergeStage.PERMISSION
        self.envelope: AdapterResultEnvelope | None = None
        self.fallback: CollectionFallback | None = None
        self.proposals: tuple[CandidateJobProposal, ...] = ()
        self._confirmed: dict[str, SuccessContract] = {}
        self._selected: set[str] = set()
        self.capability_map: CapabilityMap | None = None
        self.capability_map_markdown = ""
        self.catalogue_fetch_result: CatalogueFetchResult | None = None
        self.catalogue_shelf: tuple[RankedCapabilityMatch, ...] = ()
        self.catalogue_brief_markdown = ""
        self.selected_catalogue_capability_id = ""
        self.selected_catalogue_job_id = ""
        self.catalogue_subscription_record: CatalogueSubscriptionRecord | None = None

        # Adaptation state is deliberately ephemeral in the journey.  The
        # transaction engine owns durable journals, recovery manifests, and
        # receipts; the concierge only retains the currently selected record
        # so a browser cannot widen the approved change between stages.
        self.adaptation_state_root = self.job_store.directory.parent / "adaptation-state"
        self.adaptation_receipt_root = self.job_store.directory.parent / "adaptation-receipts"
        self._adaptation_selection: AdaptationSelection | None = None
        self._adaptation_preview: object | None = None
        self._adaptation_recovery: object | None = None
        self._adaptation_approval: object | None = None
        self._adaptation_result: object | None = None
        self._adaptation_verification: object | None = None
        self._adaptation_undo_result: object | None = None
        self._adaptation_authority: object | None = None
        self._adaptation_engine: object | None = None
        self._adaptation_contract: SuccessContract | None = None
        self._adaptation_refusal = ""
        self._hard_stop_reason = ""

        # M5 contribution dependencies are ports, not embedded services.  A
        # normal account-free diagnosis/adaptation journey never calls them.
        self._contribution_identity: ContributionIdentityPort | None = None
        self._contribution_intake: ContributionIntakePort | None = None
        self._contribution_stores: tuple[StorePort, ...] = ()
        self._contribution_consent: ConsentLedger | None = None
        self._contribution_lifecycle: ContributionLifecycle | None = None
        self._contribution_card: CapabilityCard | None = None
        self._contribution_comparison: ContributionVersionComparison | None = None
        self._contribution_manifest: DisclosureManifest | None = None
        self._contribution: Contribution | None = None
        self._contribution_handle: ContributionHandle | None = None
        self._contribution_privacy_gate = ContributionPrivacyGate()
        self._contribution_decline_store = ContributionDeclineStore(
            self.job_store.directory.parent / "contribution-candidate-declines.json",
            inspected_roots=tuple(Path(root) for root in self.permission.approved_roots),
        )
        self._contribution_candidate: ContributionCandidate | None = None
        self._contribution_privacy_preview: ContributionPrivacyPreview | None = None
        self._pending_contribution_comparison: ContributionVersionComparison | None = None
        self._contribution_return_stage = ConciergeStage.CAPABILITY_MAP
        self._pending_withdrawal_version_hash: str | None = None
        self._intake_submission_attempted = False
        self._pending_withdrawal = False

    def configure_contribution(
        self,
        *,
        identity: ContributionIdentityPort,
        intake: ContributionIntakePort,
        stores: Iterable[StorePort] = (),
    ) -> None:
        """Attach reviewed external ports without invoking identity or egress."""

        if self._contribution_identity is not None or self._contribution_intake is not None:
            raise JourneyStateError("contribution ports are already configured")
        if self.stage not in {
            ConciergeStage.CAPABILITY_MAP,
            ConciergeStage.ADAPTATION_VERIFY,
            ConciergeStage.ADAPTATION_UNDO,
        }:
            raise JourneyStateError(
                "contribution ports may be configured only after account-free diagnosis"
            )
        if not callable(getattr(identity, "contributor_secret", None)):
            raise ValueError("identity port must provide contributor_secret()")
        if not callable(getattr(intake, "submit", None)) or not callable(
            getattr(intake, "withdraw", None)
        ):
            raise ValueError("intake port must provide submit() and withdraw()")
        self._contribution_identity = identity
        self._contribution_intake = intake
        self._contribution_stores = tuple(stores)

    @property
    def contribution_card(self) -> CapabilityCard | None:
        return self._contribution_card

    @property
    def contribution_manifest(self) -> DisclosureManifest | None:
        return self._contribution_manifest

    @property
    def contribution_comparison(self) -> ContributionVersionComparison | None:
        return self._contribution_comparison

    @property
    def contribution(self) -> Contribution | None:
        return self._contribution

    @property
    def contribution_privacy_preview(self) -> ContributionPrivacyPreview | None:
        return self._contribution_privacy_preview

    @property
    def contribution_candidate(self) -> ContributionCandidate | None:
        return self._contribution_candidate

    @property
    def available_contribution_candidates(self) -> tuple[ContributionCandidate, ...]:
        """Safe candidates not permanently declined on this device."""

        candidates: list[ContributionCandidate] = []
        seen: set[str] = set()
        for proposal in self.proposals:
            candidate = candidate_from_proposal(proposal)
            if (
                candidate.candidate_digest not in seen
                and not self._contribution_decline_store.is_declined(candidate)
            ):
                seen.add(candidate.candidate_digest)
                candidates.append(candidate)
        if not self.proposals:
            candidate = user_initiated_candidate()
            if not self._contribution_decline_store.is_declined(candidate):
                candidates.append(candidate)
        return tuple(candidates)

    def configure_contribution_privacy(self, store: ContributionDeclineStore) -> None:
        """Use durable app storage for permanent candidate suppression."""

        if not isinstance(store, ContributionDeclineStore):
            raise TypeError("contribution privacy store is invalid")
        self._contribution_decline_store = store

    @property
    def contribution_available(self) -> bool:
        return self._contribution_identity is not None and self._contribution_intake is not None

    @property
    def has_pending_withdrawal(self) -> bool:
        """Whether close/expiry retained enough authority to retry intake revocation."""

        return self._pending_withdrawal

    @staticmethod
    def _require_job_store_outside_scope(
        job_store: InspectionJobStore,
        permission: PermissionMetadata,
    ) -> None:
        """Keep every draft byte outside the roots promised read-only."""

        store = job_store.directory.expanduser().resolve(strict=False)
        for raw_root in permission.approved_roots:
            root = Path(raw_root).expanduser().resolve(strict=False)
            if store == root or store.is_relative_to(root):
                raise ValueError(
                    "inspection job storage must be outside the approved read scope"
                )

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

    @property
    def fallback_evidence(self) -> tuple[FallbackEvidence, ...]:
        """The bounded person-supplied fallback claims for this session."""

        return () if self.fallback is None else self.fallback.evidence

    def set_fallback_mode(self, mode: FallbackMode | str) -> FallbackMode:
        """Choose guided or export-assisted material while at the fallback."""

        self._require(ConciergeStage.FALLBACK)
        if self.fallback is None:
            raise JourneyStateError("fallback evidence is not available")
        selected = FallbackMode(mode)
        self.fallback = CollectionFallback(
            mode=selected,
            reason=self.fallback.reason,
            evidence=self.fallback.evidence,
        )
        return selected

    def add_fallback_evidence(self, evidence: FallbackEvidence) -> FallbackEvidence:
        """Add one bounded claim without treating it as direct inspection."""

        self._require(ConciergeStage.FALLBACK)
        if self.fallback is None:
            raise JourneyStateError("fallback evidence is not available")
        if not isinstance(evidence, FallbackEvidence):
            raise TypeError("fallback evidence must be a FallbackEvidence record")
        if len(self.fallback.evidence) >= FALLBACK_MAX_EVIDENCE:
            raise ValueError(
                f"fallback evidence is limited to {FALLBACK_MAX_EVIDENCE} items"
            )
        self.fallback = CollectionFallback(
            mode=self.fallback.mode,
            reason=self.fallback.reason,
            evidence=(*self.fallback.evidence, evidence),
        )
        return evidence

    def import_fallback_evidence(
        self,
        text: str | Iterable[FallbackEvidence],
        *,
        mode: FallbackMode | str | None = None,
    ) -> tuple[FallbackEvidence, ...]:
        """Import bounded non-raw evidence lines.

        The deliberately small format is one item per line:
        ``label|level|reference|detail``.  References are validated by the
        same R2 non-raw rule used by ``EvidenceItem``; no imported payload is
        retained or written to the inspected root.
        """

        self._require(ConciergeStage.FALLBACK)
        if self.fallback is None:
            raise JourneyStateError("fallback evidence is not available")
        parsed: list[FallbackEvidence] = []
        if isinstance(text, str):
            if len(text) > FALLBACK_MAX_EVIDENCE * FALLBACK_IMPORT_LINE_MAX_LENGTH:
                raise ValueError("fallback import exceeds the bounded input size")
            lines = tuple(line.strip() for line in text.splitlines() if line.strip())
            if len(lines) > FALLBACK_MAX_EVIDENCE:
                raise ValueError(
                    f"fallback import is limited to {FALLBACK_MAX_EVIDENCE} items"
                )
            for line in lines:
                if len(line) > FALLBACK_IMPORT_LINE_MAX_LENGTH:
                    raise ValueError("fallback import line exceeds the bounded input size")
                parts = [part.strip() for part in line.split("|")]
                if len(parts) != 4:
                    raise ValueError(
                        "each fallback import line must be "
                        "label|level|reference|detail"
                    )
                label, level, reference, detail = parts
                parsed.append(
                    FallbackEvidence(
                        label=label,
                        level=level,
                        reference=reference or None,
                        detail=detail,
                    )
                )
        else:
            for item in text:
                if len(parsed) >= FALLBACK_MAX_EVIDENCE:
                    raise ValueError(
                        f"fallback import is limited to {FALLBACK_MAX_EVIDENCE} items"
                    )
                if not isinstance(item, FallbackEvidence):
                    raise TypeError(
                        "fallback import items must be FallbackEvidence records"
                    )
                parsed.append(item)
        combined = (*self.fallback.evidence, *parsed)
        if len(combined) > FALLBACK_MAX_EVIDENCE:
            raise ValueError(
                f"fallback evidence is limited to {FALLBACK_MAX_EVIDENCE} items"
            )
        self.fallback = CollectionFallback(
            mode=self.fallback.mode if mode is None else FallbackMode(mode),
            reason=self.fallback.reason,
            evidence=combined,
        )
        return tuple(parsed)

    @staticmethod
    def _fallback_state(level: EvidenceLevel) -> EvidenceState:
        """Map fallback labels to non-direct R2 states, fail closed."""

        if level is EvidenceLevel.SUPPORTED:
            return EvidenceState.INFERRED
        if level is EvidenceLevel.REPORTED:
            return EvidenceState.USER_REPORTED
        return EvidenceState.NOT_ASSESSED

    def _fallback_envelope(self) -> AdapterResultEnvelope:
        """Build an ephemeral envelope without manufacturing observations."""

        if self.fallback is None:
            raise JourneyStateError("fallback evidence is not available")
        grouped: dict[str, list[EvidenceItem]] = {}
        for index, item in enumerate(self.fallback.evidence, start=1):
            probe_id = item.probe_id or _slug(item.label)
            # A synthetic locator is a pointer to the in-memory fallback claim,
            # never a copy of its detail or any inspected file content.
            reference = item.reference or f"fallback:{probe_id}:{index}"
            grouped.setdefault(probe_id, []).append(
                EvidenceItem(
                    state=self._fallback_state(item.level),
                    captured_at=self.now(),
                    reference=reference,
                )
            )
        if not grouped:
            grouped["fallback-evidence"] = []
        probes = tuple(
            ProbeResult(
                probe_id=probe_id,
                health=(
                    InstrumentHealth.HEALTHY
                    if evidence
                    else InstrumentHealth.COULD_NOT_CHECK
                ),
                detail=(
                    "Evidence supplied through the guided/export-assisted path."
                    if evidence
                    else "No person-supplied evidence was provided."
                ),
                evidence=tuple(evidence),
            )
            for probe_id, evidence in sorted(grouped.items())
        )
        return AdapterResultEnvelope(
            adapter_id=self.permission.adapter_id,
            contract_version=self.permission.adapter_version,
            collected_at=self.now(),
            probes=probes,
        )

    def continue_fallback(self) -> AdapterResultEnvelope:
        """Enter the editable Job Map using only supplied fallback material."""

        self._require(ConciergeStage.FALLBACK)
        self.envelope = self._fallback_envelope()
        self.proposals = ()
        self.stage = ConciergeStage.JOB_MAP
        return self.envelope

    # Friendly integration aliases: transport layers can use either explicit
    # ``continue_fallback`` or the stage-oriented name.
    enter_fallback_job_map = continue_fallback

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

    @property
    def catalogue_fetch_available(self) -> bool:
        """Show the public-catalogue doorway after confirmed jobs or the Capability Map."""

        return self.stage in {
            ConciergeStage.JOB_MAP,
            ConciergeStage.CAPABILITY_MAP,
        } and bool(self._confirmed)

    def record_catalogue_fetch(self, result: CatalogueFetchResult) -> CatalogueFetchResult:
        """Record local bridge fetch state without advancing to shelf/brief UI."""

        self._require(
            ConciergeStage.JOB_MAP,
            ConciergeStage.CAPABILITY_MAP,
            ConciergeStage.CATALOGUE_SHELF,
            ConciergeStage.CATALOGUE_BRIEF,
        )
        self.catalogue_fetch_result = result
        return result

    def _display_catalogue(self) -> CatalogueV2:
        result = self.catalogue_fetch_result
        if result is None:
            raise JourneyStateError("fetch or load a verified Dex catalogue first")
        catalogue = result.display_catalogue
        if catalogue is None:
            raise JourneyStateError("no verified or stale catalogue is available to display")
        return catalogue

    def open_catalogue_shelf(
        self,
        *,
        host_adapter: str | None = None,
        lens_contract_version: str | None = None,
    ) -> tuple[RankedCapabilityMatch, ...]:
        """Enter the read-only full shelf after the Capability Map."""

        self._require(ConciergeStage.CAPABILITY_MAP)
        if self.capability_map is None:
            raise JourneyStateError("capability shelf requires the Capability Map")
        catalogue = self._display_catalogue()
        self.catalogue_shelf = rank_capability_shelf(
            catalogue,
            self.capability_map,
            host_adapter=host_adapter or self.permission.catalogue_host,
            lens_contract_version=lens_contract_version or self.permission.adapter_version,
        )
        self.catalogue_brief_markdown = ""
        self.selected_catalogue_capability_id = ""
        self.selected_catalogue_job_id = ""
        self.stage = ConciergeStage.CATALOGUE_SHELF
        return self.catalogue_shelf

    def select_catalogue_brief(
        self,
        form: dict[str, list[str]] | None = None,
        *,
        capability_id: str | None = None,
        job_id: str | None = None,
    ) -> str:
        """Render one portable brief for the person's own AI system."""

        self._require(ConciergeStage.CATALOGUE_SHELF)
        submitted = form or {}
        selected_capability_id = (
            capability_id
            if capability_id is not None
            else next(iter(submitted.get("capability_id", ())), "")
        ).strip()
        selected_job_id = (
            job_id
            if job_id is not None
            else next(iter(submitted.get("job_id", ())), "")
        ).strip()
        if not selected_capability_id:
            raise ValueError("capability id is required")
        if not selected_job_id:
            raise ValueError("job id is required")
        if self.capability_map is None:
            raise JourneyStateError("portable brief requires the Capability Map")
        catalogue = self._display_catalogue()
        brief = render_portable_brief_markdown(
            catalogue,
            self.capability_map,
            self.catalogue_shelf,
            selected_capability_id=selected_capability_id,
            selected_job_id=selected_job_id,
        )
        self.selected_catalogue_capability_id = selected_capability_id
        self.selected_catalogue_job_id = selected_job_id
        self.catalogue_brief_markdown = brief
        self.stage = ConciergeStage.CATALOGUE_BRIEF
        return brief

    def return_to_catalogue_shelf(self) -> None:
        self._require(ConciergeStage.CATALOGUE_BRIEF)
        self.stage = ConciergeStage.CATALOGUE_SHELF

    # ------------------------------------------------------------------
    # M4 adaptation stages (7-8)
    # ------------------------------------------------------------------

    @property
    def adaptation_available(self) -> bool:
        """Whether the host explicitly declares the one supported write operation."""

        from capability_exchange.adaptation.contract import OperationKind

        contract = self._adapter_contract
        return bool(
            contract is not None
            and contract.mode is AdapterMode.ADAPT_CAPABLE
            and contract.mutation_contract is not None
            and OperationKind.CREATE_NAMESPACED_SKILL
            in contract.mutation_contract.operations
        )

    @property
    def adaptation_selection(self) -> AdaptationSelection | None:
        """The one bounded choice currently being prepared, if any."""

        return self._adaptation_selection

    @property
    def adaptation_preview(self) -> object | None:
        """The immutable exact-byte preview shown to the person."""

        return self._adaptation_preview

    @property
    def adaptation_recovery(self) -> object | None:
        """The validated undo proof created and shown before approval."""

        return self._adaptation_recovery

    @property
    def adaptation_approval(self) -> object | None:
        """The single-use approval record (the bearer token is not persisted)."""

        return self._adaptation_approval

    @property
    def adaptation_result(self) -> object | None:
        """The transaction result containing the local receipt path."""

        return self._adaptation_result

    @property
    def adaptation_verification(self) -> object | None:
        """The Success-Contract-scoped verification result."""

        return self._adaptation_verification

    @property
    def adaptation_undo_result(self) -> object | None:
        """The bounded undo result after a successful stage-8 reversal."""

        return self._adaptation_undo_result

    @property
    def adaptation_refusal(self) -> str:
        return self._adaptation_refusal

    @property
    def hard_stop_reason(self) -> str:
        return self._hard_stop_reason

    @property
    def adaptation_hard_stopped(self) -> bool:
        return self.stage is ConciergeStage.ADAPTATION_HARD_STOP

    @property
    def hard_stopped(self) -> bool:
        """Short integration alias for the session's adaptation stop state."""

        return self.adaptation_hard_stopped

    @property
    def adaptation_incidents(self) -> tuple[object, ...]:
        engine = self._adaptation_engine
        if engine is None:
            return ()
        return tuple(getattr(engine, "incidents", ()))

    @property
    def adaptation_receipt(self) -> object | None:
        """Read the standard local receipt without re-running the transaction."""

        result = self._adaptation_result
        if result is None:
            return None
        path = getattr(result, "receipt_path", None)
        if path is None:
            return None
        from capability_exchange.adaptation.receipt import read_receipt

        try:
            return read_receipt(Path(path))
        except (OSError, ValueError) as exc:
            self._hard_stop("Unverified: the local adaptation receipt is unreadable")
            raise JourneyStateError(
                "receipt is unreadable; adaptation is hard-stopped"
            ) from exc

    def _require_adaptation_running(self, *allowed: ConciergeStage) -> None:
        if self.stage is ConciergeStage.ADAPTATION_HARD_STOP:
            raise JourneyStateError(
                "adaptation is hard-stopped; no further automated changes are allowed"
            )
        self._require(*allowed)

    def _hard_stop(self, reason: str) -> None:
        """Stop automation and retain only a bounded, honest explanation."""

        self._hard_stop_reason = " ".join(str(reason).split())[:512]
        self.stage = ConciergeStage.ADAPTATION_HARD_STOP

    def _refuse(self, reason: str) -> None:
        self._adaptation_refusal = " ".join(str(reason).split())[:512]
        self.stage = ConciergeStage.ADAPTATION_REFUSED

    def _adaptation_engine_for(self, preview: object) -> object:
        """Lazily create the host-neutral engine after a preview exists."""

        if self._adaptation_engine is not None:
            return self._adaptation_engine
        from capability_exchange.adaptation.approval import ApprovalAuthority
        from capability_exchange.adaptation.transaction import TransactionEngine

        authority = ApprovalAuthority()
        self._adaptation_authority = authority
        self._adaptation_engine = TransactionEngine(
            state_root=self.adaptation_state_root,
            receipt_root=self.adaptation_receipt_root,
            approval_authority=authority,
            adapter_id=self.permission.adapter_id,
            adapter_version=self.permission.adapter_version,
        )
        return self._adaptation_engine

    def select_adaptation(
        self,
        job_id: str,
        capability_id: str,
        approved_skills_root: Path,
        markdown: str,
        expected_benefit: str,
        observable_signal: str,
    ) -> AdaptationSelection:
        """Select one capability for a bounded, preview-first adaptation.

        The selection transition performs the independent G6 job and proposal
        checks.  It never creates a preview or writes a host file.  A second
        selection is impossible until this transaction has been undone or the
        session is restarted.
        """

        self._require_adaptation_running(ConciergeStage.CAPABILITY_MAP)
        if not self.adaptation_available:
            reason = "Diagnose-only adapter has no approved host mutation contract"
            self._refuse(reason)
            raise AdaptationRefusedError(reason)
        if self._adaptation_selection is not None:
            raise JourneyStateError("one adaptation must finish before another can be selected")
        try:
            validate_job_id(job_id)
        except ValueError as exc:
            self._refuse(str(exc))
            raise AdaptationRefusedError(str(exc)) from exc
        contract = self._confirmed.get(job_id)
        if contract is None:
            raise JourneyStateError("select an adaptation only for a confirmed Success Contract")

        try:
            selection = AdaptationSelection(
                job_id=job_id,
                capability_id=capability_id,
                approved_skills_root=Path(approved_skills_root),
                markdown=markdown,
                expected_benefit=expected_benefit,
                observable_signal=observable_signal,
            )
        except (OSError, TypeError, ValueError) as exc:
            self._refuse(f"selection refused: {exc}")
            raise AdaptationRefusedError(self._adaptation_refusal) from exc
        root = selection.approved_skills_root.resolve(strict=False)
        approved = tuple(
            Path(value).expanduser().resolve(strict=False)
            for value in self.permission.approved_roots
        )
        if not any(
            root == candidate or root.is_relative_to(candidate)
            for candidate in approved
        ):
            reason = "adaptation target is outside the explicitly approved user root"
            self._refuse(reason)
            raise AdaptationRefusedError(reason)

        from capability_exchange.adaptation.allowlist import OperationKind
        from capability_exchange.adaptation.eligibility import adaptation_eligibility

        job_description = " ".join(
            (
                contract.situation,
                contract.desired_outcome,
            )
        )
        proposal_description = " ".join(
            (selection.capability_id, selection.expected_benefit, selection.markdown)
        )
        decision = adaptation_eligibility(
            job_description=job_description,
            # Classify the job's positive Situation/Desired-outcome text.  Do
            # not feed boundary prose such as "never send" into the classifier:
            # a safety limit is not evidence that the job itself sends a
            # message, and the taxonomy must still catch an actual send job in
            # the job description above.
            contract_fields={
                "situation": contract.situation,
                "desired_outcome": contract.desired_outcome,
            },
            proposal_description=proposal_description,
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
        )
        if not decision.allowed:
            self._refuse(f"{decision.reason.value}: {decision.explanation}")
            raise AdaptationRefusedError(self._adaptation_refusal)
        from capability_exchange.adaptation.verification import has_outcome_procedure

        if not has_outcome_procedure(
            OperationKind.CREATE_NAMESPACED_SKILL, selection.observable_signal
        ):
            reason = "no core-owned outcome procedure supports the selected success signal"
            self._refuse(reason)
            raise AdaptationRefusedError(reason)
        self._adaptation_selection = selection
        self._adaptation_contract = contract
        self.stage = ConciergeStage.ADAPTATION_SELECT
        return selection

    def preview_adaptation(self) -> object:
        """Build the exact immutable preview; no mutation is attempted."""

        self._require_adaptation_running(ConciergeStage.ADAPTATION_SELECT)
        selection = self._adaptation_selection
        if selection is None:
            raise JourneyStateError("select an adaptation before previewing it")
        from capability_exchange.adaptation.hosts.claude_code import (
            build_claude_code_skill_preview,
        )
        from capability_exchange.adaptation.recovery import RecoveryUnavailableError

        try:
            preview = build_claude_code_skill_preview(
                approved_skills_root=selection.approved_skills_root,
                job_id=selection.job_id,
                capability_id=selection.capability_id,
                markdown=selection.markdown,
                expected_benefit=selection.expected_benefit,
                created_at=self.now(),
            )
            engine = self._adaptation_engine_for(preview)
            recovery = engine.prepare_recovery(preview, now=self.now())
        except (OSError, RecoveryUnavailableError, RuntimeError, ValueError) as exc:
            self._refuse(f"preview refused: {exc}")
            raise AdaptationRefusedError(self._adaptation_refusal) from exc
        self._adaptation_preview = preview
        self._adaptation_recovery = recovery
        self.stage = ConciergeStage.ADAPTATION_PREVIEW
        return preview

    def approve_adaptation(self, *, ttl: timedelta = timedelta(minutes=5)) -> object:
        """Issue a fresh, single-use approval bound to the exact preview."""

        self._require_adaptation_running(ConciergeStage.ADAPTATION_PREVIEW)
        preview = self._adaptation_preview
        if preview is None:
            raise JourneyStateError("preview the exact adaptation before approving it")
        if self._adaptation_recovery is None:
            raise JourneyStateError("a validated recovery proof is required before approval")
        from capability_exchange.adaptation.approval import ApprovalAuthority

        authority = self._adaptation_authority
        if not isinstance(authority, ApprovalAuthority):
            self._adaptation_engine_for(preview)
            authority = self._adaptation_authority
        assert isinstance(authority, ApprovalAuthority)
        issued = authority.issue(preview, now=self.now(), ttl=ttl)
        self._adaptation_approval = issued
        self.stage = ConciergeStage.ADAPTATION_APPROVAL
        return issued

    def apply_adaptation(self, approval_token: str | None = None) -> object:
        """Apply exactly the approved preview through the transaction engine."""

        self._require_adaptation_running(ConciergeStage.ADAPTATION_APPROVAL)
        preview = self._adaptation_preview
        selection = self._adaptation_selection
        contract = self._adaptation_contract
        issued = self._adaptation_approval
        recovery = self._adaptation_recovery
        if (
            preview is None
            or selection is None
            or contract is None
            or issued is None
            or recovery is None
        ):
            raise JourneyStateError("select, preview, and approve one adaptation before apply")
        token = approval_token or getattr(issued, "token", "")
        if not token:
            raise JourneyStateError("a fresh single-use approval token is required")
        engine = self._adaptation_engine_for(preview)
        self.stage = ConciergeStage.ADAPTATION_APPLY
        try:
            result = engine.execute(
                preview,
                approval_token=token,
                contract=contract,
                observable_signal=selection.observable_signal,
                now=self.now(),
                recovery_point=recovery,
            )
        except Exception as exc:
            from capability_exchange.adaptation.transaction import (
                AutomationHardStoppedError,
                RecoveryFailedError,
                TransactionConflictError,
            )

            if isinstance(
                exc,
                (AutomationHardStoppedError, RecoveryFailedError, TransactionConflictError),
            ):
                self._hard_stop(
                    "Recovery failed: adaptation could not prove a safe transaction state"
                    if isinstance(exc, RecoveryFailedError)
                    else f"Unverified: adaptation automation stopped ({exc})"
                )
            else:
                self._refuse(f"adaptation was not applied: {exc}")
            raise
        self._adaptation_result = result
        if getattr(result, "hard_stopped", False):
            self._hard_stop("Unverified: outcome verification was Unknown; automation stopped")
        else:
            self.stage = ConciergeStage.ADAPTATION_RECEIPT
        return result

    def verify_adaptation(self) -> object:
        """Publish the already-recorded verification as stage 7's final proof."""

        self._require_adaptation_running(ConciergeStage.ADAPTATION_RECEIPT)
        result = self._adaptation_result
        if result is None:
            raise JourneyStateError("apply the approved adaptation before verification")
        verification = getattr(result, "verification", None)
        if verification is None:
            receipt = self.adaptation_receipt
            verification = getattr(receipt, "verification_verdict", None)
        self._adaptation_verification = verification
        if verification is None or getattr(
            verification, "value", verification
        ) in {"unknown", "unverified"}:
            self._hard_stop("Unverified: outcome verification was unavailable")
            raise JourneyStateError("verification is Unverified; adaptation is hard-stopped")
        self.stage = ConciergeStage.ADAPTATION_VERIFY
        return verification

    def undo_adaptation(self) -> object:
        """Restore the exact pre-change state, or trigger the hard stop."""

        self._require_adaptation_running(
            ConciergeStage.ADAPTATION_VERIFY,
            ConciergeStage.ADAPTATION_RECEIPT,
        )
        preview = self._adaptation_preview
        if preview is None:
            raise JourneyStateError("no adaptation preview is available to undo")
        engine = self._adaptation_engine
        if engine is None:
            raise JourneyStateError("adaptation transaction engine is unavailable")
        try:
            result = engine.undo(preview)
        except Exception as exc:
            from capability_exchange.adaptation.transaction import (
                AutomationHardStoppedError,
                RecoveryFailedError,
                UndoConflictError,
            )

            if isinstance(
                exc,
                (RecoveryFailedError, UndoConflictError, AutomationHardStoppedError),
            ):
                self._hard_stop(
                    "Recovery failed: undo could not prove a byte-identical restoration"
                )
            raise
        self._adaptation_undo_result = result
        self.stage = ConciergeStage.ADAPTATION_UNDO
        return result

    # Short stage-oriented aliases keep the domain surface readable for
    # integrations while the explicit names above remain the canonical API.
    select_change = select_adaptation
    preview_change = preview_adaptation
    approve_change = approve_adaptation
    apply_change = apply_adaptation
    verify_change = verify_adaptation
    undo_change = undo_adaptation

    def read_adaptation_receipt(self) -> object | None:
        return self.adaptation_receipt

    # ------------------------------------------------------------------
    # M5 optional contribution stage (9)
    # ------------------------------------------------------------------

    def choose_contribution(self, candidate_digest: str | None = None) -> None:
        """Enter stage 9 only after a separate, explicit contribution choice."""

        self._require(
            ConciergeStage.CAPABILITY_MAP,
            ConciergeStage.ADAPTATION_VERIFY,
            ConciergeStage.ADAPTATION_UNDO,
        )
        if self._contribution_identity is None or self._contribution_intake is None:
            raise JourneyStateError("contribution intake and identity ports are unavailable")
        candidates = self.available_contribution_candidates
        if not candidates:
            raise JourneyStateError("this contribution candidate was previously declined")
        if candidate_digest is None and len(candidates) > 1:
            raise JourneyStateError("choose one reusable contribution candidate explicitly")
        if candidate_digest is None:
            candidate = candidates[0]
        else:
            candidate = next(
                (
                    item
                    for item in candidates
                    if item.candidate_digest == candidate_digest
                ),
                None,
            )
            if candidate is None:
                raise JourneyStateError("contribution candidate is unavailable or declined")
        self._contribution_return_stage = self.stage
        self._contribution_candidate = candidate
        self._contribution_privacy_preview = None
        self.stage = ConciergeStage.CONTRIBUTION_PRIVACY

    def preview_contribution(self, card: CapabilityCard) -> ContributionPrivacyPreview:
        """Classify locally and retain only the display-safe abstraction."""

        self._require(ConciergeStage.CONTRIBUTION_PRIVACY)
        candidate = self._contribution_candidate
        if candidate is None:
            raise JourneyStateError("choose a contribution candidate before privacy review")
        preview = self._contribution_privacy_gate.preview(candidate, card)
        self._contribution_privacy_preview = preview
        self.stage = ConciergeStage.CONTRIBUTION_PRIVACY_CONFIRM
        return preview

    def confirm_contribution_privacy(self, statement: str) -> CapabilityCard:
        """Build only after the exact sentence shown with this preview."""

        self._require(ConciergeStage.CONTRIBUTION_PRIVACY_CONFIRM)
        preview = self._contribution_privacy_preview
        if preview is None:
            raise JourneyStateError("a local privacy preview is required before build")
        if statement != preview.confirmation_statement:
            label = (
                "exact looks-personal confirmation"
                if preview.looks_personal
                else "exact abstraction confirmation"
            )
            raise JourneyStateError(f"{label} is required before contribution build")
        card = self._contribution_privacy_gate.require_minimized(preview.abstract_card)
        self._contribution_card = card
        self._contribution_comparison = self._pending_contribution_comparison
        self._pending_contribution_comparison = None
        self.stage = ConciergeStage.CONTRIBUTION_REVIEW
        return card

    def decline_contribution_candidate(self) -> None:
        """Permanently suppress this safe candidate digest, then leave stage 9."""

        self._require(
            ConciergeStage.CONTRIBUTION_PRIVACY,
            ConciergeStage.CONTRIBUTION_PRIVACY_CONFIRM,
        )
        candidate = self._contribution_candidate
        if candidate is None:
            raise JourneyStateError("there is no contribution candidate to decline")
        self._contribution_decline_store.decline(candidate)
        self._contribution_candidate = None
        self._contribution_privacy_preview = None
        self._pending_contribution_comparison = None
        self._contribution_card = None
        self.stage = self._contribution_return_stage

    def build_contribution(self, card: CapabilityCard) -> CapabilityCard:
        """Legacy direct build is unreachable without the S2 privacy step."""

        del card
        raise JourneyStateError(
            "preview and explicitly confirm the contribution abstraction before build"
        )

    def edit_contribution(self, edited: CapabilityCard) -> ContributionVersionComparison:
        """Replace a local draft with exactly one explicit, reviewable new version."""

        self._require(
            ConciergeStage.CONTRIBUTION_REVIEW,
            ConciergeStage.CONTRIBUTION_DISCLOSE,
            ConciergeStage.CONTRIBUTION_APPROVE,
            ConciergeStage.CONTRIBUTION_SUBMIT,
        )
        previous = self._contribution_card
        if previous is None:
            raise JourneyStateError("build a valid Capability Card before editing it")
        edited = CapabilityCard.model_validate(edited.model_dump(mode="python"))
        if edited.card_id != previous.card_id:
            raise JourneyStateError("an edited Card must retain the same card_id")
        if edited.version != previous.version + 1:
            raise JourneyStateError("an edited Card must increment version by exactly one")
        previous_fields = previous.model_dump(mode="json")
        revised_fields = edited.model_dump(mode="json")
        requested_changes = tuple(
            field
            for field in previous.__class__.model_fields
            if previous_fields[field] != revised_fields[field]
        )
        if not any(field != "version" for field in requested_changes):
            raise JourneyStateError(
                "an edited Card version must change at least one content field"
            )
        if self._intake_submission_attempted:
            raise JourneyStateError("an already submitted contribution must be withdrawn")
        candidate = self._contribution_candidate
        if candidate is None:
            raise JourneyStateError("the contribution candidate binding is unavailable")
        preview = self._contribution_privacy_gate.preview(
            candidate,
            edited,
            stable_card_id=previous.card_id,
        )
        revised = preview.abstract_card
        previous_bytes = canonical_card_bytes(previous)
        revised_bytes = canonical_card_bytes(revised)
        revised_safe_fields = revised.model_dump(mode="json")
        changed = tuple(
            field
            for field in previous.__class__.model_fields
            if previous_fields[field] != revised_safe_fields[field]
        )
        comparison = ContributionVersionComparison(
            previous_version_hash=previous.version_hash,
            revised_version_hash=revised.version_hash,
            changed_fields=changed,
            previous_exact_json=previous_bytes.decode("utf-8"),
            revised_exact_json=revised_bytes.decode("utf-8"),
        )
        if self._contribution_consent is not None and self._contribution_manifest is not None:
            self._contribution_consent.withdraw(previous, self._contribution_manifest)
        self._contribution_privacy_preview = preview
        self._pending_contribution_comparison = comparison
        self._contribution_manifest = None
        self._contribution_consent = None
        self._contribution_lifecycle = None
        self._contribution = None
        self._contribution_handle = None
        self._pending_withdrawal_version_hash = None
        self._intake_submission_attempted = False
        self._pending_withdrawal = False
        self.stage = ConciergeStage.CONTRIBUTION_PRIVACY_CONFIRM
        return comparison

    def review_contribution(self) -> CapabilityCard:
        """Revalidate the immutable version before field disclosure is possible."""

        self._require(ConciergeStage.CONTRIBUTION_REVIEW)
        card = self._contribution_card
        if card is None:
            raise JourneyStateError("build a valid Capability Card before review")
        require_valid_card(card)
        self.stage = ConciergeStage.CONTRIBUTION_DISCLOSE
        return card

    def disclose_contribution(
        self,
        approved_fields: Iterable[str],
    ) -> DisclosureManifest:
        """Construct the only exact-byte payload eligible for later egress."""

        self._require(ConciergeStage.CONTRIBUTION_DISCLOSE)
        card = self._contribution_card
        if card is None:
            raise JourneyStateError("review a valid Capability Card before disclosure")
        self._contribution_privacy_gate.require_minimized(card)
        manifest = build_disclosure_manifest(card, approved_fields=tuple(approved_fields))
        self._contribution_manifest = manifest
        self.stage = ConciergeStage.CONTRIBUTION_APPROVE
        return manifest

    def approve_contribution(self, permissions: PermissionSet) -> Contribution:
        """Record exact version consent, then derive pseudonymous provenance.

        Identity is deliberately invoked here rather than during diagnosis,
        adaptation, contribution choice, building, review, or disclosure.
        """

        self._require(ConciergeStage.CONTRIBUTION_APPROVE)
        card = self._contribution_card
        manifest = self._contribution_manifest
        identity = self._contribution_identity
        if card is None or manifest is None or identity is None:
            raise JourneyStateError("a reviewed exact disclosure is required before approval")
        if permissions.is_unresolvable:
            raise ContributionEgressError(
                "unresolvable permission state is fully withdrawn and cannot be approved"
            )

        try:
            secret = identity.contributor_secret()
        except Exception as exc:
            raise ContributionEgressError(
                "contributor authority unavailable; link this terminal before approval"
            ) from exc
        if type(secret) is not bytes or not secret or len(secret) > 4096:
            raise ContributionEgressError(
                "identity port did not provide bounded local contributor authority"
            )
        ledger = ConsentLedger()
        consent_record = ledger.grant(card, manifest, permissions)
        lifecycle = ContributionLifecycle(
            stores=list(self._contribution_stores),
            consent=ledger,
        )
        contribution = lifecycle.draft(
            card,
            manifest,
            contributor_secret=secret,
        )
        self._contribution_consent = ledger
        self._contribution_lifecycle = lifecycle
        self._contribution = contribution
        token_digest = hmac.new(
            secret,
            b"contribution-withdrawal\0" + manifest.byte_hash.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        consent_bytes = json.dumps(
            consent_record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        consent_hash = "sha256:" + hashlib.sha256(consent_bytes).hexdigest()
        idempotency_material = (
            b"capability-submission-v1\0"
            + manifest.byte_hash.encode("ascii")
            + b"\0"
            + consent_hash.encode("ascii")
        )
        self._contribution_handle = ContributionHandle(
            manifest_byte_hash=manifest.byte_hash,
            revocation_token="revocation-v1:" + token_digest,
            consent_hash=consent_hash,
            idempotency_key="sha256:" + hashlib.sha256(idempotency_material).hexdigest(),
            permissions=consent_record.permissions,
        )
        self._intake_submission_attempted = False
        self._pending_withdrawal = False
        self.stage = ConciergeStage.CONTRIBUTION_SUBMIT
        return contribution

    @staticmethod
    def _receipt_matches(
        receipt: object,
        handle: ContributionHandle,
        *,
        confirmation_field: str,
    ) -> bool:
        """Require an exact, handle-bound positive receipt; truthy values fail."""

        return (
            getattr(receipt, "manifest_byte_hash", None) == handle.manifest_byte_hash
            and getattr(receipt, "handle_binding", None) == handle.receipt_binding
            and getattr(receipt, confirmation_field, None) is True
            and type(getattr(receipt, confirmation_field, None)) is bool
        )

    def submit_contribution(self) -> Contribution:
        """Submit locally, then send one ledger-authorized positional byte value."""

        self._require(ConciergeStage.CONTRIBUTION_SUBMIT)
        card = self._contribution_card
        manifest = self._contribution_manifest
        contribution = self._contribution
        ledger = self._contribution_consent
        lifecycle = self._contribution_lifecycle
        intake = self._contribution_intake
        handle = self._contribution_handle
        if any(
            value is None
            for value in (card, manifest, contribution, ledger, lifecycle, intake, handle)
        ):
            raise ContributionEgressError("contribution approval state is incomplete")
        assert isinstance(card, CapabilityCard)
        assert isinstance(manifest, DisclosureManifest)
        assert isinstance(contribution, Contribution)
        assert isinstance(ledger, ConsentLedger)
        assert isinstance(lifecycle, ContributionLifecycle)
        assert isinstance(handle, ContributionHandle)
        assert intake is not None
        if contribution.card.version_hash != card.version_hash or contribution.manifest != manifest:
            raise ContributionEgressError(
                "exact approved Card version and disclosure consent no longer match"
            )

        try:
            outbound = ledger.authorize_outbound(card, manifest)
        except Exception as exc:
            raise ContributionEgressError(
                "exact approved Card version and disclosure consent no longer match"
            ) from exc
        if type(outbound) is not bytes:
            raise ContributionEgressError("consent authority did not return exact bytes")

        submitted = lifecycle.submit(contribution)
        if submitted.state is not ContributionState.SUBMITTED:
            self.stage = ConciergeStage.CONTRIBUTION_WITHDRAW
            raise ContributionEgressError("contribution was withdrawn before intake submission")
        self._intake_submission_attempted = True
        try:
            receipt = intake.submit(outbound, handle=handle)
        except Exception as exc:
            lifecycle.quarantine(contribution, "intake did not confirm exact-byte submission")
            self.stage = ConciergeStage.CONTRIBUTION_WITHDRAW
            self._pending_withdrawal = True
            raise ContributionEgressError(
                "intake did not confirm exact-byte submission; the Card is quarantined"
            ) from exc
        if not self._receipt_matches(receipt, handle, confirmation_field="accepted"):
            lifecycle.quarantine(contribution, "intake returned an invalid submission receipt")
            self.stage = ConciergeStage.CONTRIBUTION_WITHDRAW
            self._pending_withdrawal = True
            raise ContributionEgressError(
                "intake submission receipt was not exact and affirmative; the Card is quarantined"
            )
        self._pending_withdrawal = True
        self.stage = ConciergeStage.CONTRIBUTION_WITHDRAW
        return submitted

    def withdraw_contribution(self, *, reason: str) -> Contribution:
        """Revoke local consent immediately, then synchronously notify intake."""

        self._require(ConciergeStage.CONTRIBUTION_WITHDRAW)
        contribution = self._contribution
        lifecycle = self._contribution_lifecycle
        intake = self._contribution_intake
        handle = self._contribution_handle
        if contribution is None or lifecycle is None or intake is None or handle is None:
            raise JourneyStateError("there is no approved contribution to withdraw")
        if contribution.state is not ContributionState.WITHDRAWN:
            lifecycle.withdraw(contribution, reason=reason)
        self._pending_withdrawal_version_hash = contribution.version_hash
        local_pending = lifecycle.has_pending_withdrawal(contribution.version_hash)
        if not self._intake_submission_attempted:
            self._pending_withdrawal = local_pending
            return contribution
        try:
            receipt = intake.withdraw(handle)
        except Exception as exc:
            self._pending_withdrawal = True
            raise ContributionEgressError(
                "local withdrawal is immediate, but intake withdrawal was not confirmed"
            ) from exc
        if not self._receipt_matches(receipt, handle, confirmation_field="withdrawn"):
            self._pending_withdrawal = True
            raise ContributionEgressError(
                "local withdrawal is immediate, but intake withdrawal was not confirmed"
            )
        self._pending_withdrawal = local_pending
        self._intake_submission_attempted = False
        if not local_pending:
            self._contribution_handle = None
            self._pending_withdrawal_version_hash = None
        else:
            raise ContributionEgressError(
                "intake withdrawal is confirmed, but a controlled-store withdrawal is still pending"
            )
        return contribution

    def retry_pending_withdrawal(self) -> WithdrawalReceipt:
        """Retry a close/expiry withdrawal using only preserved opaque authority."""

        if not self._pending_withdrawal:
            raise JourneyStateError("there is no pending intake withdrawal")
        handle = self._contribution_handle
        version_hash = self._pending_withdrawal_version_hash
        lifecycle = self._contribution_lifecycle
        if lifecycle is not None and version_hash is not None:
            lifecycle.retry_pending_withdrawals(version_hash)
        local_pending = bool(
            lifecycle is not None
            and version_hash is not None
            and lifecycle.has_pending_withdrawal(version_hash)
        )
        if self._intake_submission_attempted:
            intake = self._contribution_intake
            if intake is None or handle is None:
                raise JourneyStateError("pending withdrawal authority is unavailable")
            try:
                receipt = intake.withdraw(handle)
            except Exception as exc:
                raise ContributionEgressError("intake withdrawal retry was not confirmed") from exc
            if not self._receipt_matches(receipt, handle, confirmation_field="withdrawn"):
                raise ContributionEgressError("intake withdrawal retry was not confirmed")
            self._intake_submission_attempted = False
        if local_pending:
            raise ContributionEgressError("controlled-store withdrawal retry was not confirmed")
        if handle is None:
            raise JourneyStateError("pending withdrawal receipt binding is unavailable")
        self._pending_withdrawal = False
        self._contribution_handle = None
        self._contribution_intake = None
        self._contribution_lifecycle = None
        self._pending_withdrawal_version_hash = None
        return WithdrawalReceipt(
            manifest_byte_hash=handle.manifest_byte_hash,
            handle_binding=handle.receipt_binding,
            withdrawn=True,
        )

    def close(self) -> None:
        """Close and clean up local state, regardless of the current stage."""

        if self.stage is ConciergeStage.CLOSED:
            return
        # Revoke local consent at every exit.  If intake was attempted, also
        # request authenticated withdrawal before clearing contribution state.
        # A hosted review queue is the deliberate exception: once its exact
        # affirmative receipt has been checked, closing this short-lived local
        # browser session must not silently undo the person's contribution.
        # Its durable local receipt remains the later withdrawal authority.
        contribution = self._contribution
        lifecycle = self._contribution_lifecycle
        if contribution is not None and lifecycle is not None:
            intake = self._contribution_intake
            handle = self._contribution_handle
            durable_acceptance = False
            if (
                contribution.state is ContributionState.SUBMITTED
                and self._intake_submission_attempted
                and handle is not None
                and isinstance(intake, DurableContributionIntakePort)
            ):
                try:
                    durable_acceptance = (
                        intake.has_durable_withdrawal_authority(handle) is True
                    )
                except Exception:  # noqa: BLE001 - close fails safe to withdrawal
                    durable_acceptance = False
            if durable_acceptance:
                self._pending_withdrawal = False
                self._pending_withdrawal_version_hash = None
            else:
                self._pending_withdrawal_version_hash = contribution.version_hash
                if contribution.state is not ContributionState.WITHDRAWN:
                    try:
                        lifecycle.withdraw(contribution, reason="session closed or expired")
                    except Exception:  # noqa: BLE001 - close still preserves intake recovery
                        self._pending_withdrawal = self._intake_submission_attempted
                if self._intake_submission_attempted:
                    if intake is None or handle is None:
                        self._pending_withdrawal = True
                    else:
                        try:
                            receipt = intake.withdraw(handle)
                        except Exception:  # noqa: BLE001 - opaque authority remains retryable
                            self._pending_withdrawal = True
                        else:
                            confirmed = self._receipt_matches(
                                receipt, handle, confirmation_field="withdrawn"
                            )
                            self._pending_withdrawal = not confirmed
                            if confirmed:
                                self._intake_submission_attempted = False
                self._pending_withdrawal = (
                    self._pending_withdrawal
                    or lifecycle.has_pending_withdrawal(contribution.version_hash)
                )

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
            self._adaptation_selection = None
            self._adaptation_preview = None
            self._adaptation_recovery = None
            self._adaptation_approval = None
            self._adaptation_result = None
            self._adaptation_verification = None
            self._adaptation_undo_result = None
            self._adaptation_authority = None
            self._adaptation_engine = None
            self._adaptation_contract = None
            self._contribution_identity = None
            if not self._pending_withdrawal:
                self._contribution_intake = None
            self._contribution_stores = ()
            self._contribution_consent = None
            if not self._pending_withdrawal:
                self._contribution_lifecycle = None
            self._contribution_card = None
            self._contribution_candidate = None
            self._contribution_privacy_preview = None
            self._pending_contribution_comparison = None
            self._contribution_manifest = None
            self._contribution = None
            if not self._pending_withdrawal:
                self._contribution_handle = None
                self._pending_withdrawal_version_hash = None
            self.stage = ConciergeStage.CLOSED

    def decline(self) -> None:
        """Alias used by the permission screen's leave action."""

        self.close()

    def cancel(self) -> None:
        """Alias used by an in-flight collection cancellation control."""

        self.close()
