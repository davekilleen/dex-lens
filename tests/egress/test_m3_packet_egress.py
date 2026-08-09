"""M3 packet/DNS/proxy evidence gate tests."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
import tests.egress.namespace_probe as namespace_probe
from tests.egress.namespace_probe import (
    _capture_ready,
    _leak_markers,
    _packet_endpoints,
)
from tests.egress.network_harness import (
    assert_evidence,
    capability_probe,
    run_namespace_journey,
    temporary_artifact,
)


def _gate_module():
    spec = importlib.util.spec_from_file_location(
        "m3_egress_gate", Path("scripts/m3_egress_gate.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("formal gate module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_formal_gate_marks_unavailable_capability_as_unproven() -> None:
    capability = capability_probe()
    if capability.available:
        pytest.skip("the formal gate is runnable on this privileged host")
    result = subprocess.run(
        [sys.executable, "scripts/m3_egress_gate.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "NOT PROVEN" in result.stderr


def test_isolated_formal_gate_requires_an_artifact_directory() -> None:
    env = os.environ.copy()
    env["M3_EGRESS_NETWORK_ISOLATED"] = "1"
    env.pop("M3_EGRESS_ARTIFACT_DIR", None)
    result = subprocess.run(
        [sys.executable, "scripts/m3_egress_gate.py"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2
    assert "artifact directory is required" in result.stderr


def test_failure_summary_is_sanitized_and_always_written(tmp_path: Path) -> None:
    module = _gate_module()
    destination = tmp_path / "out"
    destination.mkdir()
    module._write_summary(
        destination,
        status="failed",
        capability=capability_probe(),
        evidence={
            "packet_count": 1,
            "proxy_requests": ["must-not-survive"],
            "raw_private_bytes": "must-not-survive",
        },
    )
    payload = json.loads((destination / "evidence.json").read_text())
    assert payload["status"] == "failed"
    assert payload["evidence"]["packet_count"] == 1
    assert payload["evidence"]["proxy_requests_count"] == 1
    assert "must-not-survive" not in json.dumps(payload)


def test_evidence_checks_cannot_be_removed_by_python_optimization() -> None:
    with pytest.raises(RuntimeError, match="interfaces|loopback"):
        assert_evidence({})


def test_packet_parser_covers_ipv4_ipv6_and_fails_unknown_lines() -> None:
    endpoints, unparsed = _packet_endpoints(
        [
            "lo In IP 127.0.0.1.123 > 127.0.0.1.456: Flags [S]",
            "lo In IP6 ::1.123 > ::1.456: Flags [S]",
            "mystery packet format",
        ]
    )
    assert endpoints == [("127.0.0.1", "127.0.0.1"), ("::1", "::1")]
    assert unparsed == ["unparsed-packet"]


def test_capture_readiness_requires_a_live_process_through_startup(monkeypatch) -> None:
    class Process:
        def __init__(self, states):
            self.states = iter(states)

        def poll(self):
            return next(self.states)

    times = iter((0.0, 0.6))
    monkeypatch.setattr("tests.egress.namespace_probe.time.monotonic", lambda: next(times))
    assert _capture_ready(Process((None, None))) is True

    times = iter((0.0, 0.1))
    monkeypatch.setattr("tests.egress.namespace_probe.time.monotonic", lambda: next(times))
    assert _capture_ready(Process((1,))) is False


def test_parent_opens_capture_stream_before_tcpdump_drops_privileges(
    tmp_path: Path, monkeypatch
) -> None:
    start_capture = getattr(namespace_probe, "_start_capture", None)
    assert start_capture is not None, "capture stream must be opened by the parent"

    observed = {}
    process = object()

    def popen(command, **kwargs):
        observed["command"] = command
        observed["stdout"] = kwargs["stdout"]
        return process

    monkeypatch.setattr(namespace_probe.subprocess, "Popen", popen)
    pcap = tmp_path / "journey.pcap"
    capture, stream = start_capture(pcap)
    try:
        assert capture is process
        assert observed["command"][-4:-2] == ["-Z", "root"]
        assert observed["command"][-2:] == ["-w", "-"]
        assert observed["stdout"] is stream
        assert pcap.is_file()
    finally:
        stream.close()


def test_encoded_and_partial_canary_forms_are_detected() -> None:
    canary = "hostile/CataLog/AwsSecretValue0000CANARY"
    partial = canary[:12]
    assert _leak_markers(f"prefix {partial} suffix".encode(), [canary])
    assert _leak_markers(base64.b64encode(canary.encode()), [canary])
    assert _leak_markers(base64.b64encode(partial.encode()), [canary])
    assert _leak_markers(quote(partial, safe="").encode(), [canary])


def test_container_gate_excludes_credentials_and_minimizes_runtime() -> None:
    ignored = Path(".dockerignore").read_text()
    workflow = Path(".github/workflows/ci.yml").read_text()
    assert ".git" in ignored
    for required in (
        "install -d -m 0777 m3-egress-artifact",
        "--network none",
        "--cap-drop=ALL",
        "--read-only",
        "no-new-privileges",
        "if-no-files-found: error",
    ):
        assert required in workflow


def test_m3_full_journey_packet_dns_proxy_evidence() -> None:
    capability = capability_probe()
    if not capability.available:
        pytest.skip(f"M3 OS egress evidence unavailable: {capability.reason}")
    directory, artifact = temporary_artifact()
    try:
        run = run_namespace_journey(artifact)
        assert run.returncode == 0, run.stderr
        assert run.evidence is not None
        assert_evidence(run.evidence)
    finally:
        directory.cleanup()
