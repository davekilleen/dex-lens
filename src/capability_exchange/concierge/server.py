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
from capability_exchange.capmap.render import render_capability_map
from capability_exchange.concierge.collection import (
    CollectionCancelled,
    CollectionController,
    CollectionResult,
)
from capability_exchange.concierge.security import (
    SessionSecurity,
    ensure_loopback_bind_address,
)
from capability_exchange.diagnosis import assess
from capability_exchange.jobs import (
    CandidateJobProposal,
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
    propose_candidate_jobs,
    to_inspection_job,
)

__all__ = ["ConciergeServer", "ConciergeSession", "new_session"]

SESSION_COOKIE = "dex_lens_session"
SESSION_TTL = timedelta(minutes=30)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ConciergeSession:
    """One private local browser session."""

    approved_roots: tuple[Path, ...]
    collector: Callable[[], AdapterResultEnvelope]
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
    _security: SessionSecurity = field(init=False, repr=False)
    _collection: CollectionController | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
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

    @property
    def security(self) -> SessionSecurity:
        """The shared, lock-protected session security state."""

        return self._security

    def expired(self) -> bool:
        return self._security.expired()

    def terminate(self) -> None:
        self._security.terminate()

    def _discard(self) -> None:
        """Erase all ephemeral session state after a terminal failure."""

        self.closed = True
        self.bootstrap_token = ""
        self.session_token = ""
        self.csrf_token = ""
        self.envelope = None
        self.proposals = ()
        self.contracts = ()
        self.capability_map_markdown = ""
        self.fallback = False
        self.fallback_message = ""
        collection = self._collection
        if collection is not None:
            collection.cancel()
        if self.tempdir is not None:
            self.tempdir.cleanup()
            self.tempdir = None

    def approve_scope_and_collect(self) -> None:
        """Run the first read-only collection after explicit approval."""
        if self.closed or self.expired():
            raise ValueError("session is closed or expired")
        controller = CollectionController(self.approved_roots)
        self._collection = controller
        try:
            result = controller.collect(self.collector)
            # The controller snapshots the roots at collection start.  Check
            # the live session set once more so a scope shrink/replacement
            # racing the collector cannot publish a result for stale scope.
            controller.revalidate_scope(self.approved_roots)
        except CollectionCancelled as exc:
            self.terminate()
            raise ValueError("collection cancelled; partial data was discarded") from exc
        except ValueError:
            self.terminate()
            raise
        if self.closed or controller.cancelled:
            self.terminate()
            raise ValueError("collection cancelled; partial data was discarded")
        if not isinstance(result, CollectionResult):
            # CollectionController always wraps envelopes, but retaining this
            # guard protects callers that provide a compatible implementation.
            result = CollectionResult(envelope=result)
        self.envelope = result.envelope
        self.fallback = result.fallback
        self.fallback_message = result.message
        self.proposals = () if result.fallback else propose_candidate_jobs(self.envelope)

    def confirm_jobs(self, job_ids: tuple[str, ...]) -> None:
        """Confirm selected proposed jobs, then produce the read-only map."""
        if self.envelope is None:
            raise ValueError("collection must run before jobs can be confirmed")
        by_id = {proposal.candidate_id: proposal for proposal in self.proposals}
        if not job_ids:
            raise ValueError("confirm at least one proposed job before diagnosis")
        unknown = tuple(job_id for job_id in job_ids if job_id not in by_id)
        if unknown:
            raise ValueError("requested job id was not proposed in this session")

        confirmed: list[SuccessContract] = []
        for job_id in sorted(set(job_ids)):
            draft = to_inspection_job(by_id[job_id], created_at=self.now())
            confirmed.append(
                SuccessContract(
                    job_id=draft.job_id,
                    situation=draft.situation,
                    desired_outcome=draft.desired_outcome,
                    success_evidence=(
                        "the person confirmed this is the outcome to inspect",
                    ),
                    boundaries=JobBoundaries(
                        privacy_limits=("stay inside the approved read-only scope",),
                        approval_limits=("ask before any adaptation or contribution",),
                        autonomy_limits=("do not change files or contact services",),
                    ),
                    importance=JobImportance.MEDIUM,
                    cadence=JobCadence.IRREGULAR,
                    confirmed_at=self.now(),
                )
            )
        self.contracts = tuple(confirmed)
        self.capability_map_markdown = render_capability_map(
            assess(self.contracts, self.envelope, assessed_at=self.now())
        )

    def _revalidate_scope(self) -> None:
        missing = tuple(path for path in self.approved_roots if not path.exists())
        if missing:
            self.terminate()
            raise ValueError("approved scope changed before collection could run")


