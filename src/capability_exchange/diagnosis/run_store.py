"""Atomic diagnosis checkpoints stored outside inspected roots."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

from capability_exchange.catalogue.subscription import (
    diagnosis_run_storage,
    require_app_storage_outside_roots,
)
from capability_exchange.diagnosis.run import (
    DiagnosisCheckpoint,
    DiagnosisStage,
    DiagnosisStateError,
)

__all__ = [
    "DiagnosisInputDrift",
    "DiagnosisRunStore",
    "diagnosis_run_storage",
]


class DiagnosisInputDrift(DiagnosisStateError):
    """A stored checkpoint no longer matches the expected input identity."""


def _checkpoint_name(run_id: str) -> str:
    return run_id.replace(":", "-") + ".json"


class DiagnosisRunStore:
    """Guarded atomic checkpoint store for one diagnosis engine."""

    def __init__(
        self,
        storage: Path,
        *,
        approved_roots: Iterable[Path] = (),
    ) -> None:
        self.storage = Path(storage).expanduser().resolve(strict=False)
        require_app_storage_outside_roots(self.storage, approved_roots)
        if self.storage.is_symlink() or any(
            parent.is_symlink() for parent in self.storage.parents
        ):
            raise ValueError("diagnosis run storage must not be a symlink")

    def _path_for(self, run_id: str) -> Path:
        path = (self.storage / _checkpoint_name(run_id)).resolve(strict=False)
        if path.is_symlink():
            raise ValueError("diagnosis checkpoint path must not be a symlink")
        if path.parent != self.storage:
            raise ValueError("diagnosis checkpoint escaped the run store")
        return path

    def save(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        self.storage.mkdir(parents=True, exist_ok=True)
        path = self._path_for(checkpoint.run_id)
        payload = json.dumps(
            checkpoint.dump_for_storage(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        temporary = path.with_name(path.name + ".tmp")
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        handle = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as writer:
                writer.write(payload)
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, path)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        return checkpoint

    def load(
        self,
        run_id: str,
        *,
        expected_input_digest: str | None = None,
    ) -> DiagnosisCheckpoint:
        path = self._path_for(run_id)
        if not path.is_file():
            raise DiagnosisStateError("unknown diagnosis run")
        try:
            text = path.read_text(encoding="utf-8")
            checkpoint = DiagnosisCheckpoint.model_validate(json.loads(text))
            canonical = json.dumps(
                checkpoint.dump_for_storage(),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        except Exception as exc:
            raise DiagnosisStateError("stored diagnosis checkpoint is unreadable") from exc
        if text != canonical:
            raise DiagnosisStateError("stored diagnosis checkpoint digest is invalid")
        if (
            expected_input_digest is not None
            and checkpoint.input_identity != expected_input_digest
        ):
            raise DiagnosisInputDrift("stored diagnosis input no longer matches this run")
        return checkpoint

    def list_resumable(self) -> tuple[DiagnosisCheckpoint, ...]:
        if not self.storage.is_dir():
            return ()
        checkpoints: list[DiagnosisCheckpoint] = []
        for path in sorted(self.storage.glob("run-*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                checkpoint = DiagnosisCheckpoint.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except Exception:
                continue
            if checkpoint.stage is DiagnosisStage.CLOSED:
                continue
            checkpoints.append(checkpoint)
        checkpoints.sort(key=lambda item: item.created_at)
        return tuple(checkpoints)
