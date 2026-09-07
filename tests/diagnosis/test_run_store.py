"""Diagnosis checkpoints persist atomically outside inspected roots."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.diagnosis.test_run import approved_receipt, created_checkpoint, diagnosis_input

from capability_exchange.catalogue.subscription import diagnosis_run_storage
from capability_exchange.diagnosis.run import DiagnosisStage, DiagnosisStateError, advance_to
from capability_exchange.diagnosis.run_store import (
    DiagnosisInputDrift,
    DiagnosisRunConflict,
    DiagnosisRunStore,
)

NOW = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)


def checkpoint(stage: DiagnosisStage, *, created_at: datetime = NOW):
    current = created_checkpoint()
    if stage is DiagnosisStage.CREATED:
        return current.model_copy(update={"created_at": created_at})
    return advance_to(current, stage, now=created_at)


@pytest.fixture
def store(tmp_path: Path) -> DiagnosisRunStore:
    vault = tmp_path / "vault"
    vault.mkdir()
    storage = tmp_path / "state" / "diagnosis-runs"
    return DiagnosisRunStore(storage, approved_roots=(vault,))


def test_run_store_is_outside_every_approved_root(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    with pytest.raises(ValueError, match="outside the approved read scope"):
        DiagnosisRunStore(root / "state", approved_roots=(root,))


def test_failed_replace_leaves_previous_checkpoint(
    store: DiagnosisRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = store.save(checkpoint(DiagnosisStage.CREATED))
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        store.save(checkpoint(DiagnosisStage.SCOPE_APPROVED))
    assert store.load(first.run_id).stage is DiagnosisStage.CREATED


def test_load_refuses_unknown_runs_and_input_drift(store: DiagnosisRunStore) -> None:
    saved = store.save(checkpoint(DiagnosisStage.CREATED))

    with pytest.raises(DiagnosisStateError, match="unknown diagnosis run"):
        store.load("run:" + "0" * 16)
    with pytest.raises(DiagnosisInputDrift, match="no longer matches"):
        store.load(saved.run_id, expected_input_digest="sha256:" + "0" * 64)
    assert store.load(saved.run_id, expected_input_digest=diagnosis_input().identity_digest)


def test_list_resumable_skips_closed_and_orders_by_time(store: DiagnosisRunStore) -> None:
    later = store.save(
        checkpoint(DiagnosisStage.CREATED).model_copy(
            update={"run_id": "run:" + "b" * 16, "created_at": NOW + timedelta(minutes=2)}
        )
    )
    earlier = store.save(
        checkpoint(DiagnosisStage.CREATED).model_copy(
            update={"run_id": "run:" + "c" * 16, "created_at": NOW + timedelta(minutes=1)}
        )
    )
    store.save(
        checkpoint(DiagnosisStage.CREATED).model_copy(
            update={
                "run_id": "run:" + "d" * 16,
                "stage": DiagnosisStage.CLOSED,
                "next_action": (
                    "Diagnosis is closed. Start a new authorised flow for any follow-on work."
                ),
                "created_at": NOW,
            }
        )
    )

    resumable = store.list_resumable()
    assert [item.run_id for item in resumable] == [earlier.run_id, later.run_id]


def test_list_resumable_skips_candidate_and_scope_sidecars(store: DiagnosisRunStore) -> None:
    saved = store.save(checkpoint(DiagnosisStage.CREATED))
    store.save_candidate_scope(
        saved.run_id,
        candidate_roots=("/invented/vault",),
        locators=("candidate:sha256:" + ("ab" * 32),),
    )
    store.save_scope_approval(
        approved_receipt(),
        approved_roots=("/invented/vault",),
    )

    resumable = store.list_resumable()
    assert [item.run_id for item in resumable] == [saved.run_id]


def test_save_refuses_a_stale_expected_head(store: DiagnosisRunStore) -> None:
    """RISK finding B2 backstop: a save derived from a moved head is refused.

    Red first: without ``expected_head`` support, ``save`` was unconditional
    last-writer-wins, so the second writer silently clobbered the first
    writer's records.
    """

    base = store.save(checkpoint(DiagnosisStage.CREATED))
    advanced = checkpoint(DiagnosisStage.SCOPE_APPROVED)

    # A save derived from the current head is accepted.
    store.save(advanced, expected_head=base.canonical_digest())
    assert store.load(base.run_id).stage is DiagnosisStage.SCOPE_APPROVED

    # A save derived from the superseded head is a typed, retryable conflict,
    # and the newer head survives untouched.
    stale = base.model_copy(update={"created_at": NOW + timedelta(minutes=1)})
    with pytest.raises(DiagnosisRunConflict, match="reload the run and retry") as conflict:
        store.save(stale, expected_head=base.canonical_digest())
    assert isinstance(conflict.value, DiagnosisStateError)
    assert store.load(base.run_id).stage is DiagnosisStage.SCOPE_APPROVED

    # Without expected_head the store keeps its raw last-writer semantics for
    # deliberate tooling (rewind, tamper fixtures).
    store.save(stale)
    assert store.load(base.run_id).stage is DiagnosisStage.CREATED


def test_exclusive_lock_is_per_run_and_blocks_a_second_acquirer(
    store: DiagnosisRunStore,
) -> None:
    """The flock section is exclusive for one run and independent across runs."""

    import fcntl

    run_a = checkpoint(DiagnosisStage.CREATED).run_id
    run_b = "run:" + "e" * 16

    def try_lock(run_id: str) -> bool:
        path = store._lock_path_for(run_id)  # noqa: SLF001
        handle = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
            return True
        finally:
            os.close(handle)

    with store.exclusive(run_a):
        assert not try_lock(run_a), "a second acquirer must block on the same run"
        assert try_lock(run_b), "the lock is per run, not global"
    assert try_lock(run_a), "the lock is released when the section exits"


def test_diagnosis_run_storage_uses_app_state_outside_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    storage = diagnosis_run_storage((root,))
    assert storage.name == "diagnosis-runs"
    assert root not in storage.parents
    assert not storage.is_relative_to(root)
