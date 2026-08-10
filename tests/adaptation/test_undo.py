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
    RecoveryFailedError,
    TransactionEngine,
    UndoConflictError,
    UndoStatus,
)
from capability_exchange.jobs.contract import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
SIGNAL = "New entries are grouped under topic headings"


def completed(tmp_path: Path):
    approved = tmp_path / "approved"
    approved.mkdir()
    preview = build_preview(
        request=OperationRequest(
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
            approved_root=str(approved),
            relative_path="dex-lens-reading-list.md",
        ),
        host_id="claude-code-local",
        job_id="reading-list",
        capability_id="topic-grouping",
        content="# Skill\n",
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
    authority = ApprovalAuthority()
    issued = authority.issue(preview, now=NOW, ttl=timedelta(minutes=5))
    engine = TransactionEngine(
        state_root=tmp_path / "state",
        receipt_root=tmp_path / "receipts",
        approval_authority=authority,
        adapter_id="claude-code-local",
        adapter_version="1.0.0",
    )
    engine.execute(
        preview,
        approval_token=issued.token,
        contract=contract,
        observable_signal=SIGNAL,
        now=NOW + timedelta(seconds=1),
    )
    return engine, preview


def test_immediate_undo_restores_absent_target(tmp_path: Path) -> None:
    engine, preview = completed(tmp_path)
    result = engine.undo(preview)
    assert result.status is UndoStatus.UNDONE
    assert not Path(preview.target_path).exists()


def test_double_undo_is_idempotent(tmp_path: Path) -> None:
    engine, preview = completed(tmp_path)
    assert engine.undo(preview).status is UndoStatus.UNDONE
    assert engine.undo(preview).status is UndoStatus.ALREADY_UNDONE


def test_undo_conflict_preserves_unrelated_work_and_hard_stops(tmp_path: Path) -> None:
    engine, preview = completed(tmp_path)
    Path(preview.target_path).write_text("later unrelated work", encoding="utf-8")
    with pytest.raises(UndoConflictError):
        engine.undo(preview)
    assert Path(preview.target_path).read_text(encoding="utf-8") == "later unrelated work"
    assert engine.hard_stopped
    assert engine.incidents[-1].kind is IncidentKind.TRANSACTION_CONFLICT


def test_missing_recovery_manifest_triggers_recovery_failed(tmp_path: Path) -> None:
    engine, preview = completed(tmp_path)
    for path in (tmp_path / "state" / "recovery").glob("recovery-*.json"):
        path.unlink()
    with pytest.raises(RecoveryFailedError):
        engine.undo(preview)
    assert Path(preview.target_path).exists()
    assert engine.hard_stopped
    assert engine.incidents[-1].kind is IncidentKind.RECOVERY_FAILED
