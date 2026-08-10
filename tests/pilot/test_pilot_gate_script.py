from pathlib import Path


def test_ci_has_release_blocking_exact_pilot_build_gate() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pilot-build-gate:" in workflow
    assert "needs:" in workflow
    assert "g1-bind-mount-gate" in workflow
    assert "m3-egress-gate" in workflow
    assert "python scripts/pilot_gate.py" in workflow
    assert "Upload exact pilot-build gate evidence" in workflow


def test_gate_script_exists_and_is_not_a_declared_pass() -> None:
    script = Path("scripts/pilot_gate.py").read_text(encoding="utf-8")
    assert "execute_pilot_gate" in script
    assert "subprocess" in script
    assert "pilot_start_allowed" in script
