#!/usr/bin/env python3
"""Formal M3 packet/DNS/proxy egress gate.

Exit 2 means the OS capability was not available and therefore the gate is
*not proven*.  This is intentionally different from pytest's developer-facing
skip.  Run in the disposable Linux network-disabled container from CI; the
child sees synthetic fixture data only.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

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


def persist_artifacts(artifact: Path, output_dir: str | None) -> None:
    """Copy sanitized evidence before the temporary run directory is removed."""

    if not output_dir:
        return
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(artifact, destination / "evidence.json")
    pcap = artifact.with_suffix(".pcap")
    if pcap.is_file():
        shutil.copy2(pcap, destination / "journey.pcap")


def main() -> int:
    capability = capability_probe()
    print(f"m3-egress-capability: {capability_json(capability)}")
    if not capability.available:
        print(f"M3 egress gate NOT PROVEN: {capability.reason}", file=sys.stderr)
        return 2
    directory, artifact = temporary_artifact()
    try:
        run = run_namespace_journey(artifact)
        if run.evidence is None:
            print(run.stderr or "namespace evidence child failed", file=sys.stderr)
            return 1
        if run.returncode != 0:
            print(run.stderr or "namespace evidence child failed", file=sys.stderr)
            return 1
        assert_evidence(run.evidence)
        # Persist only a proven-clean pcap; a failed capture must not export
        # the synthetic canary bytes it is designed to detect.
        persist_artifacts(artifact, os.environ.get("M3_EGRESS_ARTIFACT_DIR"))
    except (AssertionError, RuntimeError) as exc:
        print(f"M3 egress gate FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        directory.cleanup()
    print("M3 egress gate PROVEN: interfaces-disabled namespace + packet/DNS/proxy evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
