"""Closed diagnosis stages and content-bound run identity."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    INPUT_SCHEMA_VERSION,
    NEXT_ACTION,
    NEXT_STAGE,
    ApprovedScopeReceipt,
    DiagnosisCheckpoint,
    DiagnosisInput,
    DiagnosisStage,
    DiagnosisStateError,
    RunIdentity,
    advance_to,
    canonical_json_digest,
)

NOW = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)
RUN_ID = "run:" + "a" * 16


def _scope_ref(label: str) -> str:
    return "scope:" + canonical_json_digest(label)


def approved_receipt(*, scope: str = "vault") -> ApprovedScopeReceipt:
    reference = _scope_ref(scope)
    return ApprovedScopeReceipt(
        run_id=RUN_ID,
        scope_references=(reference,),
        scope_digest=canonical_json_digest([reference]),
        session_receipt_id="session:local-test",
        approved_at=NOW,
    )


def diagnosis_input(*, scope: str = "vault") -> DiagnosisInput:
    return DiagnosisInput(
        run_id=RUN_ID,
        engine_version=ENGINE_VERSION,
        input_schema_version=INPUT_SCHEMA_VERSION,
        adapter_version="invented-adapter-1",
        approved_scope_receipt=approved_receipt(scope=scope),
        fingerprint_sha256="b" * 64,
        catalogue_version=115,
        catalogue_sha256="c" * 64,
        confirmed_jobs=(),
        assessed_at=NOW,
    )


def created_checkpoint() -> DiagnosisCheckpoint:
    return DiagnosisCheckpoint(
        run_id=RUN_ID,
        stage=DiagnosisStage.CREATED,
        previous_digest=None,
        input_identity=diagnosis_input().identity_digest,
        artifact_digests=(),
        next_action=NEXT_ACTION[DiagnosisStage.CREATED],
        engine_version=ENGINE_VERSION,
        created_at=NOW,
    )


def test_stage_order_is_closed() -> None:
    assert list(DiagnosisStage) == [
        DiagnosisStage.CREATED,
        DiagnosisStage.SCOPE_APPROVED,
        DiagnosisStage.CAPTURED,
        DiagnosisStage.CATALOGUE_VERIFIED,
        DiagnosisStage.JOBS_CONFIRMED,
        DiagnosisStage.COMPARED,
        DiagnosisStage.RENDERED,
        DiagnosisStage.CHECKED,
        DiagnosisStage.SAVED,
        DiagnosisStage.CLOSED,
    ]
    assert list(NEXT_STAGE) == list(DiagnosisStage)[:-1]


def test_input_identity_changes_when_scope_changes() -> None:
    first = diagnosis_input(scope="a")
    second = diagnosis_input(scope="b")

    assert first.identity_digest != second.identity_digest
    assert first.identity_digest == diagnosis_input(scope="a").identity_digest
    assert first.identity_digest.startswith("sha256:")
    assert len(first.identity_digest) == len("sha256:") + 64


def test_advance_to_is_lawful_and_idempotent() -> None:
    created = created_checkpoint()
    approved = advance_to(created, DiagnosisStage.SCOPE_APPROVED, now=NOW)

    assert approved.stage is DiagnosisStage.SCOPE_APPROVED
    assert approved.previous_digest == created.canonical_digest()
    assert advance_to(approved, DiagnosisStage.SCOPE_APPROVED, now=NOW) == approved

    with pytest.raises(DiagnosisStateError, match="cannot move"):
        advance_to(created, DiagnosisStage.CAPTURED, now=NOW)
    with pytest.raises(DiagnosisStateError, match="cannot move"):
        advance_to(approved, DiagnosisStage.CREATED, now=NOW)


def test_run_models_reject_naive_timestamps_and_bypasses() -> None:
    naive = datetime(2026, 8, 27, 16, 0)
    receipt = approved_receipt()

    with pytest.raises(ValidationError, match="timezone-aware"):
        receipt.model_copy(update={"approved_at": naive})
    with pytest.raises(TypeError, match="validated model_copy"):
        receipt.copy()
    with pytest.raises(ValidationError, match="timezone-aware"):
        RunIdentity.model_construct(
            run_id=RUN_ID,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            created_at=naive,
        )


def test_checkpoint_and_receipt_are_storage_bound() -> None:
    receipt = approved_receipt()
    checkpoint = created_checkpoint()

    assert receipt.dump_for_storage()["scope_digest"] == receipt.scope_digest
    assert checkpoint.dump_for_storage()["stage"] == DiagnosisStage.CREATED.value
    assert "vault" not in receipt.model_dump_json()
    assert "/Users/" not in checkpoint.model_dump_json()
