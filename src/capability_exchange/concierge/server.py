"""Loopback-only local browser concierge (stages 1-9).

The server is intentionally small and stdlib-only. It has no static asset
pipeline, no analytics, and no third-party resources; every page is rendered
from local state and every transition is a plain HTTP request guarded by a
single-use bootstrap token, a session cookie, Origin checking, and CSRF.
"""

from __future__ import annotations

import hashlib
import html
import secrets
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from capability_exchange.adaptation.approval import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalReplayError,
)
from capability_exchange.adaptation.transaction import (
    AutomationHardStoppedError,
    RecoveryFailedError,
    TransactionConflictError,
    TransactionFailedError,
    UndoConflictError,
)
from capability_exchange.adapter import AdapterContract, AdapterResultEnvelope
from capability_exchange.adapters.claude_code.containment import contained_inspection
from capability_exchange.adapters.claude_code.contract import (
    CLAUDE_CODE_CATALOGUE_HOST_ADAPTER,
    claude_code_contract,
)
from capability_exchange.boundary.deletion import DeletionError
from capability_exchange.cards import CapabilityCard
from capability_exchange.catalogue.fetch import (
    CONSENT_STATEMENT,
    DEFAULT_CATALOGUE_URL,
    CatalogueFetchConsent,
    CatalogueFetchResult,
    CatalogueFetchStatus,
    ConsentedCatalogueFetcher,
)
from capability_exchange.catalogue.subscription import (
    CatalogueSubscriptionStore,
    default_lens_app_storage,
    require_app_storage_outside_roots,
)
from capability_exchange.catalogue.v2 import KeyRing, VerifiedCatalogueStore
from capability_exchange.concierge.collection import (
    CollectionCancelled,
    CollectionController,
    CollectionResult,
    ScopeSnapshot,
)
from capability_exchange.concierge.journey import (
    CollectionFallback,
    ConciergeJourney,
    ConciergeStage,
    ContractFields,
    ContributionIdentityPort,
    ContributionIntakePort,
    FallbackEvidence,
    FallbackMode,
    JobDraftFields,
    JourneyError,
    PermissionMetadata,
)
from capability_exchange.concierge.security import (
    ConciergeSessionState,
    SessionSecurity,
    ensure_loopback_bind_address,
)
from capability_exchange.concierge.views import render_journey
from capability_exchange.contribution import PermissionSet
from capability_exchange.contribution.lifecycle import StorePort
from capability_exchange.evidence import EvidenceLevel, EvidenceState
from capability_exchange.jobs import CandidateJobProposal, JobStoreError, SuccessContract

__all__ = ["ConciergeServer", "ConciergeSession", "new_session"]

SESSION_COOKIE = "dex_lens_session"
SESSION_TTL = timedelta(minutes=30)
MAX_FORM_BYTES = 64 * 1024
MAX_FORM_FIELDS = 64


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_tempdir_outside_scope(
    tempdir: Path, approved_roots: tuple[Path, ...]
) -> None:
    resolved_tempdir = tempdir.resolve(strict=True)
    for root in approved_roots:
        resolved_root = root.resolve(strict=True)
        if resolved_tempdir == resolved_root or resolved_tempdir.is_relative_to(
            resolved_root
        ):
            raise ValueError("session state directory overlaps the approved read scope")


def _private_tempdir_outside(
    approved_roots: tuple[Path, ...],
) -> tempfile.TemporaryDirectory[str]:
    """Create private session state where it cannot mutate inspected scope."""

    candidates = (Path(tempfile.gettempdir()), Path("/var/tmp"), Path("/dev/shm"))
    attempted: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved in attempted or not resolved.is_dir():
            continue
        attempted.add(resolved)
        try:
            tempdir = tempfile.TemporaryDirectory(prefix="dex-lens-", dir=resolved)
            _require_tempdir_outside_scope(Path(tempdir.name), approved_roots)
        except (OSError, ValueError):
            if "tempdir" in locals():
                tempdir.cleanup()
                del tempdir
            continue
        return tempdir
    raise ValueError("no private session directory exists outside the approved scope")


