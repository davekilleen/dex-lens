import hashlib
import json
from datetime import UTC, datetime

import pytest

from capability_exchange.adaptation.transaction import TransactionEngine
from capability_exchange.pilot._common import content_hash
from capability_exchange.pilot.drills import (
    REQUIRED_RUNBOOK_IDS,
    TABLETOP_SCENARIOS,
    DrillExecutor,
    TabletopResult,
    validate_recovery_failure_evidence,
)


def test_all_five_runbooks_have_passing_tabletops() -> None:
    executor = DrillExecutor()
    results = executor.execute_all()
    assert tuple(result.runbook_id for result in results) == REQUIRED_RUNBOOK_IDS
    assert executor.complete()
    withdrawal = next(result for result in results if result.runbook_id == "withdrawal")
    assert withdrawal.deletion_verified
    adverse = next(result for result in results if result.runbook_id == "incident")
    assert adverse.stop_triggered
    assert "Recovery failed" in adverse.scenario
    assert adverse.execution_evidence_hash
    assert adverse.transaction_id
    assert adverse.transaction_journal_sha256
    assert adverse.transaction_receipt_sha256
    assert adverse.recovery_manifest_sha256
    assert adverse.observed_incident_kind == "recovery-failed"
    assert adverse.recovery_error_observed is True


def test_recovery_tabletop_fails_if_real_undo_does_not_raise(monkeypatch) -> None:
    monkeypatch.setattr(TransactionEngine, "undo", lambda self, preview: None)

    result = DrillExecutor().execute("incident")

    assert result.passed is False
    assert result.stop_triggered is False


def test_recovery_tabletop_rejects_a_forged_evidence_hash() -> None:
    result = DrillExecutor().execute("incident")
    forged = result.model_copy(update={"execution_evidence_hash": "0" * 64})

    with pytest.raises(ValueError, match="evidence hash"):
        type(result).model_validate(forged.model_dump(mode="python"))


def test_caller_computed_hashes_cannot_replace_filesystem_execution_evidence() -> None:
    scenario, trigger = TABLETOP_SCENARIOS["incident"]
    execution_hash = content_hash(
        {
            "transaction_id": "invented-transaction",
            "transaction_journal_sha256": "d" * 64,
            "transaction_receipt_sha256": "e" * 64,
            "recovery_manifest_sha256": "f" * 64,
            "recovery_error_observed": True,
            "hard_stopped": True,
            "incident_kind": "recovery-failed",
        }
    )
    with pytest.raises(ValueError, match="filesystem evidence context"):
        TabletopResult.model_validate(
            {
                "runbook_id": "incident",
                "scenario_id": scenario,
                "trigger_id": trigger,
                "runbook_artifact_hash": "a" * 64,
                "execution_evidence_hash": execution_hash,
                "execution_artifact_path": "invented.json",
                "execution_artifact_hash": "c" * 64,
                "transaction_id": "invented-transaction",
                "transaction_journal_sha256": "d" * 64,
                "transaction_receipt_sha256": "e" * 64,
                "recovery_manifest_sha256": "f" * 64,
                "observed_incident_kind": "recovery-failed",
                "recovery_error_observed": True,
                "scenario": "caller says it ran",
                "executed_at": datetime.now(UTC),
                "passed": True,
                "trigger_observed": True,
                "actions_evidenced": ("caller says actions happened",),
                "exit_criteria_met": True,
                "stop_triggered": True,
                "notes": "forged",
            }
        )


def test_real_recovery_evidence_survives_transaction_tempdir_and_detects_tamper(
    tmp_path,
) -> None:
    executor = DrillExecutor(evidence_root=tmp_path)
    result = executor.execute("incident")
    artifact = tmp_path / (result.execution_artifact_path or "")

    assert artifact.is_file()
    validate_recovery_failure_evidence(
        artifact,
        result.execution_artifact_hash or "",
        verifier=executor.evidence_verifier,
        trusted_key_ids=executor.trusted_evidence_key_ids,
    )
    artifact.write_bytes(artifact.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash"):
        validate_recovery_failure_evidence(
            artifact,
            result.execution_artifact_hash or "",
            verifier=executor.evidence_verifier,
            trusted_key_ids=executor.trusted_evidence_key_ids,
        )


def test_self_consistent_caller_authored_artifact_lacks_trusted_provenance(tmp_path) -> None:
    executor = DrillExecutor(evidence_root=tmp_path)
    result = executor.execute("incident")
    artifact = tmp_path / (result.execution_artifact_path or "")
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["signature"] = "caller-authored"
    artifact.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    forged_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    forged = result.model_copy(update={"execution_artifact_hash": forged_hash})

    with pytest.raises(ValueError, match="attestation is untrusted"):
        TabletopResult.model_validate(
            forged.model_dump(mode="python"),
            context={
                "evidence_root": tmp_path,
                "evidence_verifier": executor.evidence_verifier,
                "trusted_evidence_key_ids": executor.trusted_evidence_key_ids,
            },
        )


def test_trusted_recovery_evidence_cannot_mask_contradictory_result_flags(tmp_path) -> None:
    executor = DrillExecutor(evidence_root=tmp_path)
    result = executor.execute("incident")
    contradictory = result.model_copy(
        update={"trigger_observed": False, "exit_criteria_met": False}
    )

    with pytest.raises(ValueError, match="trigger and exit criteria"):
        TabletopResult.model_validate(
            contradictory.model_dump(mode="python"),
            context={
                "evidence_root": tmp_path,
                "evidence_verifier": executor.evidence_verifier,
                "trusted_evidence_key_ids": executor.trusted_evidence_key_ids,
            },
        )
