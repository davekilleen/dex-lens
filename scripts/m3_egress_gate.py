#!/usr/bin/env python3
"""Formal M3 packet/DNS/proxy evidence gate.

Exit 2 means the required OS capability was unavailable, so the gate is not
proven.  CI runs this only inside a disposable Docker ``--network none``
namespace containing synthetic fixtures and no repository credentials.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.egress.network_harness import (  # noqa: E402
    assert_evidence,
    capability_json,
    capability_probe,
    run_namespace_journey,
    temporary_artifact,
)

_SAFE_SCALAR_FIELDS = {
    "loopback_enabled",
    "journey_complete",
    "pages_checked",
    "packet_count",
    "capture_ready",
    "capture_clean_exit",
    "capture_timed_out",
    "capture_reported_error",
}
_COUNTED_FIELDS = {
    "non_loopback_packets",
    "unparsed_packets",
    "dns_packets",
    "proxy_requests",
    "application_canary_leaks",
    "pcap_canary_leaks",
}


def _sanitize_evidence(evidence: dict[str, Any] | None) -> dict[str, Any]:
    source = evidence or {}
    safe = {
        key: value
        for key in _SAFE_SCALAR_FIELDS
        if isinstance((value := source.get(key)), (bool, int))
    }
    interfaces = source.get("interfaces", [])
    safe["interfaces"] = (
        ["lo"] if isinstance(interfaces, list) and interfaces == ["lo"] else ["other"]
    )
    safe["journey_error_present"] = bool(source.get("journey_error"))
    for key in _COUNTED_FIELDS:
        value = source.get(key, [])
        safe[f"{key}_count"] = len(value) if isinstance(value, list) else -1
    return safe


def _output_directory() -> Path | None:
    raw = os.environ.get("M3_EGRESS_ARTIFACT_DIR")
    if not raw:
        return None
    destination = Path(raw)
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def _write_summary(
    destination: Path | None,
    *,
    status: str,
    capability: object,
    evidence: dict[str, Any] | None = None,
) -> None:
    if destination is None:
        return
    payload = {
        "status": status,
        "capability": asdict(capability),
        "evidence": _sanitize_evidence(evidence),
    }
    (destination / "evidence.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main() -> int:
    isolated = os.environ.get("M3_EGRESS_NETWORK_ISOLATED") == "1"
    destination = _output_directory()
    capability = capability_probe()
    print(f"m3-egress-capability: {capability_json(capability)}")
    if isolated and destination is None:
        print("M3 egress gate NOT PROVEN: artifact directory is required", file=sys.stderr)
        return 2
    if not capability.available:
        _write_summary(destination, status="not-proven", capability=capability)
        print(f"M3 egress gate NOT PROVEN: {capability.reason}", file=sys.stderr)
        return 2

    directory, artifact = temporary_artifact()
    evidence: dict[str, Any] | None = None
    try:
        try:
            run = run_namespace_journey(artifact)
        except (RuntimeError, subprocess.TimeoutExpired):
            _write_summary(
                destination,
                status="failed",
                capability=capability,
            )
            print("M3 egress gate FAILED: evidence child failed", file=sys.stderr)
            return 1
        evidence = run.evidence
        if evidence is None or run.returncode != 0:
            _write_summary(
                destination,
                status="failed",
                capability=capability,
                evidence=evidence,
            )
            print("M3 egress gate FAILED: evidence child failed", file=sys.stderr)
            return 1
        try:
            assert_evidence(evidence)
        except RuntimeError as exc:
            _write_summary(
                destination,
                status="failed",
                capability=capability,
                evidence=evidence,
            )
            print(f"M3 egress gate FAILED: {exc}", file=sys.stderr)
            return 1

        pcap = artifact.with_suffix(".pcap")
        if not pcap.is_file() or pcap.stat().st_size == 0:
            _write_summary(
                destination,
                status="failed",
                capability=capability,
                evidence=evidence,
            )
            print("M3 egress gate FAILED: clean pcap is missing", file=sys.stderr)
            return 1
        _write_summary(
            destination,
            status="proven",
            capability=capability,
            evidence=evidence,
        )
        if destination is not None:
            shutil.copy2(pcap, destination / "journey.pcap")
    finally:
        directory.cleanup()

    print(
        "M3 egress gate PROVEN: interfaces-disabled namespace + "
        "packet/DNS/proxy evidence"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
