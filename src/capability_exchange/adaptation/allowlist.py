"""Data-driven G3 operation allowlist and approval-root path jail."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final

from pydantic import ConfigDict, field_validator

from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "ALLOWED_OPERATIONS",
    "AllowedOperation",
    "OperationAssessment",
    "OperationRequest",
    "RefusalCode",
    "assess_operation",
    "canonical_target",
]


@dataclass(frozen=True, slots=True)
class AllowedOperation:
    """Static safety properties for one constructable operation."""

    operation: OperationKind
    create_only: bool
    overwrite_allowed: bool
    network_allowed: bool
    idempotency: str


_CREATE_NAMESPACED_SKILL = AllowedOperation(
    operation=OperationKind.CREATE_NAMESPACED_SKILL,
    create_only=True,
    overwrite_allowed=False,
    network_allowed=False,
    idempotency="same-preview-digest-produces-one-file-or-an-honest-existing-target-refusal",
)

ALLOWED_OPERATIONS: Final = MappingProxyType(
    {OperationKind.CREATE_NAMESPACED_SKILL: _CREATE_NAMESPACED_SKILL}
)


class RefusalCode(StrEnum):
    NOT_ALLOWLISTED = "not-allowlisted"
    UNCLASSIFIABLE = "unclassifiable"


@dataclass(frozen=True, slots=True)
class OperationAssessment:
    allowed: bool
    code: RefusalCode | None
    explanation: str


class OperationRequest(InventoriedModel):
    """One proposed operation before preview or permission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: OperationKind
    approved_root: str
    relative_path: str

    @field_validator("approved_root")
    @classmethod
    def _approved_root_is_bounded_absolute_path(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute() or path == Path(path.anchor):
            raise ValueError("approved_root must be a bounded absolute path")
        if any(character in value for character in "*?[]{}"):
            raise ValueError("approved_root cannot contain glob syntax")
        return value

    @field_validator("relative_path")
    @classmethod
    def _relative_path_is_literal_and_bounded(cls, value: str) -> str:
        if not value or value in {".", ".."} or os.path.isabs(value):
            raise ValueError("relative_path must name a bounded relative target")
        if any(character in value for character in "*?[]{}"):
            raise ValueError("relative_path cannot contain glob syntax")
        parts = PurePosixPath(value).parts
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("relative_path cannot contain traversal")
        return value


def assess_operation(operation: object) -> OperationAssessment:
    """Return a specific fail-closed decision for arbitrary proposed input."""

    if isinstance(operation, OperationKind) and operation in ALLOWED_OPERATIONS:
        return OperationAssessment(
            allowed=True,
            code=None,
            explanation=f"{operation.value} is present in the closed local-operation allowlist",
        )
    if isinstance(operation, str):
        return OperationAssessment(
            allowed=False,
            code=RefusalCode.NOT_ALLOWLISTED,
            explanation=f"{operation} is not on the reversible local-operation allowlist",
        )
    return OperationAssessment(
        allowed=False,
        code=RefusalCode.UNCLASSIFIABLE,
        explanation="the proposed operation could not be classified and is refused",
    )


def canonical_target(request: OperationRequest) -> Path:
    """Resolve an exact create-only target within the approved real-path jail."""

    declaration = ALLOWED_OPERATIONS[request.operation]
    root = Path(request.approved_root).resolve(strict=True)
    unresolved = root.joinpath(*PurePosixPath(request.relative_path).parts)
    resolved = unresolved.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("target resolves outside the approved root") from exc
    if declaration.create_only and resolved.exists():
        raise ValueError("create-only operation refused because target already exists")
    return resolved
