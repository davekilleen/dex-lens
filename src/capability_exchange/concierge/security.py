"""Fail-closed security helpers for the local browser concierge.

The concierge is deliberately a tiny HTTP server, but a browser can still
reach it from a hostile local page.  This module keeps the security decisions
centralised and makes the one-use bootstrap transition atomic under concurrent
requests.  A failed check is terminal: credentials and session state are
discarded instead of trying an unauthenticated or stale-scope fallback.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "ConciergeSessionState",
    "COOKIE_METADATA",
    "SessionSecurity",
    "SecurityFailure",
    "ensure_loopback_bind_address",
    "expected_loopback_origin",
]


# The cookie value and bearer tokens stay in memory only.  This metadata is
# safe to inventory because it describes the browser contract, never a value
# that can authenticate a session.
COOKIE_METADATA: tuple[str, ...] = (
    "name:dex_lens_session",
    "http-only",
    "same-site:strict",
    "path:/",
)


def _secret_digest(value: str) -> str:
    """Return a non-reversible reference for an in-memory bearer secret."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ConciergeSessionState(InventoriedModel):
    """The browser/session fields that may be represented at the G2 boundary.

    Raw bearer tokens are deliberately absent from this model.  Their
    digests, cookie policy, scope references, expiry, and journey state are
    still explicit and inventory-checked, so a future browser/session field
    cannot become an accidental persistence or transmission path.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_token_digest: str = Field(min_length=64, max_length=64)
    csrf_token_digest: str = Field(min_length=64, max_length=64)
    cookie_metadata: tuple[str, ...] = Field(min_length=1)
    approved_scope_references: tuple[str, ...] = Field(min_length=1)
    expires_at: datetime
    journey_state: str = Field(min_length=1, max_length=64)

    @field_validator("session_token_digest", "csrf_token_digest")
    @classmethod
    def _hex_digest(cls, value: str) -> str:
        if any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("session digests must be lowercase hexadecimal references")
        return value.lower()

    @field_validator("cookie_metadata")
    @classmethod
    def _metadata_lines(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("cookie metadata entries must be non-empty")
        return tuple(value)

    @field_validator("approved_scope_references")
    @classmethod
    def _scope_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.startswith("scope:") for item in value):
            raise ValueError("approved scope references must be non-raw scope locators")
        return tuple(value)

    @field_validator("expires_at")
    @classmethod
    def _aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("session expiry must be timezone-aware")
        return value


class SecurityFailure(ValueError):
    """A request failed a terminal session-security check."""


def ensure_loopback_bind_address(server_address: tuple[str, int]) -> tuple[str, int]:
    """Require the exact IPv4 loopback bind address.

    ``localhost`` and wildcard/IPv6 binds are intentionally rejected.  Name
    resolution is mutable and wildcard listeners expose the browser doorway to
    other interfaces, so neither is equivalent to ``127.0.0.1`` here.
    """

    if not isinstance(server_address, tuple) or len(server_address) != 2:
        raise ValueError("concierge must bind to the exact IPv4 loopback address")
    host, port = server_address
    if host != "127.0.0.1":
        raise ValueError(
            f"concierge must bind to exact loopback 127.0.0.1, not {host!r}"
        )
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("concierge port must be an integer from 0 to 65535")
    return server_address


def expected_loopback_origin(port: int) -> str:
    """Return the only browser Origin accepted for a listening port."""

    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("invalid loopback port")
    return f"http://127.0.0.1:{port}"


def _constant_time_equal(actual: str, expected: str) -> bool:
    return bool(actual) and bool(expected) and secrets.compare_digest(actual, expected)


@dataclass
class SessionSecurity:
    """Credentials and terminal validation state for one concierge session."""

    bootstrap_token: str
    session_token: str
    csrf_token: str
    expires_at: datetime
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    on_terminate: Callable[[], None] | None = None
    bootstrap_used: bool = False
    closed: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def expired(self) -> bool:
        """Whether the session has reached its expiry, using the supplied clock."""

        return self.now() >= self.expires_at

    def inventory_state(
        self,
        *,
        approved_scope_references: tuple[str, ...],
        journey_state: str,
    ) -> ConciergeSessionState:
        """Return the inventoried browser state without exposing secrets."""

        return ConciergeSessionState(
            session_token_digest=_secret_digest(self.session_token),
            csrf_token_digest=_secret_digest(self.csrf_token),
            cookie_metadata=COOKIE_METADATA,
            approved_scope_references=approved_scope_references,
            expires_at=self.expires_at,
            journey_state=journey_state,
        )

    def terminate(self) -> None:
        """Atomically close the session and erase all bearer credentials."""

        callback: Callable[[], None] | None
        with self._lock:
            if self.closed:
                return
            self.closed = True
            self.bootstrap_token = ""
            self.session_token = ""
            self.csrf_token = ""
            callback = self.on_terminate
            self.on_terminate = None
        if callback is not None:
            callback()

    def fail(self, reason: str) -> bool:
        """Terminate and return ``False`` for use in validation expressions."""

        self.terminate()
        return False

    def consume_bootstrap(self, token: str) -> bool:
        """Consume the bootstrap token exactly once.

        The check and state transition share one lock.  This matters even for a
        local-only server: two browser tabs or a replaying hostile page can hit
        the endpoint concurrently, and exactly one request must win.
        """

        with self._lock:
            if self.closed or self.expired() or self.bootstrap_used:
                should_fail = True
            elif not _constant_time_equal(token, self.bootstrap_token):
                should_fail = True
            else:
                self.bootstrap_used = True
                should_fail = False
        if should_fail:
            self.terminate()
            return False
        return True

    def validate_host(self, host: str, port: int) -> bool:
        """Accept only an exact Host header for the IPv4 loopback listener."""

        expected = f"127.0.0.1:{port}"
        with self._lock:
            valid = not self.closed and not self.expired() and host == expected
        if not valid:
            self.terminate()
            return False
        return True

    def validate_cookie(self, cookie_header: str) -> bool:
        """Validate the exact session cookie, rejecting duplicates/tampering."""

        with self._lock:
            expected = self.session_token
            valid = not self.closed and not self.expired()
            matches: list[str] = []
            if valid:
                for part in cookie_header.split(";"):
                    name, separator, value = part.strip().partition("=")
                    if separator and name == "dex_lens_session":
                        matches.append(value)
                valid = len(matches) == 1 and _constant_time_equal(matches[0], expected)
        if not valid:
            self.terminate()
            return False
        return True

    def validate_origin_csrf(self, origin: str, csrf: str, port: int) -> bool:
        """Require exact loopback Origin and the session CSRF token."""

        expected_origin = expected_loopback_origin(port)
        # Parse-and-compare prevents equivalent spellings (userinfo, alternate
        # ports, or a trailing path) from slipping through string normalisation.
        try:
            parsed = urlsplit(origin)
            parsed_port = parsed.port
        except ValueError:
            parsed = None
            parsed_port = None
        origin_shape_is_exact = bool(
            parsed is not None
            and parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed_port == port
            and parsed.path == ""
            and parsed.query == ""
            and parsed.fragment == ""
            and parsed.username is None
            and parsed.password is None
            and origin == expected_origin
        )
        with self._lock:
            valid = (
                not self.closed
                and not self.expired()
                and origin_shape_is_exact
                and _constant_time_equal(csrf, self.csrf_token)
            )
        if not valid:
            self.terminate()
            return False
        return True