@dataclass
class ConciergeSession:
    """One private local browser session."""

    approved_roots: tuple[Path, ...]
    collector: Callable[..., AdapterResultEnvelope]
    now: Callable[[], datetime] = _utc_now
    bootstrap_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    csrf_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    session_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    expires_at: datetime = field(default_factory=lambda: _utc_now() + SESSION_TTL)
    bootstrap_used: bool = False
    closed: bool = False
    envelope: AdapterResultEnvelope | None = None
    proposals: tuple[CandidateJobProposal, ...] = ()
    contracts: tuple[SuccessContract, ...] = ()
    capability_map_markdown: str = ""
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    fallback: bool = False
    fallback_message: str = ""
    cleanup_error: str = ""
    contribution_identity: ContributionIdentityPort | None = None
    contribution_intake: ContributionIntakePort | None = None
    contribution_stores: tuple[StorePort, ...] = ()
    adapter_contract: AdapterContract | None = None
    catalogue_url: str = DEFAULT_CATALOGUE_URL
    catalogue_store: VerifiedCatalogueStore | None = None
    catalogue_keyring: KeyRing | None = None
    catalogue_fetcher: ConsentedCatalogueFetcher | None = None
    app_storage: Path | None = None
    catalogue_subscription_store: CatalogueSubscriptionStore | None = None
    startup_catalogue_fetch_result: CatalogueFetchResult | None = None
    journey: ConciergeJourney = field(init=False, repr=False)
    _security: SessionSecurity = field(init=False, repr=False)
    _consent_scope: ScopeSnapshot = field(init=False, repr=False)
    _collection: CollectionController | None = field(default=None, init=False, repr=False)
    _collection_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _expiry_timer: threading.Timer | None = field(default=None, init=False, repr=False)
    _state_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        contribution_ports = (
            self.contribution_identity is not None,
            self.contribution_intake is not None,
        )
        if any(contribution_ports) and not all(contribution_ports):
            raise ValueError("contribution identity and intake ports must be configured together")
        self._consent_scope = ScopeSnapshot.capture(self.approved_roots)
        if self.tempdir is None:
            self.tempdir = _private_tempdir_outside(self.approved_roots)
        _require_tempdir_outside_scope(Path(self.tempdir.name), self.approved_roots)
        if self.app_storage is None:
            self.app_storage = default_lens_app_storage(self.approved_roots)
        require_app_storage_outside_roots(self.app_storage, self.approved_roots)
        if self.catalogue_store is None:
            self.catalogue_store = VerifiedCatalogueStore(
                self.app_storage
            )
        if self.catalogue_subscription_store is None:
            self.catalogue_subscription_store = CatalogueSubscriptionStore(
                self.app_storage
            )
        if self.catalogue_fetcher is None:
            self.catalogue_fetcher = ConsentedCatalogueFetcher(
                store=self.catalogue_store,
                keyring=self.catalogue_keyring,
                now=self.now,
            )
        contract = self.adapter_contract or claude_code_contract(
            tuple(str(root) for root in self.approved_roots)
        )
        permission = PermissionMetadata.from_contract(
            contract,
            approved_roots=self.approved_roots,
            next_action=(
                "Run one contained, read-only collection and review inferred job drafts"
            ),
            no_catalog=True,
            offline_capable=True,
            catalogue_host_adapter=CLAUDE_CODE_CATALOGUE_HOST_ADAPTER,
        )
        self.journey = ConciergeJourney(
            permission=permission,
            collector=self._collect_for_journey,
            job_store=Path(self.tempdir.name) / "inspection-jobs",
            now=self.now,
            adapter_contract=contract,
        )
        assert self.catalogue_subscription_store is not None
        self.journey.catalogue_subscription_record = (
            self.catalogue_subscription_store.load()
        )
        self._fetch_subscribed_catalogue_once()
        self._security = SessionSecurity(
            bootstrap_token=self.bootstrap_token,
            session_token=self.session_token,
            csrf_token=self.csrf_token,
            expires_at=self.expires_at,
            now=self.now,
            bootstrap_used=self.bootstrap_used,
            closed=self.closed,
            on_terminate=self._discard,
        )
        delay = max(0.0, (self.expires_at - self.now()).total_seconds())
        self._expiry_timer = threading.Timer(delay, self.terminate_and_wait)
        self._expiry_timer.daemon = True
        self._expiry_timer.start()

    def _fetch_subscribed_catalogue_once(self) -> None:
        assert self.catalogue_subscription_store is not None
        assert self.catalogue_fetcher is not None
        subscription = self.catalogue_subscription_store.load()
        if not subscription.subscribed:
            return
        try:
            consent = CatalogueFetchConsent(
                catalogue_url=subscription.catalogue_url,
                requested_at=self.now(),
                statement=CONSENT_STATEMENT,
            )
        except ValueError:
            return
        self.startup_catalogue_fetch_result = self.catalogue_fetcher.fetch(consent)

    @property
    def security(self) -> SessionSecurity:
        """The shared, lock-protected session security state."""

        return self._security

    @property
    def inventory_state(self) -> ConciergeSessionState:
        """Return the non-secret, inventory-checked browser/session view."""

        references = tuple(
            "scope:" + hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
            for root in self.approved_roots
        )
        return self._security.inventory_state(
            approved_scope_references=references,
            journey_state=self.journey.stage.value,
        )

    def expired(self) -> bool:
        return self._security.expired()

    def terminate(self) -> None:
        self._security.terminate()

    def wait_for_collection_stop(self, timeout: float = 1.0) -> bool:
        thread = self._collection_thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def terminate_and_wait(self) -> bool:
        """Close state, then prove the process-backed collector has stopped."""

        self.terminate()
        return self.wait_for_collection_stop()

    def _discard(self) -> None:
        """Erase all ephemeral session state after a terminal failure."""

        with self._state_lock:
            self.closed = True
            collection = self._collection
            if collection is not None:
                collection.cancel()
            try:
                self.journey.close()
            except DeletionError:
                self.cleanup_error = (
                    "local draft deletion could not be verified; session is closed"
                )
            self.bootstrap_token = ""
            self.session_token = ""
            self.csrf_token = ""
            self.envelope = None
            self.proposals = ()
            self.contracts = ()
            self.capability_map_markdown = ""
            self.fallback = False
            self.fallback_message = ""
            if self.tempdir is not None:
                try:
                    self.tempdir.cleanup()
                except OSError:
                    self.cleanup_error = (
                        "local session cleanup could not be verified; session is closed"
                    )
                self.tempdir = None
            timer = self._expiry_timer
            if timer is not None:
                timer.cancel()
                self._expiry_timer = None

    def approve_scope_and_collect(self) -> None:
        """Run the first read-only collection after explicit approval."""
        self._begin_collection()
        self._finish_collection()

    def start_scope_collection(self) -> threading.Thread:
        """Start collection off-thread so the browser keeps a cancel control."""

        self._begin_collection()
        thread = threading.Thread(
            target=self._finish_collection_in_background,
            name="dex-lens-session-collection",
            daemon=True,
        )
        with self._state_lock:
            self._collection_thread = thread
            thread.start()
        return thread

    def _begin_collection(self) -> None:
        with self._state_lock:
            if self.closed or self.expired():
                raise ValueError("session is closed or expired")
            try:
                self._consent_scope.revalidate(self.approved_roots)
            except ValueError:
                self.terminate()
                raise
            self.journey.begin_collection()

    def _finish_collection_in_background(self) -> None:
        try:
            self._finish_collection()
        except Exception:
            # The terminal state is rendered on the next request; no partial
            # exception or adapter detail is published from the worker.
            return

    def _finish_collection(self) -> None:
        try:
            result = self._collect_for_journey()
            with self._state_lock:
                controller = self._collection
                if controller is not None:
                    controller.revalidate_scope()
                if (
                    self.closed
                    or self.expired()
                    or controller is None
                    or controller.cancelled
                ):
                    raise ValueError(
                        "collection cancelled; partial data was discarded"
                    )
                self.journey.complete_collection(result)
                self._sync_journey()
        except Exception as exc:
            self.terminate()
            if isinstance(exc, ValueError):
                raise
            raise ValueError("contained collection failed; session was closed") from exc

    def _collect_for_journey(self) -> AdapterResultEnvelope | CollectionFallback:
        """Collect through R3 control and translate an honest fallback."""
        with self._state_lock:
            if self.closed or self.expired():
                raise ValueError("session is closed or expired")
            controller = CollectionController(
                self.approved_roots,
                scope_provider=lambda: self.approved_roots,
                scope_snapshot=self._consent_scope,
            )
            self._collection = controller
        try:
            result = controller.collect(self.collector)
            # The controller snapshots the roots at collection start.  Check
            # the live session set once more so a scope shrink/replacement
            # racing the collector cannot publish a result for stale scope.
            controller.revalidate_scope()
        except CollectionCancelled as exc:
            self.terminate()
            raise ValueError("collection cancelled; partial data was discarded") from exc
        except ValueError:
            self.terminate()
            raise
        if not isinstance(result, CollectionResult):
            # CollectionController always wraps envelopes, but retaining this
            # guard protects callers that provide a compatible implementation.
            result = CollectionResult(envelope=result)
        if result.fallback:
            fallback_evidence: list[FallbackEvidence] = []
            for probe in result.envelope.probes:
                for item in probe.evidence:
                    # A fallback envelope is never allowed to smuggle a
                    # direct observation into the person-facing path.  Only
                    # the two non-direct claim states retain a positive label;
                    # every other state is visibly Unknown.
                    level = (
                        EvidenceLevel.SUPPORTED
                        if item.state is EvidenceState.INFERRED
                        else EvidenceLevel.REPORTED
                        if item.state is EvidenceState.USER_REPORTED
                        else EvidenceLevel.UNKNOWN
                    )
                    fallback_evidence.append(
                        FallbackEvidence(
                            label=probe.probe_id,
                            level=level,
                            detail=probe.detail or "No direct evidence was collected.",
                            reference=item.reference,
                            probe_id=probe.probe_id,
                        )
                    )
            reason = result.message or (
                "The contained adapter is unavailable on this host. No direct "
                "inspection result was published."
            )
            # Adapter refusal text is guidance, not a payload.  Keep enough of
            # it to explain the fallback while respecting the session bound.
            reason = " ".join(reason.split())[:512].rstrip()
            return CollectionFallback(
                mode=FallbackMode.GUIDED,
                reason=reason,
                evidence=tuple(fallback_evidence),
            )
        return result.envelope

    def _sync_journey(self) -> None:
        self.envelope = self.journey.envelope
        self.proposals = self.journey.proposals
        self.contracts = self.journey.contracts
        self.capability_map_markdown = self.journey.capability_map_markdown
        self.fallback = self.journey.fallback is not None
        self.fallback_message = (
            "" if self.journey.fallback is None else self.journey.fallback.reason
        )

    def confirm_jobs(self, job_ids: tuple[str, ...]) -> None:
        """Refuse the obsolete checkbox shortcut; full fields are required."""
        raise ValueError(
            "each selected job needs a full Success Contract before diagnosis"
        )

    def add_job(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.add_job(
                JobDraftFields(
                    job_id=_optional(form, "job_id"),
                    title=_required(form, "title"),
                    situation=_required(form, "situation"),
                    desired_outcome=_required(form, "desired_outcome"),
                )
            )
            self._sync_journey()

    def edit_job(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.edit_job(
                _required(form, "job_id"),
                title=_required(form, "title"),
                situation=_required(form, "situation"),
                desired_outcome=_required(form, "desired_outcome"),
            )
            self._sync_journey()

    def discard_job(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.discard_job(_required(form, "job_id"))
            self._sync_journey()

    def confirm_job(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.confirm_job(
                _required(form, "job_id"),
                ContractFields(
                    success_evidence=_form_lines(form, "success_evidence"),
                    privacy_limits=_form_lines(form, "privacy_limits"),
                    approval_limits=_form_lines(form, "approval_limits"),
                    autonomy_limits=_form_lines(form, "autonomy_limits"),
                    importance=_required(form, "importance"),
                    cadence=_required(form, "cadence"),
                ),
            )
            self._sync_journey()

    def set_fallback_mode(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.set_fallback_mode(_required(form, "mode"))
            self._sync_journey()

    def add_fallback_evidence(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.add_fallback_evidence(
                FallbackEvidence(
                    label=_required(form, "label"),
                    level=_required(form, "level"),
                    detail=_required(form, "detail"),
                    reference=_optional(form, "reference"),
                    probe_id=_optional(form, "probe_id"),
                )
            )
            self._sync_journey()

    def import_fallback_evidence(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.import_fallback_evidence(
                _required(form, "evidence"),
                mode=_optional(form, "mode"),
            )
            self._sync_journey()

    def continue_fallback(self) -> None:
        with self._state_lock:
            self.journey.continue_fallback()
            self._sync_journey()

    def diagnose(self) -> None:
        with self._state_lock:
            self.journey.diagnose()
            if self.startup_catalogue_fetch_result is not None:
                self.journey.record_catalogue_fetch(self.startup_catalogue_fetch_result)
                if self.startup_catalogue_fetch_result.display_catalogue is not None:
                    self.journey.open_catalogue_shelf()
            if (
                self.contribution_identity is not None
                and self.contribution_intake is not None
                and not self.journey.contribution_available
            ):
                self.configure_contribution()
            self._sync_journey()

    def fetch_catalogue(self, form: dict[str, list[str]]) -> CatalogueFetchResult:
        with self._state_lock:
            if self.closed or self.expired():
                raise ValueError("session is closed or expired")
            statement = _optional(form, "catalogue_consent") or ""
            url = _optional(form, "catalogue_url") or self.catalogue_url
            try:
                consent = CatalogueFetchConsent(
                    catalogue_url=url,
                    requested_at=self.now(),
                    statement=statement,
                )
            except ValueError as exc:
                result = CatalogueFetchResult(
                    status=CatalogueFetchStatus.REFUSED,
                    message=str(exc),
                    catalog_version=None,
                    verified=None,
                    stale=None,
                    fetched_at=self.now(),
                )
                self.journey.record_catalogue_fetch(result)
                return result
            assert self.catalogue_fetcher is not None
            result = self.catalogue_fetcher.fetch(consent)
            self.journey.record_catalogue_fetch(result)
            return result

    def open_catalogue_shelf(self) -> None:
        with self._state_lock:
            self.journey.open_catalogue_shelf()

    def select_catalogue_brief(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.select_catalogue_brief(form)

    def catalogue_brief_download(self) -> tuple[str, str]:
        """Return the selected portable brief and a safe attachment filename."""

        with self._state_lock:
            capability_id = self.journey.selected_catalogue_capability_id
            markdown = self.journey.catalogue_brief_markdown
            if not capability_id or not markdown:
                raise ValueError("select a catalogue brief before downloading")
            safe_id = "".join(
                character
                for character in capability_id
                if character.isalnum() or character == "-"
            ).strip("-")
            return markdown, f"dex-brief-{safe_id or 'capability'}.md"

    def subscribe_catalogue_updates(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            assert self.catalogue_subscription_store is not None
            url = _optional(form, "catalogue_url") or self.catalogue_url
            self.catalogue_subscription_store.subscribe(
                catalogue_url=url,
                now=self.now(),
            )
            self.journey.catalogue_subscription_record = (
                self.catalogue_subscription_store.load()
            )

    def revoke_catalogue_updates(self) -> None:
        with self._state_lock:
            assert self.catalogue_subscription_store is not None
            self.catalogue_subscription_store.revoke(now=self.now())
            self.journey.catalogue_subscription_record = (
                self.catalogue_subscription_store.load()
            )

    def look_catalogue_updates(self) -> None:
        with self._state_lock:
            assert self.catalogue_subscription_store is not None
            result = self.journey.catalogue_fetch_result
            if result is not None and result.catalog_version is not None:
                self.catalogue_subscription_store.mark_seen(
                    catalog_version=result.catalog_version,
                    now=self.now(),
                )
            self.journey.catalogue_subscription_record = (
                self.catalogue_subscription_store.load()
            )
            if self.journey.stage is ConciergeStage.CAPABILITY_MAP:
                self.journey.open_catalogue_shelf()

    def park_catalogue_updates(self) -> None:
        with self._state_lock:
            assert self.catalogue_subscription_store is not None
            result = self.journey.catalogue_fetch_result
            if result is None or result.catalog_version is None:
                raise ValueError("no catalogue update is available to park")
            self.catalogue_subscription_store.park(
                catalog_version=result.catalog_version,
                now=self.now(),
            )
            self.journey.catalogue_subscription_record = (
                self.catalogue_subscription_store.load()
            )

    # M4 stages 7-8 stay behind the same narrow session boundary as the M3
    # journey.  HTTP handlers only parse bounded form fields and call these
    # methods; preview, approval, apply, receipt, verification, and undo all
    # remain domain transitions on ``ConciergeJourney``.

    def select_adaptation(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.select_adaptation(
                job_id=_required(form, "job_id"),
                capability_id=_required(form, "capability_id"),
                approved_skills_root=Path(_required(form, "approved_skills_root")),
                markdown=_required(form, "markdown"),
                expected_benefit=_required(form, "expected_benefit"),
                observable_signal=_required(form, "observable_signal"),
            )

    def preview_adaptation(self) -> None:
        with self._state_lock:
            self.journey.preview_adaptation()

    def approve_adaptation(self) -> None:
        with self._state_lock:
            self.journey.approve_adaptation()

    def apply_adaptation(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            token = _optional(form, "approval_token")
            self.journey.apply_adaptation(approval_token=token or None)

    def verify_adaptation(self) -> None:
        with self._state_lock:
            self.journey.verify_adaptation()

    def undo_adaptation(self) -> None:
        with self._state_lock:
            self.journey.undo_adaptation()

    def configure_contribution(self) -> None:
        """Attach external ports after diagnosis without invoking either port."""

        if self.contribution_identity is None or self.contribution_intake is None:
            raise ValueError("contribution ports are unavailable")
        self.journey.configure_contribution(
            identity=self.contribution_identity,
            intake=self.contribution_intake,
            stores=self.contribution_stores,
        )

    def choose_contribution(self) -> None:
        with self._state_lock:
            if not self.journey.contribution_available:
                self.configure_contribution()
            self.journey.choose_contribution()

    def build_contribution(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            card = CapabilityCard.model_validate_json(_required(form, "card_json"))
            self.journey.build_contribution(card)

    def edit_contribution(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            card = CapabilityCard.model_validate_json(_required(form, "card_json"))
            self.journey.edit_contribution(card)

    def review_contribution(self) -> None:
        with self._state_lock:
            self.journey.review_contribution()

    def disclose_contribution(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            fields = tuple(form.get("approved_field", ()))
            self.journey.disclose_contribution(fields)

    def approve_contribution(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            granted = set(form.get("permission", ()))
            allowed = {
                "review",
                "storage",
                "moderation",
                "attribution",
                "reuse",
                "distribution",
            }
            unknown = granted - allowed
            if unknown:
                raise ValueError("unknown contribution permission")
            self.journey.approve_contribution(
                PermissionSet(**{name: name in granted for name in sorted(allowed)})
            )

    def submit_contribution(self) -> None:
        with self._state_lock:
            self.journey.submit_contribution()

    def withdraw_contribution(self, form: dict[str, list[str]]) -> None:
        with self._state_lock:
            self.journey.withdraw_contribution(
                reason=_optional(form, "reason") or "person requested withdrawal"
            )

    def _revalidate_scope(self) -> None:
        missing = tuple(path for path in self.approved_roots if not path.exists())
        if missing:
            self.terminate()
            raise ValueError("approved scope changed before collection could run")


def new_session(
    *,
    approved_roots: tuple[Path, ...],
    collector: Callable[..., AdapterResultEnvelope],
    now: Callable[[], datetime] = _utc_now,
    contribution_identity: ContributionIdentityPort | None = None,
    contribution_intake: ContributionIntakePort | None = None,
    contribution_stores: tuple[StorePort, ...] = (),
    adapter_contract: AdapterContract | None = None,
    catalogue_url: str = DEFAULT_CATALOGUE_URL,
    catalogue_store: VerifiedCatalogueStore | None = None,
    catalogue_keyring: KeyRing | None = None,
    catalogue_fetcher: ConsentedCatalogueFetcher | None = None,
    app_storage: Path | None = None,
    catalogue_subscription_store: CatalogueSubscriptionStore | None = None,
) -> ConciergeSession:
    """Create a session with expiry derived from the supplied clock."""
    return ConciergeSession(
        approved_roots=approved_roots,
        collector=collector,
        now=now,
        expires_at=now() + SESSION_TTL,
        contribution_identity=contribution_identity,
        contribution_intake=contribution_intake,
        contribution_stores=contribution_stores,
        adapter_contract=adapter_contract,
        catalogue_url=catalogue_url,
        catalogue_store=catalogue_store,
        catalogue_keyring=catalogue_keyring,
        catalogue_fetcher=catalogue_fetcher,
        app_storage=app_storage,
        catalogue_subscription_store=catalogue_subscription_store,
    )


class ConciergeServer(ThreadingHTTPServer):
    """Loopback-only HTTP server carrying one concierge session."""

    allow_reuse_address = False

    def __init__(self, server_address: tuple[str, int], session: ConciergeSession) -> None:
        ensure_loopback_bind_address(server_address)
        super().__init__(server_address, _ConciergeHandler)
        self.session = session


class _ConciergeHandler(BaseHTTPRequestHandler):
    server: ConciergeServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5.0)

    def do_GET(self) -> None:
        if self._hostile_upgrade():
            return
        if not self._trusted_host():
            self._forbidden("host is not trusted")
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            query = parse_qs(parsed.query, keep_blank_values=True)
            values = query.get("token", [])
            self._bootstrap(values[0] if set(query) == {"token"} and len(values) == 1 else "")
            return
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "token" in query:
            self._security_failure("bootstrap tokens are valid only at the doorway")
            return
        if not self._valid_session_cookie():
            self._forbidden("session is not valid")
            return
        if parsed.path == "/session" or parsed.path in {
            "/adaptation/receipt",
            "/adapt/receipt",
        }:
            self._send_page(_render_session(self.server.session))
            return
        self._not_found()

    def do_POST(self) -> None:
        if self._hostile_upgrade():
            return
        if not self._trusted_host():
            self._forbidden("host is not trusted")
            return
        if not self._valid_session_cookie():
            self._forbidden("session is not valid")
            return
        if self.headers.get("Transfer-Encoding"):
            self._security_failure("streamed request bodies are not supported")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._security_failure("invalid request length")
            return
        if length < 0 or length > MAX_FORM_BYTES:
            self._security_failure("invalid request length")
            return
        try:
            raw_body = self.rfile.read(length).decode("utf-8", "replace")
            form = parse_qs(raw_body, max_num_fields=MAX_FORM_FIELDS)
        except (OSError, ValueError):
            self._security_failure("request body is invalid or too large")
            return
        if not self._valid_origin_and_csrf(form):
            self._forbidden("request failed session security checks")
            return
        parsed = urlparse(self.path)
        if "token" in parse_qs(parsed.query, keep_blank_values=True):
            self._security_failure("bootstrap tokens are valid only at the doorway")
            return
        if parsed.path == "/approve":
            self._approve()
            return
        if parsed.path in {"/decline", "/cancel"}:
            stopped = self.server.session.terminate_and_wait()
            message = (
                "<p>No inspection is running.</p>"
                if stopped
                else "<p>Session closed; collection stop could not be proven.</p>"
            )
            self._send_page(_page("Session closed", message))
            return
        if parsed.path == "/confirm-jobs":
            self._confirm_jobs(form)
            return
        if parsed.path == "/fallback/mode":
            self._journey_action(self.server.session.set_fallback_mode, form)
            return
        if parsed.path == "/fallback/evidence":
            self._journey_action(self.server.session.add_fallback_evidence, form)
            return
        if parsed.path == "/fallback/import":
            self._journey_action(self.server.session.import_fallback_evidence, form)
            return
        if parsed.path == "/fallback/continue":
            self._journey_action(
                lambda ignored: self.server.session.continue_fallback(), form
            )
            return
        if parsed.path == "/jobs/add":
            self._journey_action(self.server.session.add_job, form)
            return
        if parsed.path == "/jobs/edit":
            self._journey_action(self.server.session.edit_job, form)
            return
        if parsed.path == "/jobs/discard":
            self._journey_action(self.server.session.discard_job, form)
            return
        if parsed.path == "/jobs/confirm":
            self._journey_action(self.server.session.confirm_job, form)
            return
        if parsed.path == "/diagnose":
            self._journey_action(lambda ignored: self.server.session.diagnose(), form)
            return
        if parsed.path == "/catalogue/fetch":
            self._journey_action(
                lambda submitted: self.server.session.fetch_catalogue(submitted),
                form,
            )
            return
        if parsed.path == "/catalogue/shelf":
            self._journey_action(
                lambda ignored: self.server.session.open_catalogue_shelf(), form
            )
            return
        if parsed.path == "/catalogue/brief":
            self._journey_action(self.server.session.select_catalogue_brief, form)
            return
        if parsed.path == "/catalogue/brief/download":
            self._catalogue_brief_download()
            return
        if parsed.path == "/catalogue/subscribe":
            self._journey_action(self.server.session.subscribe_catalogue_updates, form)
            return
        if parsed.path == "/catalogue/revoke":
            self._journey_action(
                lambda ignored: self.server.session.revoke_catalogue_updates(), form
            )
            return
        if parsed.path == "/catalogue/updates/look":
            self._journey_action(
                lambda ignored: self.server.session.look_catalogue_updates(), form
            )
            return
        if parsed.path == "/catalogue/updates/park":
            self._journey_action(
                lambda ignored: self.server.session.park_catalogue_updates(), form
            )
            return
        if parsed.path in {"/adaptation/select", "/adapt/select"}:
            self._journey_action(self.server.session.select_adaptation, form)
            return
        if parsed.path in {"/adaptation/preview", "/adapt/preview"}:
            self._journey_action(
                lambda ignored: self.server.session.preview_adaptation(), form
            )
            return
        if parsed.path in {"/adaptation/approve", "/adapt/approve"}:
            self._journey_action(
                lambda ignored: self.server.session.approve_adaptation(), form
            )
            return
        if parsed.path in {"/adaptation/apply", "/adapt/apply"}:
            self._journey_action(self.server.session.apply_adaptation, form)
            return
        if parsed.path in {"/adaptation/verify", "/adapt/verify"}:
            self._journey_action(
                lambda ignored: self.server.session.verify_adaptation(), form
            )
            return
        if parsed.path in {"/adaptation/undo", "/adapt/undo"}:
            self._journey_action(
                lambda ignored: self.server.session.undo_adaptation(), form
            )
            return
        if parsed.path == "/contribution/choose":
            self._journey_action(
                lambda ignored: self.server.session.choose_contribution(), form
            )
            return
        if parsed.path == "/contribution/build":
            self._journey_action(self.server.session.build_contribution, form)
            return
        if parsed.path == "/contribution/edit":
            self._journey_action(self.server.session.edit_contribution, form)
            return
        if parsed.path == "/contribution/review":
            self._journey_action(
                lambda ignored: self.server.session.review_contribution(), form
            )
            return
        if parsed.path == "/contribution/disclose":
            self._journey_action(self.server.session.disclose_contribution, form)
            return
        if parsed.path == "/contribution/approve":
            self._journey_action(self.server.session.approve_contribution, form)
            return
        if parsed.path == "/contribution/submit":
            self._journey_action(
                lambda ignored: self.server.session.submit_contribution(), form
            )
            return
        if parsed.path == "/contribution/withdraw":
            self._journey_action(self.server.session.withdraw_contribution, form)
            return
        if parsed.path == "/close":
            self.server.session.terminate_and_wait()
            self._send_page(_render_session(self.server.session))
            return
        self._not_found()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _bootstrap(self, token: str) -> None:
        session = self.server.session
        if not session.security.consume_bootstrap(token):
            self._forbidden("bootstrap token expired or already used")
            return
        session.bootstrap_used = True
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/session")
        self.send_header(
            "Set-Cookie",
            (
                f"{SESSION_COOKIE}={session.session_token}; "
                "HttpOnly; SameSite=Strict; Path=/"
            ),
        )
        # The one-use bearer is still present in this request URL, so never
        # allow it to become a referrer.  The token-free session page uses
        # ``same-origin`` so Chromium gives native POSTs a concrete Origin.
        self._security_headers(referrer_policy="no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _approve(self) -> None:
        try:
            thread = self.server.session.start_scope_collection()
        except (JourneyError, ValueError) as exc:
            self._bad_request(str(exc))
            return
        # Immediate synthetic/small collections preserve the one-click flow;
        # larger real collections return the cancellable progress page.
        thread.join(timeout=0.05)
        self._send_page(_render_session(self.server.session))

    def _confirm_jobs(self, form: dict[str, list[str]]) -> None:
        job_ids = tuple(form.get("job_id", ()))
        try:
            self.server.session.confirm_jobs(job_ids)
        except ValueError as exc:
            self._bad_request(str(exc))
            return
        self._send_page(_render_session(self.server.session))

    def _journey_action(
        self,
        action: Callable[[dict[str, list[str]]], None],
        form: dict[str, list[str]],
    ) -> None:
        try:
            action(form)
        except DeletionError:
            self.server.session.terminate_and_wait()
            self._bad_request(
                "local draft deletion could not be verified; session was closed"
            )
            return
        except (JobStoreError, JourneyError, TypeError, ValueError) as exc:
            if self.server.session.journey.stage in {
                ConciergeStage.ADAPTATION_REFUSED,
                ConciergeStage.ADAPTATION_HARD_STOP,
                ConciergeStage.CONTRIBUTION_WITHDRAW,
            }:
                self._send_page(
                    _render_session(self.server.session),
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._bad_request(str(exc))
            return
        except (
            ApprovalExpiredError,
            ApprovalMismatchError,
            ApprovalReplayError,
            AutomationHardStoppedError,
            RecoveryFailedError,
            TransactionConflictError,
            TransactionFailedError,
            UndoConflictError,
        ):
            # The domain transition has already recorded refusal/hard-stop
            # state.  Render that state instead of leaking a traceback or
            # attempting an implicit retry from the transport layer.
            self._send_page(_render_session(self.server.session), status=HTTPStatus.BAD_REQUEST)
            return
        self._send_page(_render_session(self.server.session))

    def _catalogue_brief_download(self) -> None:
        try:
            markdown, filename = self.server.session.catalogue_brief_download()
        except ValueError as exc:
            self._bad_request(str(exc))
            return
        payload = markdown.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self._security_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _valid_session_cookie(self) -> bool:
        return self.server.session.security.validate_cookie(self.headers.get("Cookie", ""))

    def _valid_origin_and_csrf(self, form: dict[str, list[str]]) -> bool:
        origin = self.headers.get("Origin", "")
        csrf = self.headers.get("X-CSRF-Token", "") or next(
            iter(form.get("csrf_token", ())), ""
        )
        return self.server.session.security.validate_origin_csrf(
            origin, csrf, self.server.server_port
        )

    def _trusted_host(self) -> bool:
        return self.server.session.security.validate_host(
            self.headers.get("Host", ""), self.server.server_port
        )

    def _hostile_upgrade(self) -> bool:
        upgrade = self.headers.get("Upgrade", "").strip().lower()
        connection = {
            token.strip().lower()
            for token in self.headers.get("Connection", "").split(",")
        }
        if upgrade == "websocket" or "upgrade" in connection:
            self._security_failure("WebSocket upgrades are not supported")
            return True
        return False

    def _security_failure(self, message: str) -> None:
        self.server.session.terminate_and_wait()
        self._forbidden(message)

    def _security_headers(self, *, referrer_policy: str = "same-origin") -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", referrer_policy)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'none'; connect-src 'none'; img-src 'none'; "
            "object-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )

    def _send_page(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._security_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _forbidden(self, message: str) -> None:
        self._send_page(
            _page("Access refused", f"<p>{html.escape(message)}</p>"),
            HTTPStatus.FORBIDDEN,
        )

    def _bad_request(self, message: str) -> None:
        self._send_page(
            _page("Request refused", f"<p>{html.escape(message)}</p>"),
            HTTPStatus.BAD_REQUEST,
        )

    def _not_found(self) -> None:
        self._send_page(
            _page("Not found", "<p>This local session has no such page.</p>"),
            HTTPStatus.NOT_FOUND,
        )


def _page(title: str, main: str, session: ConciergeSession | None = None) -> str:
    csrf = (
        f'<meta name="csrf-token" content="{html.escape(session.csrf_token)}">'
        if session is not None
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {csrf}
  <title>{html.escape(title)} - Dex Lens</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #161616;
      --muted: #5f6468;
      --line: #d9dddf;
      --paper: #fbfcfc;
      --accent: #0f766e;
      --accent-dark: #0b4f4a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family:
        ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      background: var(--paper);
      color: var(--ink);
    }}
    main {{
      width: min(920px, calc(100vw - 32px));
      margin: 48px auto;
    }}
    h1 {{ font-size: 2rem; line-height: 1.15; margin: 0 0 16px; }}
    h2 {{ font-size: 1.25rem; margin: 32px 0 12px; }}
    p, li {{ color: var(--muted); line-height: 1.55; }}
    .panel {{ border: 1px solid var(--line); border-radius: 8px; padding: 20px; background: #fff; }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 20px; }}
    button {{
      border: 1px solid var(--accent-dark);
      background: var(--accent);
      color: white;
      border-radius: 6px;
      padding: 10px 14px;
      font: inherit;
      cursor: pointer;
    }}
    button.secondary {{ background: white; color: var(--accent-dark); }}
    label {{ display: block; margin: 12px 0; }}
    pre {{
      white-space: pre-wrap;
      background: #fff;
      border: 1px solid var(--line);
      padding: 16px;
      border-radius: 8px;
    }}
  </style>
</head>
<body><main>{main}</main></body>
</html>"""


def _render_session(session: ConciergeSession) -> str:
    with session._state_lock:
        return render_journey(session.journey, session.csrf_token)


def _required(form: dict[str, list[str]], name: str) -> str:
    value = next(iter(form.get(name, ())), "").strip()
    if not value:
        raise ValueError(f"{name.replace('_', ' ')} is required")
    return value


def _optional(form: dict[str, list[str]], name: str) -> str | None:
    value = next(iter(form.get(name, ())), "").strip()
    return value or None


def _form_lines(form: dict[str, list[str]], name: str) -> tuple[str, ...]:
    value = next(iter(form.get(name, ())), "")
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def session_for_roots(roots: tuple[Path, ...]) -> ConciergeSession:
    """Build the real CLI session for approved roots."""

    def collect(cancel_event: threading.Event | None = None) -> AdapterResultEnvelope:
        result = contained_inspection(
            [str(root) for root in roots], cancel_event=cancel_event
        )
        return result.envelope

    return new_session(approved_roots=roots, collector=collect)


def start_server(session: ConciergeSession) -> ConciergeServer:
    """Start a loopback-only server for one session."""
    server = ConciergeServer(("127.0.0.1", 0), session)
    return server
