from pathlib import Path

from capability_exchange.pilot.completeness import verify_r7_manifest


def test_synthetic_pack_is_explicitly_incomplete() -> None:
    report = verify_r7_manifest(Path(__file__).parents[2] / "docs/pilot/r7-manifest.json")
    assert not report.complete
    assert not report.observed_real_pilot_evidence
    assert not report.independent_signoff
    assert any("observed real-pilot evidence" in issue for issue in report.issues)
    assert any("named owner" in issue for issue in report.issues)
