from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.approval import ApprovalAuthority
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.incidents import IncidentKind
from capability_exchange.adaptation.preview import build_preview
from capability_exchange.adaptation.receipt import read_receipt
from capability_exchange.adaptation.transaction import (
    AutomationHardStoppedError,
    TransactionEngine,
)
from capability_exchange.adaptation.verification import VerificationVerdict
from capability_exchange.jobs.contract import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
SIGNAL = "New entries are grouped under topic headings"


def make_contract() -> SuccessContract:
    return SuccessContract(
        job_id="reading-list",
        situation="When I save useful articles during the week",
        desired_outcome="My local reading list is grouped by topic",
        success_evidence=(SIGNAL,),
        boundaries=JobBoundaries(
            privacy_limits=("No article text leaves this machine",),
            approval_limits=("Ask before changing my Claude Code setup",),
            autonomy_limits=("Never send or publish the reading list",),
        ),
        importance=JobImportance.MEDIUM,
        cadence=JobCadence.WEEKLY,
        confirmed_at=NOW,
    )


def make_preview(root: Path, *, job_id: str = "reading-list"):
    return build_preview(
        request=OperationRequest(
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
            approved_root=str(root),
            relative_path=f"dex-lens-{job_id}.md",
        ),
        host_id="claude-code-local",
        job_id=job_id,
        capability_id="topic-grouping",
        content="# Skill\n\nGroup new reading-list entries under topic headings.\n",
        expected_benefit="Group reading-list entries by topic",
        created_at=NOW,
    )


def execute(engine: TransactionEngine, authority: ApprovalAuthority, preview):
    issued = authority.issue(preview, now=NOW, ttl=timedelta(minutes=5))
    return engine.execute(
        preview,
        approval_token=issued.token,
        contract=make_contract(),
        observable_signal=SIGNAL,
        now=NOW + timedelta(seconds=1),
    )


def test_successful_transaction_is_applied_receipted_and_verified(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    authority = ApprovalAuthority()
    engine = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=authority,
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
    )
    preview = make_preview(approved)

    result = execute(engine, authority, preview)

    assert Path(preview.target_path).read_text(encoding="utf-8") == preview.content
    assert result.verification is not None
    assert result.verification.verdict is VerificationVerdict.WORKING
    assert result.hard_stopped is False
    receipt = read_receipt(result.receipt_path)
    assert receipt.preview_digest == preview.preview_digest
    assert receipt.verification_verdict is VerificationVerdict.WORKING


def test_replaying_completed_transaction_has_one_effect_and_one_receipt(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    authority = ApprovalAuthority()
    engine = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=authority,
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
    )
    preview = make_preview(approved)
    first = execute(engine, authority, preview)

    second = engine.execute(
        preview,
        approval_token="already-consumed-and-ignored-for-complete-transaction",
        contract=make_contract(),
        observable_signal=SIGNAL,
        now=NOW + timedelta(seconds=2),
    )

    assert second.receipt_path == first.receipt_path
    assert len(list((tmp_path / "receipts").glob("receipt-*.json"))) == 1
    assert Path(preview.target_path).read_text(encoding="utf-8") == preview.content


def test_unknown_verification_hard_stops_later_automation(
    tmp_path: Path, monkeypatch
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    authority = ApprovalAuthority()
    engine = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=authority,
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
    )
    preview = make_preview(approved)

    original_read = Path.read_bytes

    def sabotage_target(self: Path) -> bytes:
        if self == Path(preview.target_path):
            raise OSError("verification unavailable")
        return original_read(self)

    monkeypatch.setattr(Path, "read_bytes", sabotage_target)
    result = execute(engine, authority, preview)
    assert result.verification is not None
    assert result.verification.verdict is VerificationVerdict.UNKNOWN
    assert result.hard_stopped
    assert engine.incidents[-1].kind is IncidentKind.UNVERIFIED

    other = make_preview(approved, job_id="weekly-planning")
    issued = authority.issue(other, now=NOW, ttl=timedelta(minutes=5))
    with pytest.raises(AutomationHardStoppedError):
        engine.execute(
            other,
            approval_token=issued.token,
            contract=make_contract(),
            observable_signal=SIGNAL,
            now=NOW + timedelta(seconds=2),
        )
