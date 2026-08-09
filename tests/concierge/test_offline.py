"""The M3 diagnosis journey remains useful with no external connection."""

from __future__ import annotations

import socket
from urllib.parse import urlencode

import pytest
from tests.concierge.test_local_server import RunningServer, envelope


def test_full_journey_completes_with_external_connections_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_connect = socket.socket.connect

    def refuse_external(sock: socket.socket, address: object) -> object:
        assert isinstance(address, tuple)
        if address[0] != "127.0.0.1":
            raise OSError("external network disabled for offline M3 test")
        return original_connect(sock, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", refuse_external)
    with RunningServer(envelope) as running:
        permission = running.bootstrap()
        assert "No catalog is available or required" in permission
        status, _, _ = running.post("/approve")
        assert status == 200
        for job_id in running.session.journey.job_ids:
            status, _, _ = running.post(
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
        status, _, body = running.post("/diagnose")
        assert status == 200
        assert "Capability Map" in body
