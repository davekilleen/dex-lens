"""Atomic diagnosis checkpoints stored outside inspected roots."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

from pydantic import Field

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.catalogue.subscription import (
    diagnosis_run_storage,
    require_app_storage_outside_roots,
)
from capability_exchange.diagnosis.run import (
    ApprovedScopeReceipt,
    DiagnosisCheckpoint,
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.work import AnalysisMode

__all__ = [
    "DiagnosisInputDrift",
    "DiagnosisRunStore",
    "PersistedCandidateScope",
    "PersistedScopeApproval",
    "diagnosis_run_storage",
]


class DiagnosisInputDrift(DiagnosisStateError):
    """A stored checkpoint no longer matches the expected input identity."""


class PersistedScopeApproval(InventoriedModel):
    """Local-only approved roots plus the receipt, so later commands can collect."""

    run_id: str = Field(pattern=r"^run:[a-z0-9]{16,64}$")
    approved_roots: tuple[str, ...] = Field(min_length=1)
    receipt: ApprovedScopeReceipt


class PersistedCandidateScope(InventoriedModel):
    """Offered folders for a prepared run, stored outside inspected roots."""

    run_id: str = Field(pattern=r"^run:[a-z0-9]{16,64}$")
    candidate_roots: tuple[str, ...] = Field(min_length=1)
    locators: tuple[str, ...] = Field(min_length=1)
    analysis_mode: AnalysisMode = AnalysisMode.INVENTORY_ONLY


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

    def _sidecar_path_for(self, run_id: str, suffix: str) -> Path:
        return self._path_for(run_id).with_name(self._path_for(run_id).stem + suffix)

    def _approval_path_for(self, run_id: str) -> Path:
        return self._sidecar_path_for(run_id, ".scope.json")

    def _candidate_path_for(self, run_id: str) -> Path:
        return self._sidecar_path_for(run_id, ".candidate.json")

    def _write_atomic(self, path: Path, payload: str) -> None:
        self.storage.mkdir(parents=True, exist_ok=True)
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

    def save_scope_approval(
        self,
        receipt: ApprovedScopeReceipt,
        *,
        approved_roots: tuple[str, ...],
    ) -> PersistedScopeApproval:
        approval = PersistedScopeApproval(
            run_id=receipt.run_id,
            approved_roots=approved_roots,
            receipt=receipt,
        )
        path = self._approval_path_for(receipt.run_id)
        self._write_atomic(
            path,
            json.dumps(
                approval.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        return approval

    def load_scope_approval(self, run_id: str) -> PersistedScopeApproval | None:
        path = self._approval_path_for(run_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return PersistedScopeApproval.model_validate(payload)
        except Exception as exc:
            raise DiagnosisStateError("stored scope approval is unreadable") from exc

    def save_candidate_scope(
        self,
        run_id: str,
        *,
        candidate_roots: tuple[str, ...],
        locators: tuple[str, ...],
        analysis_mode: AnalysisMode = AnalysisMode.INVENTORY_ONLY,
    ) -> PersistedCandidateScope:
        if len(candidate_roots) != len(locators):
            raise DiagnosisStateError("candidate roots and locators must be the same length")
        offered = PersistedCandidateScope(
            run_id=run_id,
            candidate_roots=candidate_roots,
            locators=locators,
            analysis_mode=AnalysisMode(analysis_mode),
        )
        self._write_atomic(
            self._candidate_path_for(run_id),
            json.dumps(
                offered.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        return offered

    def load_candidate_scope(self, run_id: str) -> PersistedCandidateScope | None:
        path = self._candidate_path_for(run_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return PersistedCandidateScope.model_validate(payload)
        except Exception as exc:
            raise DiagnosisStateError("stored candidate scope is unreadable") from exc

    def _path_for(self, run_id: str) -> Path:
        path = (self.storage / _checkpoint_name(run_id)).resolve(strict=False)
        if path.is_symlink():
            raise ValueError("diagnosis checkpoint path must not be a symlink")
        if path.parent != self.storage:
            raise ValueError("diagnosis checkpoint escaped the run store")
        return path

    def save(self, checkpoint: DiagnosisCheckpoint) -> DiagnosisCheckpoint:
        payload = json.dumps(
            checkpoint.dump_for_storage(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        self._write_atomic(self._path_for(checkpoint.run_id), payload)
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
            if path.name.endswith((".scope.json", ".candidate.json")):
                continue
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