def new_session(
    *,
    approved_roots: tuple[Path, ...],
    collector: Callable[[], AdapterResultEnvelope],
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
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._security_failure("invalid request length")
            return
        if length < 0:
            self._security_failure("invalid request length")
            return
        raw_body = self.rfile.read(length).decode("utf-8", "replace")
        form = parse_qs(raw_body)
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
            self.server.session.terminate()
            self._send_page(_page("Session closed", "<p>No inspection was started.</p>"))
            return
        if parsed.path == "/confirm-jobs":
            self._confirm_jobs(form)
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
        self._security_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _approve(self) -> None:
        try:
            self.server.session.approve_scope_and_collect()
        except ValueError as exc:
            self._bad_request(str(exc))
            return
        self._send_page(_render_session(self.server.session))

    def _confirm_jobs(self, form: dict[str, list[str]]) -> None:
        job_ids = tuple(form.get("job_id", ()))
        try:
            self.server.session.confirm_jobs(job_ids)
        except ValueError as exc:
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
        self.server.session.terminate()
        self._forbidden(message)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
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
    if session.fallback:
        return _page(
            "Guided evidence only",
            f"<h1>Guided evidence only</h1>"
            f"<div class=\"panel\"><p>{html.escape(session.fallback_message)}</p>"
            "<p>No direct inspection ran, so this session contains no Verified claims. "
            "You can continue with guided or export-assisted evidence.</p></div>",
            session,
        )
    if session.capability_map_markdown:
        return _page(
            "Capability Map",
            f"<h1>Capability Map</h1><pre>{html.escape(session.capability_map_markdown)}</pre>",
            session,
        )
    if session.envelope is not None:
        proposals = "\n".join(
            (
                f"<label><input type=\"checkbox\" name=\"job_id\" "
                f"value=\"{html.escape(proposal.candidate_id)}\" checked> "
                f"{html.escape(proposal.title)}</label>"
            )
            for proposal in session.proposals
        )
        if not proposals:
            proposals = "<p>No candidate jobs were inferred from the approved scope.</p>"
        return _page(
            "Confirm your Job Map",
            f"""
            <h1>Confirm your Job Map</h1>
            <div class="panel">
              <p>These are inferred suggestions. Keep only the jobs you want diagnosed.</p>
              <form method="post" action="/confirm-jobs">
                <input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token)}">
                {proposals}
                <div class="actions">
                  <button type="submit">Confirm selected jobs</button>
                  <button class="secondary" formaction="/cancel">Cancel</button>
                </div>
              </form>
            </div>
            """,
            session,
        )
    roots = "".join(f"<li>{html.escape(str(root))}</li>" for root in session.approved_roots)
    return _page(
        "Inspection permission",
        f"""
        <h1>Inspection permission</h1>
        <div class="panel">
          <p>Nothing has been scanned yet.</p>
          <p>Dex Lens will inspect only these approved folders, read-only:</p>
          <ul>{roots}</ul>
          <p>It stays local, uses no analytics, and does not adapt or contribute anything.</p>
          <form method="post" action="/approve">
            <input type="hidden" name="csrf_token" value="{html.escape(session.csrf_token)}">
            <div class="actions">
              <button type="submit">Approve read-only inspection</button>
              <button class="secondary" formaction="/decline">Decline and leave</button>
            </div>
          </form>
        </div>
        """,
        session,
    )


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
