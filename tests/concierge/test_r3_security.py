"""R3 local concierge security invariants."""

from __future__ import annotations

import http.client
import tempfile
import threading
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from capability_exchange.adapter import AdapterResultEnvelope, InstrumentHealth, ProbeResult
from capability_exchange.concierge.security import (
    SessionSecurity,
    ensure_loopback_bind_address,
)
from capability_exchange.concierge.server import ConciergeServer, new_session
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


def test_security_headers_and_hostile_deep_link_terminate() -> None:
    with _Running() as running:
        status, headers, _ = running.request(f"/?token={running.session.bootstrap_token}")
        assert status == 303
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cache-control"] == "no-store"
        assert "default-src 'none'" in headers["content-security-policy"]
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
