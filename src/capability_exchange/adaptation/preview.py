"""Exact, drift-detecting M4 adaptation preview (T1/T2)."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.adaptation.allowlist import OperationRequest, canonical_target
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "AdaptationPreview",
    "PreviewDriftError",
    "PreviewMismatchError",
    "assert_preview_current",
    "build_preview",
]


class PreviewMismatchError(Exception):
    """Proposed apply bytes do not match the exact approved preview."""


class PreviewDriftError(Exception):
    """The approved scope or target changed after preview."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_payload(values: dict[str, object]) -> str:
    encoded = json.dumps(
        values,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256(encoded)


class AdaptationPreview(InventoriedModel):
    """One complete human-reviewable effect list bound to exact bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=128)
    capability_id: str = Field(min_length=1, max_length=128)
    operation: OperationKind
    approved_root: str
    relative_path: str
    target_path: str
    content: str = Field(min_length=1, max_length=262_144)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_size: int = Field(ge=1, le=262_144)
    prior_state: Literal["absent"]
    effects: tuple[str, ...] = Field(min_length=1, max_length=1)
    expected_benefit: str = Field(min_length=1, max_length=500)
    risks: tuple[str, ...] = Field(min_length=1)
    created_at: datetime
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def _timestamp_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    def _digest_fields(self) -> dict[str, object]:
        return {
            "host_id": self.host_id,
            "job_id": self.job_id,
            "capability_id": self.capability_id,
            "operation": self.operation.value,
            "approved_root": self.approved_root,
            "relative_path": self.relative_path,
            "target_path": self.target_path,
            "content": self.content,
            "content_sha256": self.content_sha256,
            "content_size": self.content_size,
            "prior_state": self.prior_state,
            "effects": list(self.effects),
            "expected_benefit": self.expected_benefit,
            "risks": list(self.risks),
            "created_at": self.created_at.isoformat(),
        }

    @model_validator(mode="after")
    def _exact_and_unforged(self) -> AdaptationPreview:
        content_bytes = self.content.encode("utf-8")
        if self.content_size != len(content_bytes) or self.content_sha256 != _sha256(
            content_bytes
        ):
            raise ValueError("content size/hash does not match the exact preview content")
        expected_effects = (f"create-file:{self.target_path}",)
        if self.effects != expected_effects:
            raise ValueError("effect list is incomplete or does not match the exact target")
        if self.preview_digest != _digest_payload(self._digest_fields()):
            raise ValueError("preview_digest does not match the exact preview fields")
        return self

    def assert_content(self, content: bytes) -> None:
        if len(content) != self.content_size or _sha256(content) != self.content_sha256:
            raise PreviewMismatchError(
                "apply content differs from the exact approved preview content"
            )


def build_preview(
    *,
    request: OperationRequest,
    host_id: str,
    job_id: str,
    capability_id: str,
    content: str,
    expected_benefit: str,
    created_at: datetime,
) -> AdaptationPreview:
    """Create a preview only while the create-only target is absent and jailed."""

    target = canonical_target(request)
    if not target.parent.is_dir():
        raise ValueError(
            "target parent directory must already exist; implicit directory "
            "creation is not part of the exact effect list"
        )
    content_bytes = content.encode("utf-8")
    values: dict[str, object] = {
        "host_id": host_id,
        "job_id": job_id,
        "capability_id": capability_id,
        "operation": request.operation,
        "approved_root": str(Path(request.approved_root).resolve(strict=True)),
        "relative_path": request.relative_path,
        "target_path": str(target),
        "content": content,
        "content_sha256": _sha256(content_bytes),
        "content_size": len(content_bytes),
        "prior_state": "absent",
        "effects": (f"create-file:{target}",),
        "expected_benefit": expected_benefit,
        "risks": (
            "creates one user-owned local Markdown file",
            "does not overwrite, send data, or use the network",
        ),
        "created_at": created_at,
    }
    digest_values = {
        **values,
        "operation": request.operation.value,
        "effects": list(values["effects"]),
        "risks": list(values["risks"]),
        "created_at": created_at.isoformat(),
    }
    return AdaptationPreview(**values, preview_digest=_digest_payload(digest_values))


def assert_preview_current(preview: AdaptationPreview) -> None:
    """Refuse if scope resolution or target state changed after preview."""

    try:
        root = Path(preview.approved_root).resolve(strict=True)
        candidate = root.joinpath(*PurePosixPath(preview.relative_path).parts).resolve(
            strict=False
        )
        candidate.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise PreviewDriftError("approved scope changed after preview") from exc
    if str(candidate) != preview.target_path or os.path.lexists(candidate):
        raise PreviewDriftError("target changed after preview; no write was attempted")
