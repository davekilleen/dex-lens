#!/usr/bin/env python3
"""Privileged CI gate for the G1 bind-mount hostile fixture.

The ordinary matrix deliberately skips this fixture when the host cannot
create a mount namespace.  This gate runs the same module in a disposable
Linux container with only ``CAP_SYS_ADMIN`` and refuses to call a skip or a
partial child report proof.  The resulting JSON is sanitized fixture evidence
for the CI artifact, not a claim that an unprivileged local host executed it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "hostile" / "test_g1_bind_mount_escape.py"
_UNPROVEN = re.compile(
    r"\b(?:skip|skipped|skipping|unproven|not[ -]proven|xfailed|xpassed|deselected)\b|"
    r"\b(?:0|no) tests? (?:collected|ran|run)\b",
    re.IGNORECASE,
)


class GateFailure(RuntimeError):
    """The bind-mount proof was skipped, incomplete, or did not pass."""


def _json_report(report_path: Path) -> dict[str, Any]:
    if not report_path.is_file():
        raise GateFailure(f"missing child report: {report_path}")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateFailure(f"missing child report or invalid JSON: {type(exc).__name__}") from exc
    if not isinstance(report, dict):
        raise GateFailure("child report is not a JSON object")
    return report


def _assert_report(report: dict[str, Any]) -> None:
    escape = report.get("escape")
    if not isinstance(escape, dict):
        raise GateFailure("containment assertion missing escape report")
    required_escape = (
        "canary_readable_through_mount",
        "decoy_hidden_by_mount",
        "same_device_as_approved_root",
        "ismount_says_no",
        "realpath_stays_inside_root",
    )
    if any(escape.get(key) is not True for key in required_escape):
        raise GateFailure("containment assertion did not reproduce the bind-mount escape")

    for decision_name in ("dir_decision", "key_decision"):
        decision = report.get(decision_name)
        if not isinstance(decision, dict):
            raise GateFailure(f"containment assertion missing {decision_name}")
        if decision.get("verdict") != "blocked" or decision.get("reason") != "mount-point-crossing":
            raise GateFailure(f"containment assertion failed for {decision_name}")
    if not report.get("mount_points_inside_scope"):
        raise GateFailure("containment assertion recorded no mount point")
    exclusions = report.get("exclusion_reasons")
    if not isinstance(exclusions, list) or "mount-point-crossing" not in exclusions:
        raise GateFailure("containment assertion has no mount-point-crossing exclusion")

    admitted = report.get("admitted_relative_paths", ())
    snapshotted = report.get("snapshot_relative_paths", ())
    if any("vendor-cache" in str(path) for path in (*admitted, *snapshotted)):
        raise GateFailure("containment assertion admitted bytes behind the bind mount")
    if (
        report.get("canary_in_snapshot") is not False
        or report.get("canary_in_envelope") is not False
    ):
        raise GateFailure("containment assertion leaked the bind-mount canary")


def validate_gate_evidence(*, returncode: int, output: str, report_path: Path) -> dict[str, Any]:
    """Validate pytest output and the child JSON report, failing closed."""
    if returncode != 0:
        raise GateFailure(f"bind-mount hostile module failed (exit {returncode})")
    if _UNPROVEN.search(output):
        raise GateFailure("bind-mount hostile fixture was skipped or unproven")
    report = _json_report(report_path)
    _assert_report(report)
    return report


def _write_evidence(destination: Path | None, payload: dict[str, Any]) -> None:
    if destination is None:
        return
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "g1-bind-mount-gate.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _envelope(
    *, status: str, commit: str, output: str, report_path: Path, report: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "commit": commit,
        "producer": "scripts/g1_bind_mount_gate.py",
        "proofs": ["formal:g1-bind-mount"],
        "test_ids": [str(FIXTURE.relative_to(REPO_ROOT))],
        "pytest_output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "child_report_sha256": _sha256(report_path) if report_path.is_file() else None,
        "report": report,
    }


def main() -> int:
    configured = os.environ.get("G1_BIND_MOUNT_EVIDENCE_DIR")
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if configured:
        evidence_dir = Path(configured)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="g1-bind-mount-gate-")
        evidence_dir = Path(temporary.name)
    report_path = evidence_dir / "bind-mount-child-report.json"
    commit = os.environ.get("DEX_LENS_BUILD_COMMIT", "")
    if configured and not re.fullmatch(r"[0-9a-f]{40}", commit):
        _write_evidence(
            evidence_dir,
            _envelope(
                status="not-proven",
                commit=commit or "missing",
                output="missing exact build commit",
                report_path=report_path,
                report=None,
            ),
        )
        print("G1 bind-mount gate NOT PROVEN: exact build commit is required", file=sys.stderr)
        return 2
    environment = os.environ.copy()
    environment.update(
        {
            "G1_BIND_MOUNT_REPORT": str(report_path),
            # The CI image owns CAP_SYS_ADMIN directly; ordinary hosts retain
            # the fixture's unshare probe and loudly skip when it is unavailable.
            "G1_BIND_MOUNT_DIRECT": "1",
            "PYTHONPATH": os.pathsep.join(
                (str(REPO_ROOT / "src"), str(REPO_ROOT), os.environ.get("PYTHONPATH", ""))
            ),
        }
    )
    completed = subprocess.run(  # noqa: S603 - fixed pytest argv, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rs",
            "-p",
            "no:cacheprovider",
            str(FIXTURE),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    try:
        report = validate_gate_evidence(
            returncode=completed.returncode,
            output=output,
            report_path=report_path,
        )
    except GateFailure as exc:
        _write_evidence(
            evidence_dir if configured else None,
            _envelope(
                status="failed",
                commit=commit,
                output=output,
                report_path=report_path,
                report=None,
            ),
        )
        print(f"G1 bind-mount gate FAILED: {exc}", file=sys.stderr)
        if temporary is not None:
            temporary.cleanup()
        return 1
    _write_evidence(
        evidence_dir if configured else None,
        _envelope(
            status="proven",
            commit=commit,
            output=output,
            report_path=report_path,
            report=report,
        ),
    )
    print("G1 bind-mount gate PROVEN: privileged fixture + containment report")
    if temporary is not None:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
