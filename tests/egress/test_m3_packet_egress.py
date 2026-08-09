"""M3 packet/DNS/proxy evidence test.

The test is visibly skipped on an unprivileged developer host.  The formal
release job invokes ``scripts/m3_egress_gate.py`` and turns the same capability
absence into a hard failure, so a missing packet proof can never go unnoticed.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from tests.egress.network_harness import (
    assert_evidence,
    capability_probe,
    run_namespace_journey,
    temporary_artifact,
)


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


def test_formal_gate_persists_sanitized_artifacts(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "m3_egress_gate", Path("scripts/m3_egress_gate.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "evidence.json"
    source.write_text('{"packet_count": 1}')
    source.with_suffix(".pcap").write_bytes(b"pcap")
    destination = tmp_path / "out"
    module.persist_artifacts(source, str(destination))
    assert (destination / "evidence.json").read_text() == source.read_text()
    assert (destination / "journey.pcap").read_bytes() == b"pcap"


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
