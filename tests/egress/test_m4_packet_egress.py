"""M4 default-path egress proof for the full stage 1-8 local journey.

The privileged packet/DNS/proxy runner is reused for the OS-level network-none
proof.  The adaptation leg is also exercised at the domain boundary so a local
transaction cannot accidentally acquire a socket while rendering its preview,
receipt, verification, or undo pages.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from tests.concierge.test_adaptation_journey import _journey, _select
from tests.egress.network_harness import (
    assert_evidence,
    capability_probe,
    run_namespace_journey,
    temporary_artifact,
)
from tests.fixtures.hostile.catalog import derivations_of

from capability_exchange.concierge.views import render_journey


def test_m4_stage_7_8_journey_has_no_socket_or_canary_egress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    canary = "M4-private-canary-not-on-the-wire-001"
    journey = _journey(tmp_path)
    _select(journey)
    pages = [render_journey(journey, csrf_token="csrf")]
    journey.preview_adaptation()
    pages.append(render_journey(journey, csrf_token="csrf"))
    journey.approve_adaptation()
    pages.append(render_journey(journey, csrf_token="csrf"))

    destinations: list[object] = []
    original_connect = socket.socket.connect

    def loopback_only(sock: socket.socket, address: object) -> object:
        destinations.append(address)
        assert isinstance(address, tuple)
        assert address[0] in {"127.0.0.1", "::1"}, address
        return original_connect(sock, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    result = journey.apply_adaptation()
    pages.append(render_journey(journey, csrf_token="csrf"))
    journey.verify_adaptation()
    pages.append(render_journey(journey, csrf_token="csrf"))
    journey.undo_adaptation()
    pages.append(render_journey(journey, csrf_token="csrf"))

    joined = "\n".join(pages)
    assert destinations == []
    assert canary not in joined
    assert all(derived not in joined for derived in derivations_of(canary))
    assert result.receipt_path.exists()


def test_m4_packet_dns_proxy_harness_is_network_none() -> None:
    capability = capability_probe()
    if not capability.available:
        pytest.skip(f"M4 OS egress evidence unavailable: {capability.reason}")
    directory, artifact = temporary_artifact()
    try:
        run = run_namespace_journey(artifact)
        assert run.returncode == 0, run.stderr
        assert run.evidence is not None
        assert_evidence(run.evidence)
        assert run.evidence.get("proxy_requests") == []
        assert run.evidence.get("dns_packets") == []
    finally:
        directory.cleanup()
