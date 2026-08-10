from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.preview import build_preview
from capability_exchange.adaptation.verification import (
    CREATED_SKILL_OUTCOME_SIGNAL,
    VerificationVerdict,
    verify_created_skill,
)
from capability_exchange.diagnosis.finding import CapabilityState
from capability_exchange.evidence import EvidenceLevel, EvidenceState
from capability_exchange.jobs.contract import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def contract(*, signal: str = CREATED_SKILL_OUTCOME_SIGNAL) -> SuccessContract:
    return SuccessContract(
        job_id="reading-list",
        situation="When I save useful articles during the week",
        desired_outcome="My local reading list is grouped by topic",
        success_evidence=(signal,),
        boundaries=JobBoundaries(
            privacy_limits=("No article text leaves this machine",),
            approval_limits=("Ask before changing my Claude Code setup",),
            autonomy_limits=("Never send or publish the reading list",),
        ),
        importance=JobImportance.MEDIUM,
        cadence=JobCadence.WEEKLY,
        confirmed_at=NOW,
    )


def make_preview(root: Path, *, content: str = "# Skill\n"):
    return build_preview(
        request=OperationRequest(
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
            approved_root=str(root),
            relative_path="dex-lens-reading-list.md",
        ),
        host_id="claude-code-local",
        job_id="reading-list",
        capability_id="topic-grouping",
        content=content,
        expected_benefit="Group reading-list entries by topic",
        created_at=NOW,
    )


def verify(preview, contract_value, tmp_path: Path):
    return verify_created_skill(
        preview,
        contract_value,
        observable_signal=contract_value.success_evidence[0],
        verified_at=NOW,
        evidence_root=tmp_path / "evidence",
    )


def test_success_looking_file_never_proves_the_real_job_outcome(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    Path(preview.target_path).write_text(preview.content, encoding="utf-8")

    result = verify(preview, contract(), tmp_path)

    assert result.verdict is VerificationVerdict.UNKNOWN
    assert result.capability_state is CapabilityState.UNKNOWN
    assert result.evidence_state is EvidenceState.UNVERIFIED
    assert result.evidence_level is EvidenceLevel.UNKNOWN
    assert result.evidence_reference is None


def test_unsupported_free_text_signal_is_unknown_without_an_artifact(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    Path(preview.target_path).write_text(preview.content, encoding="utf-8")

    result = verify(preview, contract(signal="The reading list looks better"), tmp_path)

    assert result.verdict is VerificationVerdict.UNKNOWN
    assert result.evidence_state is EvidenceState.UNVERIFIED
    assert result.evidence_reference is None


def test_sabotaged_procedure_is_unknown_not_working(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    Path(preview.target_path).write_text(preview.content, encoding="utf-8")

    monkeypatch.setattr(Path, "read_bytes", lambda _self: (_ for _ in ()).throw(OSError()))
    result = verify(preview, contract(), tmp_path)

    assert result.verdict is VerificationVerdict.UNKNOWN
    assert result.capability_state is CapabilityState.UNKNOWN


def test_caller_verdict_callback_is_not_an_accepted_api() -> None:
    assert "outcome_verifier" not in inspect.signature(verify_created_skill).parameters


def test_wrong_contract_or_signal_is_not_demonstrated(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    Path(preview.target_path).write_text(preview.content, encoding="utf-8")
    other = contract()
    forged = other.model_copy(update={"job_id": "other-job"})

    result = verify_created_skill(
        preview,
        forged,
        observable_signal=CREATED_SKILL_OUTCOME_SIGNAL,
        verified_at=NOW,
        evidence_root=tmp_path / "evidence",
    )
    assert result.verdict is VerificationVerdict.NOT_DEMONSTRATED


def test_missing_evidence_root_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    Path(preview.target_path).write_text(preview.content, encoding="utf-8")
    result = verify_created_skill(
        preview,
        contract(),
        observable_signal=CREATED_SKILL_OUTCOME_SIGNAL,
        verified_at=NOW,
    )
    assert result.verdict is VerificationVerdict.UNKNOWN


@pytest.mark.parametrize("name", ["outcome_verifier", "verdict"])
def test_no_caller_owned_verdict_surface(name: str) -> None:
    assert name not in inspect.signature(verify_created_skill).parameters
