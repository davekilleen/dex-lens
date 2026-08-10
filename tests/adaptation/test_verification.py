from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adaptation.allowlist import OperationRequest
from capability_exchange.adaptation.contract import OperationKind
from capability_exchange.adaptation.preview import build_preview
from capability_exchange.adaptation.verification import (
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


def contract() -> SuccessContract:
    return SuccessContract(
        job_id="reading-list",
        situation="When I save useful articles during the week",
        desired_outcome="My local reading list is grouped by topic",
        success_evidence=("New entries are grouped under topic headings",),
        boundaries=JobBoundaries(
            privacy_limits=("No article text leaves this machine",),
            approval_limits=("Ask before changing my Claude Code setup",),
            autonomy_limits=("Never send or publish the reading list",),
        ),
        importance=JobImportance.MEDIUM,
        cadence=JobCadence.WEEKLY,
        confirmed_at=NOW,
    )


def make_preview(root: Path):
    return build_preview(
        request=OperationRequest(
            operation=OperationKind.CREATE_NAMESPACED_SKILL,
            approved_root=str(root),
            relative_path="skills/dex-lens-reading-list/SKILL.md",
        ),
        host_id="claude-code-local",
        job_id="reading-list",
        capability_id="topic-grouping",
        content="# Skill\n",
        expected_benefit="Group reading-list entries by topic",
        created_at=NOW,
    )


def test_exact_file_and_declared_signal_verify_working(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    target = Path(preview.target_path)
    target.parent.mkdir(parents=True)
    target.write_text(preview.content, encoding="utf-8")

    result = verify_created_skill(
        preview,
        contract(),
        observable_signal="New entries are grouped under topic headings",
        verified_at=NOW,
    )
    assert result.verdict is VerificationVerdict.WORKING
    assert result.capability_state is CapabilityState.WORKING
    assert result.evidence_state is EvidenceState.OBSERVED
    assert result.evidence_level is EvidenceLevel.VERIFIED


def test_success_looking_file_without_contract_signal_is_not_demonstrated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    target = Path(preview.target_path)
    target.parent.mkdir(parents=True)
    target.write_text(preview.content, encoding="utf-8")

    result = verify_created_skill(
        preview,
        contract(),
        observable_signal="The file exists",
        verified_at=NOW,
    )
    assert result.verdict is VerificationVerdict.NOT_DEMONSTRATED
    assert result.evidence_state is EvidenceState.INSUFFICIENT
    assert result.evidence_level is EvidenceLevel.UNKNOWN


def test_sabotaged_verifier_is_unknown_unverified_and_never_working(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    preview = make_preview(root)
    target = Path(preview.target_path)
    target.parent.mkdir(parents=True)
    target.write_text(preview.content, encoding="utf-8")

    def fail_read(self: Path) -> bytes:
        raise OSError("sabotaged verifier")

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    result = verify_created_skill(
        preview,
        contract(),
        observable_signal="New entries are grouped under topic headings",
        verified_at=NOW,
    )
    assert result.verdict is VerificationVerdict.UNKNOWN
    assert result.capability_state is CapabilityState.UNKNOWN
    assert result.evidence_state is EvidenceState.UNVERIFIED
    assert result.evidence_level is EvidenceLevel.UNKNOWN

