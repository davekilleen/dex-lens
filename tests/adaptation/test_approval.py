from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.approval import (
    ApprovalAuthority,
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalReplayError,
)
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.preview import build_preview

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def make_preview(root: Path, *, job_id: str = "reading-list"):
    return build_preview(
        request=OperationRequest(
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
            approved_root=str(root),
            relative_path="dex-lens-reading-list.md",
        ),
        host_id="claude-code-local",
        job_id=job_id,
        capability_id="topic-grouping",
        content="# Skill\n",
        expected_benefit="Group reading-list entries by topic",
        created_at=NOW,
    )


def test_approval_binds_exact_preview_scope_and_one_change(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    authority = ApprovalAuthority()

    issued = authority.issue(preview, now=NOW, ttl=timedelta(minutes=5))
    record = authority.consume(issued.token, preview, now=NOW + timedelta(seconds=1))

    assert record.preview_digest == preview.preview_digest
    assert record.host_id == preview.host_id
    assert record.job_id == preview.job_id
    assert record.capability_id == preview.capability_id
    assert record.target_path == preview.target_path
    assert record.limits == ("one-change", "create-only", "no-network")
    assert not hasattr(record, "token")


def test_approval_is_single_use(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    authority = ApprovalAuthority()
    issued = authority.issue(preview, now=NOW, ttl=timedelta(minutes=5))
    authority.consume(issued.token, preview, now=NOW)

    with pytest.raises(ApprovalReplayError):
        authority.consume(issued.token, preview, now=NOW)


def test_approval_expires_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    authority = ApprovalAuthority()
    issued = authority.issue(preview, now=NOW, ttl=timedelta(seconds=1))

    with pytest.raises(ApprovalExpiredError):
        authority.consume(issued.token, preview, now=NOW + timedelta(seconds=2))


def test_approval_for_one_preview_cannot_authorize_another(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    approved = make_preview(root, job_id="reading-list")
    other = make_preview(root, job_id="weekly-planning")
    authority = ApprovalAuthority()
    issued = authority.issue(approved, now=NOW, ttl=timedelta(minutes=5))

    with pytest.raises(ApprovalMismatchError):
        authority.consume(issued.token, other, now=NOW)

    # A mismatch does not consume the valid approval; the exact preview can use it once.
    assert authority.consume(issued.token, approved, now=NOW).job_id == "reading-list"


def test_unknown_token_refuses_without_leaking_registry_state(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    authority = ApprovalAuthority()
    with pytest.raises(ApprovalMismatchError, match="unknown"):
        authority.consume("not-a-real-token", preview, now=NOW)
