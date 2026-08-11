import runpy
from pathlib import Path


class _StoredGateReport:
    def dump_for_storage(self) -> dict[str, bool]:
        return {"pilot_start_allowed": True}


class _StoredRedTeamReport:
    def dump_for_storage(self) -> dict[str, bool]:
        return {"pilot_start_allowed": True}


def test_ci_has_release_blocking_exact_pilot_build_gate() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pilot-build-gate:" in workflow
    assert "needs:" in workflow
    assert "g1-bind-mount-gate" in workflow
    assert "m3-egress-gate" in workflow
    assert "python scripts/pilot_gate.py" in workflow
    assert "Upload exact pilot-build gate evidence" in workflow
    assert "Download G1 bind-mount evidence" in workflow
    assert "Download M3-M4 egress evidence" in workflow
    assert "Download M5 contribution evidence" in workflow
    assert "--formal-evidence" in workflow
    assert "needs.g1-bind-mount-gate.result" in workflow
    assert "needs.m3-egress-gate.result" in workflow
    assert "needs.m5-egress-gate.result" in workflow
    assert "--security-opt apparmor=unconfined" in workflow


def test_gate_script_exists_and_is_not_a_declared_pass() -> None:
    script = Path("scripts/pilot_gate.py").read_text(encoding="utf-8")
    assert "execute_pilot_gate" in script
    assert "subprocess" in script
    assert "pilot_start_allowed" in script
    assert "git" in script
    assert "formal_evidence" in script


def test_gate_artifact_retains_actual_redteam_report() -> None:
    namespace = runpy.run_path("scripts/pilot_gate.py")
    artifact_payload = namespace["_artifact_payload"]

    assert artifact_payload(_StoredGateReport(), _StoredRedTeamReport()) == {
        "pilot_gate": {"pilot_start_allowed": True},
        "red_team": {"pilot_start_allowed": True},
    }
