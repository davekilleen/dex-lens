#!/usr/bin/env python3
"""Run and record the release-blocking exact pilot-build gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from capability_exchange.pilot.gate import (  # noqa: E402
    FormalGateEvidence,
    execute_pilot_gate,
    subprocess_gate_runner,
)
from capability_exchange.pilot.redteam import evaluate_gate_redteam  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_payload(report: object, redteam: object) -> dict[str, object]:
    """Persist only fields the inventory explicitly allows this gate to store."""
    return {
        "pilot_gate": report.dump_for_storage(),  # type: ignore[attr-defined]
        "red_team": redteam.dump_for_storage(),  # type: ignore[attr-defined]
    }


def _load_formal_evidence(
    paths: list[Path], *, commit: str
) -> tuple[FormalGateEvidence, ...]:
    formal_evidence: list[FormalGateEvidence] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or data.get("status") != "proven":
            raise ValueError(f"formal evidence is not proven: {path}")
        if data.get("commit") != commit:
            raise ValueError(f"formal evidence commit does not match exact build: {path}")
        producer = data.get("producer")
        proofs = data.get("proofs")
        test_ids = data.get("test_ids")
        if not isinstance(proofs, list) or not isinstance(test_ids, list) or not test_ids:
            raise ValueError(f"formal evidence lacks canonical proofs/test ids: {path}")
        if len(set(test_ids)) != len(test_ids):
            raise ValueError(f"formal evidence repeats a canonical test id: {path}")
        if producer == "scripts/g1_bind_mount_gate.py":
            if (
                proofs != ["formal:g1-bind-mount"]
                or test_ids != ["tests/fixtures/hostile/test_g1_bind_mount_escape.py"]
                or not __import__("re").fullmatch(
                    r"[0-9a-f]{64}", str(data.get("pytest_output_sha256", ""))
                )
                or not __import__("re").fullmatch(
                    r"[0-9a-f]{64}", str(data.get("child_report_sha256", ""))
                )
            ):
                raise ValueError("G1 formal evidence envelope is incomplete")
        elif producer == "scripts/m3_egress_gate.py":
            expected = ["formal:m3-egress", "formal:m4-egress"]
            expected_tests = [
                "tests/egress/test_m3_concierge_egress.py",
                "tests/egress/test_m4_packet_egress.py",
            ]
            if proofs != expected or test_ids != expected_tests:
                raise ValueError("M3-M4 formal evidence identities are incomplete")
            pcap = path.parent / "journey.pcap"
            if not pcap.is_file() or data.get("pcap_sha256") != _sha256(pcap):
                raise ValueError("M3-M4 formal evidence pcap hash is invalid")
            observed = data.get("evidence") or {}
            for key in ("journey_complete", "adaptation_refused"):
                if observed.get(key) is not True:
                    raise ValueError(f"M3-M4 formal evidence is missing {key}")
        elif producer == "scripts/m5_egress_gate.py":
            expected_tests = [
                "tests/concierge/test_contribution_journey.py",
                "tests/egress/test_m5_contribution_egress.py",
            ]
            if (
                proofs != ["formal:m5-egress"]
                or test_ids != expected_tests
                or not __import__("re").fullmatch(
                    r"[0-9a-f]{64}", str(data.get("pytest_output_sha256", ""))
                )
            ):
                raise ValueError("M5 formal evidence envelope is incomplete")
        else:
            raise ValueError(f"untrusted formal evidence producer: {producer!r}")
        artifact_hash = _sha256(path)
        formal_evidence.extend(
            FormalGateEvidence(
                evidence_id=proof,
                commit=commit,
                producer=producer,
                status="proven",
                artifact_sha256=artifact_hash,
                test_ids=tuple(test_ids),
            )
            for proof in proofs
        )
    expected_proofs = {
        "formal:g1-bind-mount",
        "formal:m3-egress",
        "formal:m4-egress",
        "formal:m5-egress",
    }
    actual_proofs = [item.evidence_id for item in formal_evidence]
    if len(actual_proofs) != len(set(actual_proofs)) or set(actual_proofs) != expected_proofs:
        raise ValueError("formal evidence must provide every proof identity exactly once")
    return tuple(formal_evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--formal-evidence", type=Path, action="append", required=True)
    args = parser.parse_args()
    live = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    if live != args.commit:
        raise ValueError("--commit does not match live git HEAD")
    formal_evidence = _load_formal_evidence(args.formal_evidence, commit=args.commit)
    report = execute_pilot_gate(
        commit=args.commit,
        observed_at=datetime.now(UTC),
        runner=subprocess_gate_runner,
        formal_evidence=formal_evidence,
    )
    redteam = evaluate_gate_redteam(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            _artifact_payload(report, redteam),
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(report.explanation)
    print(f"evidence: {args.output}")
    return 0 if report.pilot_start_allowed and redteam.pilot_start_allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
