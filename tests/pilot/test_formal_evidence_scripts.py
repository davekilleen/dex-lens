from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


def load_script(name: str) -> ModuleType:
    path = Path("scripts") / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_m5(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    returncode: int = 0,
    stdout: str = "2 passed",
    stderr: str = "",
    live_commit: str = COMMIT,
) -> tuple[int, dict[str, Any]]:
    module = load_script("m5_egress_gate")
    output = tmp_path / "m5.json"
    monkeypatch.setenv("DEX_LENS_BUILD_COMMIT", COMMIT)
    monkeypatch.setattr(sys, "argv", ["m5_egress_gate.py", "--output", str(output)])
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: live_commit)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        ),
    )
    result = module.main()
    return result, json.loads(output.read_text(encoding="utf-8"))


def test_m5_executor_emits_commit_bound_proven_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, envelope = run_m5(monkeypatch, tmp_path)
    assert result == 0
    assert envelope["status"] == "proven"
    assert envelope["commit"] == COMMIT
    assert envelope["producer"] == "scripts/m5_egress_gate.py"
    assert envelope["proofs"] == ["formal:m5-egress"]
    assert envelope["test_ids"] == [
        "tests/concierge/test_contribution_journey.py",
        "tests/egress/test_m5_contribution_egress.py",
    ]
    assert len(envelope["pytest_output_sha256"]) == 64


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (1, "1 failed"),
        (0, "1 passed, 1 skipped"),
        (0, "1 passed, 1 xpassed"),
        (0, "2 passed, 1 deselected"),
        (0, "no tests ran"),
    ],
)
def test_m5_executor_records_failure_skip_and_unproven_runs_as_not_proven(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    returncode: int,
    stdout: str,
) -> None:
    result, envelope = run_m5(
        monkeypatch,
        tmp_path,
        returncode=returncode,
        stdout=stdout,
    )
    assert result == 1
    assert envelope["status"] == "not-proven"


def test_m5_executor_rejects_a_commit_that_does_not_match_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit, match="does not match HEAD"):
        run_m5(monkeypatch, tmp_path, live_commit=OTHER_COMMIT)


def write_formal_envelopes(tmp_path: Path) -> list[Path]:
    (tmp_path / "journey.pcap").write_bytes(b"pcap")
    pcap_hash = __import__("hashlib").sha256(b"pcap").hexdigest()
    envelopes = {
        "g1.json": {
            "schema_version": 1,
            "status": "proven",
            "commit": COMMIT,
            "producer": "scripts/g1_bind_mount_gate.py",
            "proofs": ["formal:g1-bind-mount"],
            "test_ids": ["tests/fixtures/hostile/test_g1_bind_mount_escape.py"],
            "pytest_output_sha256": "1" * 64,
            "child_report_sha256": "2" * 64,
        },
        "m3.json": {
            "schema_version": 1,
            "status": "proven",
            "commit": COMMIT,
            "producer": "scripts/m3_egress_gate.py",
            "proofs": ["formal:m3-egress", "formal:m4-egress"],
            "test_ids": [
                "tests/egress/test_m3_concierge_egress.py",
                "tests/egress/test_m4_packet_egress.py",
            ],
            "pcap_sha256": pcap_hash,
            "evidence": {"journey_complete": True, "adaptation_refused": True},
        },
        "m5.json": {
            "schema_version": 1,
            "status": "proven",
            "commit": COMMIT,
            "producer": "scripts/m5_egress_gate.py",
            "proofs": ["formal:m5-egress"],
            "test_ids": [
                "tests/concierge/test_contribution_journey.py",
                "tests/egress/test_m5_contribution_egress.py",
            ],
            "pytest_output_sha256": "3" * 64,
        },
    }
    paths: list[Path] = []
    for name, envelope in envelopes.items():
        path = tmp_path / name
        path.write_text(json.dumps(envelope), encoding="utf-8")
        paths.append(path)
    return paths


def rewrite(path: Path, **changes: Any) -> None:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope.update(changes)
    path.write_text(json.dumps(envelope), encoding="utf-8")


@pytest.mark.parametrize(
    ("index", "changes", "match"),
    [
        (0, {"producer": "caller.py"}, "untrusted formal evidence producer"),
        (2, {"test_ids": ["tests/egress/test_m5_contribution_egress.py"]}, "M5 formal"),
        (2, {"pytest_output_sha256": "forged"}, "M5 formal"),
        (0, {"proofs": ["formal:g1-bind-mount", "formal:g1-bind-mount"]}, "G1 formal"),
    ],
)
def test_pilot_loader_rejects_untrusted_or_malformed_envelopes(
    tmp_path: Path,
    index: int,
    changes: dict[str, Any],
    match: str,
) -> None:
    module = load_script("pilot_gate")
    paths = write_formal_envelopes(tmp_path)
    rewrite(paths[index], **changes)
    with pytest.raises(ValueError, match=match):
        module._load_formal_evidence(paths, commit=COMMIT)


def test_pilot_loader_accepts_each_canonical_formal_identity_exactly_once(
    tmp_path: Path,
) -> None:
    module = load_script("pilot_gate")
    evidence = module._load_formal_evidence(
        write_formal_envelopes(tmp_path),
        commit=COMMIT,
    )
    assert tuple(item.evidence_id for item in evidence) == (
        "formal:g1-bind-mount",
        "formal:m3-egress",
        "formal:m4-egress",
        "formal:m5-egress",
    )


def test_g1_executor_envelope_binds_commit_fixture_output_and_child_report(
    tmp_path: Path,
) -> None:
    module = load_script("g1_bind_mount_gate")
    report = tmp_path / "child.json"
    report.write_text('{"escape":"blocked"}', encoding="utf-8")
    envelope = module._envelope(
        status="proven",
        commit=COMMIT,
        output="1 passed",
        report_path=report,
        report={"escape": "blocked"},
    )
    assert envelope["commit"] == COMMIT
    assert envelope["proofs"] == ["formal:g1-bind-mount"]
    assert envelope["test_ids"] == [
        "tests/fixtures/hostile/test_g1_bind_mount_escape.py"
    ]
    assert all(
        len(envelope[key]) == 64
        for key in ("pytest_output_sha256", "child_report_sha256")
    )


def test_m3_executor_envelope_is_m3_m4_only_and_hash_binds_pcap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_script("m3_egress_gate")
    monkeypatch.setenv("DEX_LENS_BUILD_COMMIT", COMMIT)
    module._write_summary(
        tmp_path,
        status="proven",
        capability=module.capability_probe(),
        evidence={"journey_complete": True, "adaptation_refused": True},
        pcap_sha256="4" * 64,
    )
    envelope = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert envelope["commit"] == COMMIT
    assert envelope["proofs"] == ["formal:m3-egress", "formal:m4-egress"]
    assert "formal:m5-egress" not in envelope["proofs"]
    assert envelope["pcap_sha256"] == "4" * 64
