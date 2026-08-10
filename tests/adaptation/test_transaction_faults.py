from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.approval import ApprovalAuthority
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.incidents import IncidentKind
from capability_exchange.adaptation.preview import build_preview
from capability_exchange.adaptation.transaction import (
    InjectedCrash,
    TransactionConflictError,
    TransactionEngine,
    TransactionFailedError,
)
from capability_exchange.jobs.contract import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
SIGNAL = "New entries are grouped under topic headings"


def fixture(root: Path):
    preview = build_preview(
        request=OperationRequest(
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
            approved_root=str(root),
            relative_path="dex-lens-reading-list.md",
        ),
        host_id="claude-code-local",
        job_id="reading-list",
        capability_id="topic-grouping",
        content="# Skill\n\nGroup new reading-list entries under topic headings.\n",
        expected_benefit="Group reading-list entries by topic",
        created_at=NOW,
    )
    contract = SuccessContract(
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
    return preview, contract


class CrashAt:
    def __init__(self, checkpoint: str) -> None:
        self.checkpoint = checkpoint
        self.triggered = False

    def __call__(self, checkpoint: str) -> None:
        if checkpoint == self.checkpoint and not self.triggered:
            self.triggered = True
            raise InjectedCrash(checkpoint)


@pytest.mark.parametrize(
    "checkpoint",
    ["before-recovery", "mid-write", "before-commit", "after-commit-before-receipt"],
)
def test_restart_resolves_every_fault_to_prestate_or_complete_receipt(
    tmp_path: Path, checkpoint: str
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    preview, contract = fixture(approved)
    authority = ApprovalAuthority()
    issued = authority.issue(preview, now=NOW, ttl=timedelta(minutes=5))
    crashing = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=authority,
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
        fault_hook=CrashAt(checkpoint),
    )
    with pytest.raises(InjectedCrash):
        crashing.execute(
            preview,
            approval_token=issued.token,
            contract=contract,
            observable_signal=SIGNAL,
            now=NOW + timedelta(seconds=1),
        )

    restarted = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=ApprovalAuthority(),
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
    )
    result = restarted.execute(
        preview,
        approval_token="not-reused-on-resume",
        contract=contract,
        observable_signal=SIGNAL,
        now=NOW + timedelta(seconds=2),
    )
    assert Path(preview.target_path).read_text(encoding="utf-8") == preview.content
    assert result.receipt_path.exists()
    assert len(list((tmp_path / "receipts").glob("receipt-*.json"))) == 1


def test_receipt_failure_rolls_back_exact_applied_file(tmp_path: Path, monkeypatch) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    preview, contract = fixture(approved)
    authority = ApprovalAuthority()
    issued = authority.issue(preview, now=NOW, ttl=timedelta(minutes=5))

    def fail_receipt(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("capability_exchange.adaptation.transaction.write_receipt", fail_receipt)
    engine = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=authority,
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
    )
    with pytest.raises(TransactionFailedError, match="receipt"):
        engine.execute(
            preview,
            approval_token=issued.token,
            contract=contract,
            observable_signal=SIGNAL,
            now=NOW + timedelta(seconds=1),
        )
    assert not Path(preview.target_path).exists()
    assert engine.incidents[-1].kind is IncidentKind.RECEIPT_FAILED


def test_unrelated_bytes_after_crash_are_never_deleted_as_partial_output(
    tmp_path: Path,
) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    preview, contract = fixture(approved)
    authority = ApprovalAuthority()
    issued = authority.issue(preview, now=NOW, ttl=timedelta(minutes=5))
    engine = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=authority,
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
        fault_hook=CrashAt("mid-write"),
    )
    with pytest.raises(InjectedCrash):
        engine.execute(
            preview,
            approval_token=issued.token,
            contract=contract,
            observable_signal=SIGNAL,
            now=NOW,
        )
    Path(preview.target_path).write_text("unrelated later work", encoding="utf-8")

    restarted = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=ApprovalAuthority(),
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
    )
    with pytest.raises(TransactionConflictError):
        restarted.execute(
            preview,
            approval_token="unused",
            contract=contract,
            observable_signal=SIGNAL,
            now=NOW + timedelta(seconds=1),
        )
    assert Path(preview.target_path).read_text(encoding="utf-8") == "unrelated later work"
    assert restarted.hard_stopped
    assert restarted.incidents[-1].kind is IncidentKind.TRANSACTION_CONFLICT
