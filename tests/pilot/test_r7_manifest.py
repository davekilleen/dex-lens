from pathlib import Path

from capability_exchange.pilot.completeness import (
    R7Artifact,
    R7EvidenceStatus,
    R7Manifest,
    verify_r7_manifest,
)


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
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
