"""R3 local concierge security invariants."""

from __future__ import annotations

import http.client
import tempfile
import threading
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from capability_exchange.adapter import AdapterResultEnvelope, InstrumentHealth, ProbeResult
from capability_exchange.concierge.security import (
    COOKIE_METADATA,
    ConciergeSessionState,
    SessionSecurity,
    ensure_loopback_bind_address,
)
from capability_exchange.concierge.server import (
    ConciergeServer,
    ConciergeSession,
    new_session,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState


def _envelope() -> AdapterResultEnvelope:
    now = datetime.now(UTC)
    return AdapterResultEnvelope(
        adapter_id="claude-code-local",
        contract_version="0.1.0",
        collected_at=now,
        probes=(
            ProbeResult(
                probe_id="test-probe",
                health=InstrumentHealth.HEALTHY,
                evidence=(
                    EvidenceItem(
                        state=EvidenceState.OBSERVED,
                        captured_at=now,
                        reference="file:test",
                    ),
                ),
            ),
        ),
    )


class _Running(AbstractContextManager["_Running"]):
    def __init__(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name) / "scope"
        root.mkdir()
        self.session = new_session(approved_roots=(root,), collector=_envelope)
        self.server = ConciergeServer(("127.0.0.1", 0), self.session)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.cookie = ""

    def __enter__(self) -> _Running:
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tempdir.cleanup()

    def request(
        self, path: str, *, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], str]:
        request_headers = {"Host": f"127.0.0.1:{self.server.server_port}"}
        if self.cookie:
            request_headers["Cookie"] = self.cookie
        if headers:
            request_headers.update(headers)
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("GET", path, headers=request_headers)
        response = conn.getresponse()
        body = response.read().decode()
        result_headers = {key.lower(): value for key, value in response.getheaders()}
        if "set-cookie" in result_headers:
            self.cookie = result_headers["set-cookie"].split(";", 1)[0]
        conn.close()
        return response.status, result_headers, body


def test_loopback_constructor_guard_is_exact() -> None:
    ensure_loopback_bind_address(("127.0.0.1", 0))
    with pytest.raises(ValueError, match="loopback"):
        ensure_loopback_bind_address(("localhost", 0))
    with pytest.raises(ValueError, match="loopback"):
        ensure_loopback_bind_address(("0.0.0.0", 0))
    with pytest.raises(ValueError, match="loopback"):
        ensure_loopback_bind_address(("::1", 0))


