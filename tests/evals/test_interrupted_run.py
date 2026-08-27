"""Interrupted diagnosis resumes exactly; hostile mutations never reach SAVED."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.evals.test_real_session_replay import real_session_replay

from capability_exchange.diagnosis.comparison import ComparisonLedger, Disposition
from capability_exchange.diagnosis.observations import EvidenceFingerprint
from capability_exchange.diagnosis.receipts import DecisionState, RecommendationDecision, ShareState
from capability_exchange.diagnosis.report import ReportModel
from capability_exchange.diagnosis.run import DiagnosisStage, canonical_json_digest
from capability_exchange.diagnosis.run_store import DiagnosisInputDrift
from capability_exchange.evaluation.replay import (
    NON_TERMINAL_STAGES,
    ReplayHarness,
    canonical_replay_bytes,
    run_direct,
)


def _ledger_payload(harness: ReplayHarness) -> dict[str, object]:
    payload = harness._artifact_payload(harness.checkpoint(), "ledger")
    assert isinstance(payload, dict)
    return payload


def _fingerprint_payload(harness: ReplayHarness) -> dict[str, object]:
    payload = harness._artifact_payload(harness.checkpoint(), "fingerprint")
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize("stage", NON_TERMINAL_STAGES)
def test_interrupted_run_resumes_to_the_same_canonical_bytes(
    stage: DiagnosisStage, tmp_path: Path
) -> None:
    replay = real_session_replay(ordering="forward")
    uninterrupted = run_direct(replay)
    harness = ReplayHarness(replay, tmp_path / stage.value)
    harness.prepare()
    harness.run_to(stage)
    harness.rebuild_engine()
    resumed = canonical_replay_bytes(harness.resume_to_closed())
    assert resumed == uninterrupted
    assert harness.checkpoint().stage is DiagnosisStage.CLOSED


def test_changed_scope_digest_refuses_resume_as_stale(tmp_path: Path) -> None:
    replay = real_session_replay(ordering="forward")
    harness = ReplayHarness(replay, tmp_path)
    harness.prepare()
    harness.run_to(DiagnosisStage.SCOPE_APPROVED)
    previous = harness.checkpoint()
    receipt = harness.consent.receipt_for(replay.run_id)
    assert receipt is not None
    hostile_reference = "scope:sha256:" + "d" * 64
    harness.replace_artifact(
        "scope-receipt",
        receipt.model_copy(
            update={
                "scope_references": (hostile_reference,),
                "scope_digest": canonical_json_digest([hostile_reference]),
            }
        ).dump_for_storage(),
    )
    harness.rebuild_engine()
    with pytest.raises(DiagnosisInputDrift, match="no longer matches"):
        harness.resume_to_closed()
    assert harness.checkpoint().stage is previous.stage
    assert harness.checkpoint().input_identity == previous.input_identity


def _mutate_count(harness: ReplayHarness) -> None:
    ledger = ComparisonLedger.model_validate(_ledger_payload(harness))
    entries = list(ledger.entries)
    for index, entry in enumerate(entries):
        if entry.disposition is Disposition.NOT_ASSESSED:
            entries[index] = entry.model_copy(update={"disposition": Disposition.NOT_RELEVANT})
            break
    harness.replace_artifact(
        "ledger",
        ledger.model_copy(update={"entries": tuple(entries)}).model_dump(mode="json"),
    )


def _mutate_catalogue_hash(harness: ReplayHarness) -> None:
    ledger = ComparisonLedger.model_validate(_ledger_payload(harness))
    harness.replace_artifact(
        "ledger",
        ledger.model_copy(update={"catalogue_sha256": "c" * 64}).model_dump(mode="json"),
    )


def _mutate_evidence_reference(harness: ReplayHarness) -> None:
    ledger = ComparisonLedger.model_validate(_ledger_payload(harness))
    entries = list(ledger.entries)
    for index, entry in enumerate(entries):
        if entry.evidence_references:
            entries[index] = entry.model_copy(
                update={"evidence_references": ("file-token:hostile-missing.md",)}
            )
            break
    harness.replace_artifact(
        "ledger",
        ledger.model_copy(update={"entries": tuple(entries)}).model_dump(mode="json"),
    )


def _mutate_source_class(harness: ReplayHarness) -> None:
    fingerprint = EvidenceFingerprint.model_validate(_fingerprint_payload(harness))
    observations: list[object] = []
    changed = False
    for item in fingerprint.observations:
        raw = item.model_dump(mode="json")
        if not changed and raw["provenance"]["source_class"] == "vault-authored":
            raw["provenance"]["source_class"] = "generated"
            changed = True
        observations.append(type(item).model_validate(raw))
    harness.replace_artifact(
        "fingerprint",
        fingerprint.model_copy(update={"observations": tuple(observations)}).model_dump(
            mode="json"
        ),
    )


def _hostile_from_result(kind: str):
    original = ReportModel.from_result

    def injected(**kwargs: object) -> ReportModel:
        if kind == "decision_state":
            kwargs["decisions"] = (
                RecommendationDecision(
                    catalogue_id="invented-capability-000",
                    state=DecisionState.COMPLETED,
                ),
            )
        elif kind == "share_state":
            kwargs["share_state"] = ShareState.SENT
        return original(**kwargs)

    return injected


@pytest.mark.parametrize(
    "mutation",
    (
        "count",
        "catalogue_hash",
        "evidence_reference",
        "decision_state",
        "share_state",
        "source_class",
    ),
)
def test_hostile_factual_mutation_fails_before_saved(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replay = real_session_replay(ordering="forward")
    harness = ReplayHarness(replay, tmp_path / mutation)
    harness.prepare()
    harness.run_to(DiagnosisStage.CHECKED)
    if mutation == "count":
        _mutate_count(harness)
    elif mutation == "catalogue_hash":
        _mutate_catalogue_hash(harness)
    elif mutation == "evidence_reference":
        _mutate_evidence_reference(harness)
    elif mutation == "source_class":
        _mutate_source_class(harness)
    else:
        monkeypatch.setattr(
            "capability_exchange.diagnosis.orchestrator.ReportModel.from_result",
            _hostile_from_result(mutation),
        )
    previous = harness.checkpoint()
    with pytest.raises((DiagnosisInputDrift, ValueError), match="hostile|receipt|facts"):
        harness.engine.advance(replay.run_id)
    intact = harness.checkpoint()
    assert intact.stage is DiagnosisStage.CHECKED
    assert intact.canonical_digest() == previous.canonical_digest()
    assert harness.reports.list() == []
