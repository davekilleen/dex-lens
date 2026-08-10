from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_exchange.adaptation.receipt import (
    TransactionReceipt,
    read_receipt,
    write_receipt,
)
from capability_exchange.boundary.deletion import run_deletion_path

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
CANARY = "CANARY-private-source-must-not-enter-receipt"


def make_receipt(**overrides: object) -> TransactionReceipt:
    values: dict[str, object] = {
        "transaction_id": "a" * 32,
        "preview_digest": "b" * 64,
        "approval_id": "c" * 24,
        "approval_issued_at": NOW,
        "operation": "create-namespaced-skill",
        "target_path": "/tmp/approved/skills/dex-lens-reading-list/SKILL.md",
        "content_sha256": "d" * 64,
        "adapter_id": "claude-code-local",
        "adapter_version": "1.0.0",
        "recovery_manifest_path": "/tmp/state/recovery.json",
        "applied_at": NOW,
        "verification_verdict": "working",
        "evidence_level": "verified",
        "verification_procedure_id": "create-namespaced-skill-loadability-v1",
        "verification_evidence_reference": "evidence://synthetic/outcome",
        "verification_evidence_sha256": "e" * 64,
        "verification_contract_digest": "f" * 64,
        "verification_observed_at": NOW,
    }
    values.update(overrides)
    return TransactionReceipt(**values)


def test_receipt_is_standard_user_readable_json(tmp_path: Path) -> None:
    receipt = make_receipt()
    path = write_receipt(receipt, tmp_path)

    # Proves readability without importing Dex Lens: plain JSON survives uninstall.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["transaction_id"] == receipt.transaction_id
    assert payload["verification_verdict"] == "working"
    assert payload["approval_issued_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert payload["verification_evidence_sha256"] == "e" * 64
    assert read_receipt(path) == receipt


def test_private_source_values_are_unrepresentable_in_receipt() -> None:
    with pytest.raises(ValidationError):
        make_receipt(raw_source=CANARY)
    assert CANARY not in make_receipt().model_dump_json()


def test_receipt_refuses_naive_approval_time() -> None:
    with pytest.raises(ValidationError, match="approval_issued_at"):
        make_receipt(approval_issued_at=datetime(2026, 8, 10, 9, 0))


def test_receipt_write_refuses_overwrite(tmp_path: Path) -> None:
    receipt = make_receipt()
    path = write_receipt(receipt, tmp_path)
    with pytest.raises(FileExistsError):
        write_receipt(receipt, tmp_path)
    assert read_receipt(path) == receipt


def test_registered_deletion_removes_receipt_bytes(tmp_path: Path) -> None:
    path = write_receipt(make_receipt(), tmp_path)
    removed = run_deletion_path("delete-adaptation-receipts", tmp_path)
    assert path in removed
    assert not path.exists()
