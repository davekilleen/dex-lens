from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.preview import build_preview
from capability_exchange.adaptation.recovery import (
    RecoveryConflictError,
    RecoveryUnavailableError,
    create_recovery_point,
    restore_absent_target,
    validate_recovery_point,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def make_preview(root: Path):
    return build_preview(
        request=OperationRequest(
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
            approved_root=str(root),
            relative_path="skills/dex-lens-reading-list/SKILL.md",
        ),
        host_id="claude-code-local",
        job_id="reading-list",
        capability_id="topic-grouping",
        content="# Skill\n",
        expected_benefit="Group reading-list entries by topic",
        created_at=NOW,
    )


def test_recovery_point_is_read_back_and_validated_before_mutation(tmp_path: Path) -> None:
    target_root = tmp_path / "approved"
    state_root = tmp_path / "state"
    target_root.mkdir()
    preview = make_preview(target_root)

    point = create_recovery_point(preview, state_root=state_root, created_at=NOW)
    assert point.prior_state == "absent"
    assert point.target_path == preview.target_path
    assert point.manifest_path.endswith(".json")
    assert validate_recovery_point(Path(point.manifest_path)) == point


def test_unwritable_or_invalid_recovery_location_refuses_before_target_change(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "approved"
    target_root.mkdir()
    preview = make_preview(target_root)
    state_root = tmp_path / "state-file"
    state_root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(RecoveryUnavailableError):
        create_recovery_point(preview, state_root=state_root, created_at=NOW)
    assert not Path(preview.target_path).exists()


def test_truncated_or_tampered_recovery_manifest_is_invalid(tmp_path: Path) -> None:
    target_root = tmp_path / "approved"
    target_root.mkdir()
    preview = make_preview(target_root)
    point = create_recovery_point(preview, state_root=tmp_path / "state", created_at=NOW)
    manifest = Path(point.manifest_path)
    manifest.write_text(json.dumps({"target_path": preview.target_path}), encoding="utf-8")

    with pytest.raises(RecoveryUnavailableError):
        validate_recovery_point(manifest)


def test_restore_removes_only_the_exact_applied_bytes(tmp_path: Path) -> None:
    target_root = tmp_path / "approved"
    target_root.mkdir()
    preview = make_preview(target_root)
    point = create_recovery_point(preview, state_root=tmp_path / "state", created_at=NOW)
    target = Path(preview.target_path)
    target.parent.mkdir(parents=True)
    target.write_text(preview.content, encoding="utf-8")

    restore_absent_target(point, expected_applied_sha256=preview.content_sha256)
    assert not target.exists()


def test_restore_never_clobbers_unrelated_later_work(tmp_path: Path) -> None:
    target_root = tmp_path / "approved"
    target_root.mkdir()
    preview = make_preview(target_root)
    point = create_recovery_point(preview, state_root=tmp_path / "state", created_at=NOW)
    target = Path(preview.target_path)
    target.parent.mkdir(parents=True)
    target.write_text("changed by the person", encoding="utf-8")

    with pytest.raises(RecoveryConflictError):
        restore_absent_target(point, expected_applied_sha256=preview.content_sha256)
    assert target.read_text(encoding="utf-8") == "changed by the person"

