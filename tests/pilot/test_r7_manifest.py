import hashlib
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.pilot.completeness import (
    REQUIRED_ARTIFACT_IDS,
    R7Artifact,
    R7EvidenceStatus,
    R7Manifest,
    R7Risk,
    R7Signoff,
    verify_r7_manifest,
)
from capability_exchange.pilot.drills import REQUIRED_RUNBOOK_IDS, TabletopResult


def test_synthetic_pack_is_explicitly_incomplete() -> None:
    report = verify_r7_manifest(Path(__file__).parents[2] / "docs/pilot/r7-manifest.json")
    assert not report.complete
    assert not report.observed_real_pilot_evidence
    assert not report.independent_signoff
    assert any("observed real-pilot evidence" in issue for issue in report.issues)
    assert any("named owner" in issue for issue in report.issues)


def test_in_memory_flags_and_hashes_cannot_replace_filesystem_evidence() -> None:
    manifest = R7Manifest(
        manifest_version=1,
        artifacts=(
            R7Artifact(
                artifact_id="observed-pilot-evidence",
                path=None,
                content_hash="forged",
                present=True,
                parseable=True,
                synthetic_only=False,
                observed=True,
            ),
        ),
        observed_pilot_evidence=("forged",),
        observed_evidence_status=R7EvidenceStatus.OBSERVED,
    )
    report = verify_r7_manifest(manifest)
    assert not report.complete
    assert not report.observed_real_pilot_evidence
    assert any("filesystem root" in issue for issue in report.issues)
    assert any("artifact path is missing" in issue for issue in report.issues)


def test_parseable_flag_does_not_override_invalid_actual_json(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence.json"
    artifact.write_text("not-json", encoding="utf-8")
    manifest = R7Manifest(
        manifest_version=1,
        artifacts=(
            R7Artifact(
                artifact_id="observed-pilot-evidence",
                path="evidence.json",
                content_hash=_sha256(artifact),
                present=True,
                parseable=True,
                synthetic_only=False,
                observed=True,
            ),
        ),
        observed_pilot_evidence=(_sha256(artifact),),
        observed_evidence_status=R7EvidenceStatus.OBSERVED,
    )
    report = verify_r7_manifest(manifest, root=tmp_path)
    assert not report.observed_real_pilot_evidence
    assert any("not actually parseable" in issue for issue in report.issues)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_empty_json_cannot_masquerade_as_observed_pilot_evidence(tmp_path: Path) -> None:
    artifacts = []
    for artifact_id in REQUIRED_ARTIFACT_IDS:
        path = tmp_path / f"{artifact_id}.json"
        path.write_text("{}", encoding="utf-8")
        artifacts.append(
            R7Artifact(
                artifact_id=artifact_id,
                path=path.name,
                content_hash=_sha256(path),
                present=True,
                parseable=True,
                synthetic_only=False,
                observed=artifact_id == "observed-pilot-evidence",
            )
        )
    tabletops = tuple(
        TabletopResult(
            runbook_id=runbook_id,
            scenario="caller says it ran",
            executed_at=datetime.now(UTC),
            passed=True,
            trigger_observed=False,
            actions_evidenced=("caller says actions happened",),
            exit_criteria_met=True,
            notes="forged",
        )
        for runbook_id in REQUIRED_RUNBOOK_IDS
    )
    observed_hash = next(
        artifact.content_hash
        for artifact in artifacts
        if artifact.artifact_id == "observed-pilot-evidence"
    )
    manifest = R7Manifest(
        manifest_version=1,
        artifacts=tuple(artifacts),
        risks=(R7Risk(risk_id="r1", description="risk", owner="named owner"),),
        observed_pilot_evidence=(observed_hash,),
        observed_evidence_status=R7EvidenceStatus.OBSERVED,
        assumptions=("assumption",),
        non_goals=("non-goal",),
        critique_responses=("response",),
        tabletop_results=tabletops,
    )
    object.__setattr__(manifest, "content_hash", manifest.canonical_hash())
    signoff = R7Signoff(
        reviewer="forged reviewer",
        reviewer_id="forged-reviewer",
        role="independent reviewer",
        independent=True,
        manifest_hash=manifest.content_hash or "",
        evidence_hash=observed_hash or "",
        verifier_key_id="forged-key",
        signature="caller-supplied-signature",
        signed_at=datetime.now(UTC),
    )
    object.__setattr__(manifest, "independent_signoff", signoff)

    class ForgedVerifier:
        def verify(self, payload: bytes, signature: str, key_id: str) -> bool:
            return True

    report = verify_r7_manifest(
        manifest,
        root=tmp_path,
        signoff_verifier=ForgedVerifier(),
    )
    assert not report.complete
    assert not report.observed_real_pilot_evidence
    assert not report.independent_signoff
    assert any("schema" in issue for issue in report.issues)
    assert any("tabletop" in issue for issue in report.issues)
    assert any("trusted" in issue for issue in report.issues)