def test_bootstrap_token_is_atomic_under_concurrent_replay() -> None:
    security = SessionSecurity(
        bootstrap_token="bootstrap",
        session_token="session",
        csrf_token="csrf",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def consume() -> None:
        barrier.wait()
        results.append(security.consume_bootstrap("bootstrap"))

    threads = [threading.Thread(target=consume) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    assert results.count(False) == 7


def test_security_failures_terminate_and_discard() -> None:
    security = SessionSecurity(
        bootstrap_token="bootstrap",
        session_token="session",
        csrf_token="csrf",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert security.validate_host("example.test:1234", 1234) is False
    assert security.closed
    assert security.bootstrap_token == ""
    assert security.session_token == ""
    assert security.csrf_token == ""


def test_session_inventory_state_digests_secrets_and_carries_browser_metadata() -> None:
    """Only non-secret session references cross the typed G2 boundary."""
    security = SessionSecurity(
        bootstrap_token="bootstrap",
        session_token="session-secret",
        csrf_token="csrf-secret",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    builder = getattr(security, "inventory_state", None)
    assert callable(builder), "SessionSecurity must expose an inventoried state view"

    state = builder(
        approved_scope_references=("scope:sha256:approved",),
        journey_state="permission",
    )

    assert state.session_token_digest != "session-secret"
    assert state.csrf_token_digest != "csrf-secret"
    assert state.approved_scope_references == ("scope:sha256:approved",)
    assert state.journey_state == "permission"
    assert state.cookie_metadata
    assert "session-secret" not in state.model_dump_json()
    assert "csrf-secret" not in state.model_dump_json()


def test_session_inventory_state_rejects_raw_scope_paths_on_bypass_routes() -> None:
    """The typed G2 view cannot smuggle a local path via Pydantic shortcuts."""
    values = {
        "session_token_digest": "a" * 64,
        "csrf_token_digest": "b" * 64,
        "cookie_metadata": COOKIE_METADATA,
        "approved_scope_references": ("scope:/home/dave/private",),
        "expires_at": datetime.now(UTC) + timedelta(minutes=1),
        "journey_state": "permission",
    }
    with pytest.raises(ValueError, match="scope"):
        ConciergeSessionState.model_validate(values)
    with pytest.raises(ValueError, match="scope"):
        ConciergeSessionState.model_construct(**values)
    valid = ConciergeSessionState.model_validate(
        {**values, "approved_scope_references": ("scope:sha256:approved",)}
    )
    with pytest.raises(ValueError, match="scope"):
        valid.model_copy(update={"approved_scope_references": ("scope:/tmp/raw",)})


def test_session_expiry_automatically_discards_state(tmp_path: Path) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    session = ConciergeSession(
        approved_roots=(root,),
        collector=_envelope,
        expires_at=datetime.now(UTC) + timedelta(milliseconds=40),
    )
    state_dir = Path(session.tempdir.name)  # type: ignore[union-attr]

    deadline = time.monotonic() + 2
    while (
        (not session.closed or session.tempdir is not None)
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)

    assert session.closed
    assert session.tempdir is None
    assert not state_dir.exists()


def test_session_state_is_allocated_outside_even_a_temp_root() -> None:
    approved = Path(tempfile.gettempdir()).resolve()
    session = new_session(approved_roots=(approved,), collector=_envelope)
    try:
        state_dir = Path(session.tempdir.name).resolve()  # type: ignore[union-attr]
        assert not state_dir.is_relative_to(approved)
    finally:
        session.terminate()


def test_replaced_root_is_refused_before_the_first_read(tmp_path: Path) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    calls = 0

    def collector() -> AdapterResultEnvelope:
        nonlocal calls
        calls += 1
        return _envelope()

    session = new_session(approved_roots=(root,), collector=collector)
    root.rename(tmp_path / "old-scope")
    root.mkdir()

    with pytest.raises(ValueError, match="scope"):
        session.approve_scope_and_collect()

    assert session.closed
    assert calls == 0


def test_root_replaced_after_approval_transition_is_still_never_read(
    tmp_path: Path,
) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    calls = 0

    def collector() -> AdapterResultEnvelope:
        nonlocal calls
        calls += 1
        return _envelope()

    session = new_session(approved_roots=(root,), collector=collector)
    session._begin_collection()
    root.rename(tmp_path / "consented-scope")
    root.mkdir()

    with pytest.raises(ValueError, match="scope"):
        session._finish_collection()

    assert session.closed
    assert calls == 0


def test_security_headers_and_hostile_deep_link_terminate() -> None:
    with _Running() as running:
        status, headers, _ = running.request(f"/?token={running.session.bootstrap_token}")
        assert status == 303
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cache-control"] == "no-store"
        assert "default-src 'none'" in headers["content-security-policy"]
        status, headers, _ = running.request("/session")
        assert status == 200
        # A real browser otherwise serializes native same-origin form POSTs
        # with ``Origin: null``, which the exact-origin CSRF gate must reject.
        assert headers["referrer-policy"] == "same-origin"
        status, _, _ = running.request(f"/anything?token={running.session.bootstrap_token}")
        assert status == 403
        assert running.session.closed


def test_websocket_upgrade_is_rejected_before_any_session_use() -> None:
    with _Running() as running:
        status, _, _ = running.request(
            f"/?token={running.session.bootstrap_token}",
            headers={"Upgrade": "websocket", "Connection": "Upgrade"},
        )
        assert status == 403
        assert running.session.closed
