"""Validated recovery points for the create-only M4 pilot operation (T4/T8)."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.adaptation.preview import AdaptationPreview
from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "RecoveryConflictError",
    "RecoveryPoint",
    "RecoveryUnavailableError",
    "create_recovery_point",
    "restore_absent_target",
    "validate_recovery_point",
]


class RecoveryUnavailableError(Exception):
    """A recovery point could not be created or proven readable."""


class RecoveryConflictError(Exception):
    """Undo would overwrite or delete later unrelated work."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class RecoveryPoint(InventoriedModel):
    """Validated proof that the create-only target was absent before apply."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recovery_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_path: str
    prior_state: Literal["absent"]
    created_at: datetime
    manifest_path: str

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recovery created_at must be timezone-aware")
        return value


def _canonical_payload(point: RecoveryPoint) -> bytes:
    return json.dumps(
        point.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def create_recovery_point(
    preview: AdaptationPreview, *, state_root: Path, created_at: datetime
) -> RecoveryPoint:
    """Write, read, and checksum a recovery manifest before any target mutation."""

    target = Path(preview.target_path)
    if os.path.lexists(target):
        raise RecoveryUnavailableError("target is no longer absent; recovery refused")
    try:
        state_root.mkdir(parents=True, exist_ok=True)
        if not state_root.is_dir():
            raise NotADirectoryError(state_root)
        manifest = state_root / f"recovery-{preview.preview_digest[:32]}.json"
        if os.path.lexists(manifest):
            raise FileExistsError(manifest)
        point = RecoveryPoint(
            recovery_id=preview.preview_digest[:32],
            preview_digest=preview.preview_digest,
            target_path=preview.target_path,
            prior_state="absent",
            created_at=created_at,
            manifest_path=str(manifest),
        )
        payload = _canonical_payload(point)
        wrapper = json.dumps(
            {
                "payload": json.loads(payload),
                "payload_sha256": _sha256(payload),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        temporary = manifest.with_suffix(".tmp")
        with temporary.open("xb") as handle:
            handle.write(wrapper)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, manifest)
        proven = validate_recovery_point(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RecoveryUnavailableError(
            "recovery point could not be created and read back before mutation"
        ) from exc
    if proven != point:
        raise RecoveryUnavailableError("recovery read-back did not match its source")
    return proven


def validate_recovery_point(manifest: Path) -> RecoveryPoint:
    """Verify schema, checksum, path identity, and prior-state proof."""

    try:
        wrapper = json.loads(manifest.read_text(encoding="utf-8"))
        if set(wrapper) != {"payload", "payload_sha256"}:
            raise ValueError("unexpected recovery wrapper fields")
        payload = json.dumps(
            wrapper["payload"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if _sha256(payload) != wrapper["payload_sha256"]:
            raise ValueError("recovery manifest checksum mismatch")
        point = RecoveryPoint.model_validate(wrapper["payload"])
        if Path(point.manifest_path) != manifest:
            raise ValueError("recovery manifest path does not identify itself")
        if os.path.lexists(point.target_path):
            raise ValueError("target is not in the recorded absent state")
        return point
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise RecoveryUnavailableError("recovery point is missing, truncated, or invalid") from exc


def restore_absent_target(
    point: RecoveryPoint, *, expected_applied_sha256: str
) -> None:
    """Restore absence only when the target still contains the exact applied bytes."""

    target = Path(point.target_path)
    if not os.path.lexists(target):
        return
    if target.is_symlink() or not target.is_file():
        raise RecoveryConflictError("target shape changed after apply; undo refused")
    try:
        current_digest = _sha256(target.read_bytes())
    except OSError as exc:
        raise RecoveryConflictError("target cannot be read safely; undo refused") from exc
    if current_digest != expected_applied_sha256:
        raise RecoveryConflictError("target contains later unrelated work; undo refused")
    target.unlink()
    if os.path.lexists(target):
        raise RecoveryUnavailableError("target survived recovery unlink")

