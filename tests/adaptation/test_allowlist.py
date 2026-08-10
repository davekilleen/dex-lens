from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_exchange.adaptation.allowlist import (
    ALLOWED_OPERATIONS,
    OperationRequest,
    RefusalCode,
    assess_operation,
    canonical_target,
)
from capability_exchange.adaptation.contract import OperationKind


def test_allowlist_is_data_and_contains_only_the_create_only_operation() -> None:
    assert tuple(ALLOWED_OPERATIONS) == (OperationKind.CREATE_NAMESPACED_SKILL,)
    declaration = ALLOWED_OPERATIONS[OperationKind.CREATE_NAMESPACED_SKILL]
    assert declaration.create_only
    assert declaration.network_allowed is False
    assert declaration.overwrite_allowed is False


@pytest.mark.parametrize(
    "blocked",
    [
        "send-message",
        "network-post",
        "delete-source",
        "change-permissions",
        "edit-credentials",
        "publish",
        "purchase",
        "weaken-security",
        "change-external-system",
    ],
)
def test_blocked_categories_cannot_be_constructed_and_refuse_honestly(
    blocked: str,
) -> None:
    with pytest.raises(ValidationError):
        OperationRequest(operation=blocked, approved_root="/tmp/approved", relative_path="x")
    refusal = assess_operation(blocked)
    assert refusal.allowed is False
    assert refusal.code is RefusalCode.NOT_ALLOWLISTED
    assert blocked in refusal.explanation


def test_unknown_operation_refuses_instead_of_guessing() -> None:
    refusal = assess_operation(object())
    assert refusal.allowed is False
    assert refusal.code is RefusalCode.UNCLASSIFIABLE


@pytest.mark.parametrize(
    "relative_path",
    ["../escape.md", "/absolute.md", "skills/*.md", "skills/[x].md", "", "."],
)
def test_target_path_rejects_traversal_absolute_globs_and_empty(
    tmp_path: Path, relative_path: str
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        request = OperationRequest(
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
            approved_root=str(tmp_path),
            relative_path=relative_path,
        )
        canonical_target(request)


def test_target_is_canonical_and_jailed_under_approved_root(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    request = OperationRequest(
        operation=OperationKind.CREATE_NAMESPACED_SKILL,
        approved_root=str(approved),
        relative_path="skills/dex-lens-reading-list/SKILL.md",
    )
    target = canonical_target(request)
    assert target == approved / "skills/dex-lens-reading-list/SKILL.md"
    assert target.is_absolute()


def test_symlinked_parent_escape_is_refused(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    (approved / "skills").symlink_to(outside, target_is_directory=True)
    request = OperationRequest(
        operation=OperationKind.CREATE_NAMESPACED_SKILL,
        approved_root=str(approved),
        relative_path="skills/dex-lens-reading-list/SKILL.md",
    )
    with pytest.raises(ValueError, match="outside the approved root"):
        canonical_target(request)


def test_existing_target_is_refused_by_create_only_recipe(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    target = approved / "skills/dex-lens-reading-list/SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("existing", encoding="utf-8")
    request = OperationRequest(
        operation=OperationKind.CREATE_NAMESPACED_SKILL,
        approved_root=str(approved),
        relative_path="skills/dex-lens-reading-list/SKILL.md",
    )
    with pytest.raises(ValueError, match="already exists"):
        canonical_target(request)

