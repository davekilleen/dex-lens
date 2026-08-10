from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.preview import (
    AdaptationPreview,
    PreviewDriftError,
    PreviewMismatchError,
    assert_preview_current,
    build_preview,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
CONTENT = "# Reading list helper\n\nKeep the local reading list grouped by topic.\n"


def request_for(root: Path) -> OperationRequest:
    return OperationRequest(
        operation=OperationKind.CREATE_NAMESPACED_SKILL,
        approved_root=str(root),
        relative_path="skills/dex-lens-reading-list/SKILL.md",
    )


def preview_for(root: Path, **overrides: object) -> AdaptationPreview:
    values: dict[str, object] = {
        "request": request_for(root),
        "host_id": "claude-code-local",
        "job_id": "reading-list",
        "capability_id": "topic-grouping",
        "content": CONTENT,
        "expected_benefit": "Group new reading-list entries by topic",
        "created_at": NOW,
    }
    values.update(overrides)
    return build_preview(**values)  # type: ignore[arg-type]


def test_preview_is_deterministic_and_binds_every_approved_effect(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    first = preview_for(root)
    second = preview_for(root)

    assert first.preview_digest == second.preview_digest
    assert first.content_sha256
    assert first.content_size == len(CONTENT.encode("utf-8"))
    assert first.effects == (f"create-file:{first.target_path}",)
    assert first.prior_state == "absent"


def test_any_change_to_content_or_scope_changes_preview_digest(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()

    first = preview_for(first_root)
    changed_content = preview_for(first_root, content=CONTENT + "Extra\n")
    changed_scope = preview_for(second_root)

    digests = {
        first.preview_digest,
        changed_content.preview_digest,
        changed_scope.preview_digest,
    }
    assert len(digests) == 3


def test_preview_rejects_incomplete_or_forged_effect_list(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = preview_for(root)
    payload = preview.model_dump(mode="python")
    payload["effects"] = ()
    with pytest.raises(ValidationError, match="effect"):
        AdaptationPreview.model_validate(payload)


def test_apply_content_must_be_byte_identical_to_preview(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = preview_for(root)
    preview.assert_content(CONTENT.encode("utf-8"))
    with pytest.raises(PreviewMismatchError, match="content"):
        preview.assert_content((CONTENT + "changed").encode("utf-8"))


def test_target_created_after_preview_is_drift_and_refuses_before_write(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = preview_for(root)
    target = Path(preview.target_path)
    target.parent.mkdir(parents=True)
    target.write_text("someone else's work", encoding="utf-8")

    with pytest.raises(PreviewDriftError, match="changed after preview"):
        assert_preview_current(preview)


def test_naive_preview_timestamp_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    with pytest.raises(ValidationError, match="timezone"):
        preview_for(root, created_at=datetime(2026, 8, 10, 9, 0))
