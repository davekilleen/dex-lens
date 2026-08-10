"""Loopback-only local browser concierge (M3 stages 1-6).

The server is intentionally small and stdlib-only. It has no static asset
pipeline, no analytics, and no third-party resources; every page is rendered
from local state and every transition is a plain HTTP request guarded by a
single-use bootstrap token, a session cookie, Origin checking, and CSRF.
"""

from __future__ import annotations

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

from capability_exchange.adapter import AdapterResultEnvelope
from capability_exchange.adapters.claude_code.containment import contained_inspection
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.boundary.deletion import DeletionError
from capability_exchange.concierge.collection import (
    CollectionCancelled,
    CollectionController,
    CollectionResult,
    ScopeSnapshot,
)
from capability_exchange.concierge.journey import (
    CollectionFallback,
    ConciergeJourney,
    ContractFields,
    FallbackEvidence,
    FallbackMode,
    JobDraftFields,
    JourneyError,
    PermissionMetadata,
)
from capability_exchange.concierge.security import (
    SessionSecurity,
    ensure_loopback_bind_address,
)
from capability_exchange.concierge.views import render_journey
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
        self._consent_scope = ScopeSnapshot.capture(self.approved_roots)
        if self.tempdir is None:
            self.tempdir = _private_tempdir_outside(self.approved_roots)
        _require_tempdir_outside_scope(Path(self.tempdir.name), self.approved_roots)
        contract = claude_code_contract(tuple(str(root) for root in self.approved_roots))
        permission = PermissionMetadata.from_contract(
            contract,
            approved_roots=self.approved_roots,
            next_action=(
                "Run one contained, read-only collection and review inferred job drafts"
            ),
            no_catalog=True,
            offline_capable=True,
        )
        self.journey = ConciergeJourney(
            permission=permission,
            collector=self._collect_for_journey,
            job_store=Path(self.tempdir.name) / "inspection-jobs",
            now=self.now,
        )
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

    @property
    def security(self) -> SessionSecurity:
        """The shared, lock-protected session security state."""

        return self._security

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
            self._sync_journey()

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
) -> ConciergeSession:
    """Create a session with expiry derived from the supplied clock."""
    return ConciergeSession(
        approved_roots=approved_roots,
        collector=collector,
        now=now,
        expires_at=now() + SESSION_TTL,
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
        if parsed.path == "/session":
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
            self._bad_request(str(exc))
            return
        self._send_page(_render_session(self.server.session))

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
