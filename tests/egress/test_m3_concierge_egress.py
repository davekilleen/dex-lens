"""M3 full-journey egress evidence at the local concierge boundary."""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from urllib.parse import urlencode

import pytest
from tests.adapters.claude_code.fixture_helpers import tree_digests
from tests.concierge.test_local_server import RunningServer
from tests.egress.harness import EGRESS_CANARIES, build_canary_system
from tests.fixtures.hostile.catalog import assert_no_canary_leak

from capability_exchange.adapter import AdapterResultEnvelope
from capability_exchange.adapters.claude_code.containment import contained_inspection


def test_full_read_only_journey_has_only_loopback_parent_traffic_and_no_leak(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = build_canary_system(tmp_path / "fixture")
    before = tree_digests(root)

    def collect(cancel_event: threading.Event) -> AdapterResultEnvelope:
        return contained_inspection([str(root)], cancel_event=cancel_event).envelope

    with RunningServer(collect, approved_root=root) as running:
        original_connect = socket.socket.connect
        destinations: list[object] = []

        def loopback_only(sock: socket.socket, address: object) -> object:
            destinations.append(address)
            assert isinstance(address, tuple)
            assert address[0] == "127.0.0.1", address
            return original_connect(sock, address)  # type: ignore[arg-type]

        monkeypatch.setattr(socket.socket, "connect", loopback_only)

        pages = [running.bootstrap()]
        status, _, body = running.post("/approve")
        assert status == 200
        pages.append(body)
        for job_id in running.session.journey.job_ids:
            status, _, body = running.post(
                "/jobs/confirm",
                body=urlencode(
                    {
                        "job_id": job_id,
                        "success_evidence": "the confirmed outcome is available",
                        "privacy_limits": "stay inside the approved root",
                        "approval_limits": "ask before external action",
                        "autonomy_limits": "do not change files",
                        "importance": "medium",
                        "cadence": "weekly",
                    }
                ),
            )
            assert status == 200
            pages.append(body)
        status, _, body = running.post("/diagnose")
        assert status == 200
        pages.append(body)

        joined = "\n".join(pages)
        assert destinations
        assert_no_canary_leak(joined, EGRESS_CANARIES, context="M3 browser pages")
        lowered = joined.lower()
        for forbidden in (
            "https://",
            "<script",
            "<iframe",
            "<img",
            "fetch(",
            "websocket",
            "localstorage",
            "sessionstorage",
            "analytics",
        ):
            assert forbidden not in lowered

    assert tree_digests(root) == before
