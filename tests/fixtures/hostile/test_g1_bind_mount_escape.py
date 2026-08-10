"""G1 hostile fixture (2), bind-mount variant (gates.md; HANDOFF 5.1).

``mount --bind ~/.ssh <approved-root>/vendor-cache`` inside a single
filesystem is the escape the device check and ``os.path.ismount`` both miss:
same ``st_dev``, own inode, and ``realpath`` does not unwind it. Before this
fixture existed the allowlist admitted every byte underneath with no
exclusion record.

The mount needs ``CAP_SYS_ADMIN`` in the namespace owning it and is only
visible inside that mount namespace, so the whole assertion runs in a child
under ``unshare --user --map-root-user --mount`` (see
:mod:`tests.fixtures.hostile.bind_mount_child`).

**Where the mount cannot be made, this file skips — loudly.** The skip
reason carries the kernel's own refusal (and ``-rs`` is on by default in
``pyproject.toml``, so every skip prints its reason), and the always-running
test below raises a warning so the gap also appears in the warnings summary.
Per gates.md G1's fail-closed rule, a containment property that cannot be
proven on a host is not a property that host has; an unproven fixture must
be audible rather than indistinguishable from a passing one.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHILD_MODULE = "tests.fixtures.hostile.bind_mount_child"

#: `unshare -Umr` on GitHub's ubuntu runners gives an unprivileged user
#: namespace with CAP_SYS_ADMIN, which is all a bind mount needs.
_UNSHARE_ARGS = ["unshare", "--user", "--map-root-user", "--mount"]


def _namespace_unavailable_reason() -> str | None:
    """None when this host can host the fixture; else why it cannot."""
    if sys.platform != "linux":
        return f"bind mounts are a Linux facility; this host is {sys.platform!r}"
    if os.environ.get("G1_BIND_MOUNT_DIRECT") == "1":
        # The dedicated CI image grants the child CAP_SYS_ADMIN directly, so
        # it does not need a nested user namespace. Ordinary matrix runs keep
        # the unshare probe below and remain loudly skipped when unavailable.
        return None
    if shutil.which("unshare") is None:
        return "util-linux `unshare` is not installed on this host"
    probe = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [*_UNSHARE_ARGS, sys.executable, "-c", "pass"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip().replace("\n", "; ")
        return f"unprivileged user namespaces are unavailable here: {detail}"
    return None


_UNAVAILABLE = _namespace_unavailable_reason()

_UNPROVEN_WARNING = (
    "G1 hostile fixture 'bind-mount-escape' did NOT run on this host: "
    f"{_UNAVAILABLE}. The bind-mount containment property is therefore "
    "unproven here and must be proven on a CI leg that can create a user "
    "namespace (gates.md G1 fixture 2; HANDOFF 5.1)."
)


def test_g1_bind_mount_gate_rejects_skips_missing_reports_and_failed_assertions(
    tmp_path: Path,
) -> None:
    """The privileged gate must never turn an unproven fixture green."""
    gate_path = _REPO_ROOT / "scripts" / "g1_bind_mount_gate.py"
    assert gate_path.is_file(), "the CI gate script must be shipped"
    spec = importlib.util.spec_from_file_location("g1_bind_mount_gate", gate_path)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    validate = getattr(gate, "validate_gate_evidence", None)
    assert callable(validate), "gate must expose a fail-closed evidence validator"

    missing_report = tmp_path / "missing.json"
    with pytest.raises(gate.GateFailure, match="missing child report"):
        validate(returncode=0, output="1 passed", report_path=missing_report)

    skipped_report = tmp_path / "skipped.json"
    with pytest.raises(gate.GateFailure, match="skipped|unproven"):
        validate(returncode=0, output="1 skipped", report_path=skipped_report)

    failed_report = tmp_path / "failed.json"
    failed_report.write_text(json.dumps({"escape": {"canary_readable_through_mount": False}}))
    with pytest.raises(gate.GateFailure, match="containment"):
        validate(returncode=0, output="1 passed", report_path=failed_report)


def test_g1_bind_mount_fixture_is_never_silently_skipped() -> None:
    """Always runs. Makes an unrunnable hostile fixture audible.

    A skipped containment fixture is an unproven gate, and an unproven gate
    that nobody can see is indistinguishable from a passing one. This test
    does not assert the fixture ran — it asserts the *absence* is announced.
    """
    if _UNAVAILABLE is not None:
        warnings.warn(_UNPROVEN_WARNING, UserWarning, stacklevel=1)
    payload = _REPO_ROOT / (_CHILD_MODULE.replace(".", os.sep) + ".py")
    assert payload.is_file(), (
        "the bind-mount fixture payload must exist even on hosts that cannot run it"
    )


@pytest.fixture(scope="module")
def bind_mount_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if _UNAVAILABLE is not None:
        pytest.skip(_UNPROVEN_WARNING)
    base = tmp_path_factory.mktemp("bind-mount-escape")
    prefix = [] if os.environ.get("G1_BIND_MOUNT_DIRECT") == "1" else _UNSHARE_ARGS
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [*prefix, sys.executable, "-m", _CHILD_MODULE, str(base)],
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                (str(_REPO_ROOT / "src"), str(_REPO_ROOT), os.environ.get("PYTHONPATH", ""))
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 3:  # EXIT_MOUNT_UNAVAILABLE
        pytest.skip(
            "G1 hostile fixture 'bind-mount-escape' could not create the mount "
            f"even inside a user namespace: {completed.stderr.strip()}. The "
            "bind-mount containment property is unproven on this host."
        )
    assert completed.returncode == 0, (
        f"the bind-mount fixture child failed (exit {completed.returncode}):\n"
        f"{completed.stderr}"
    )
    report = json.loads(completed.stdout)
    artifact = os.environ.get("G1_BIND_MOUNT_REPORT")
    if artifact:
        Path(artifact).write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    return report


def test_g1_bind_mount_fixture_really_reproduces_the_hole(bind_mount_report: dict) -> None:
    """The fixture must be the escape, not a decoration of one.

    If any of these stop holding, the bind mount is no longer the case the
    old checks missed and a pass below would be meaningless.
    """
    escape = bind_mount_report["escape"]
    assert escape["canary_readable_through_mount"], "the mount did not take effect"
    assert escape["decoy_hidden_by_mount"], "the mount did not shadow the real directory"
    assert escape["same_device_as_approved_root"], (
        "cross-device mount: the pre-existing st_dev check would have caught this, "
        "so it does not exercise the bind-mount hole"
    )
    assert escape["ismount_says_no"], (
        "os.path.ismount detected this mount, so it does not exercise the hole "
        "the pruning check missed"
    )
    assert escape["realpath_stays_inside_root"], "realpath unwound the mount unexpectedly"


def test_g1_bind_mounted_directory_refused_with_honest_record(
    bind_mount_report: dict,
) -> None:
    assert bind_mount_report["dir_decision"]["verdict"] == "blocked"
    assert bind_mount_report["dir_decision"]["reason"] == "mount-point-crossing"
    assert bind_mount_report["mount_points_inside_scope"], (
        "the allowlist must record the mount it found inside the approved scope"
    )
    assert "mount-point-crossing" in bind_mount_report["exclusion_reasons"]


def test_g1_file_behind_the_bind_mount_refused(bind_mount_report: dict) -> None:
    assert bind_mount_report["key_decision"]["verdict"] == "blocked"
    assert bind_mount_report["key_decision"]["reason"] == "mount-point-crossing"


def test_g1_bind_mounted_bytes_never_reach_snapshot_or_envelope(
    bind_mount_report: dict,
) -> None:
    admitted = bind_mount_report["admitted_relative_paths"]
    captured = bind_mount_report["snapshot_relative_paths"]
    assert not any("vendor-cache" in path for path in admitted), admitted
    assert not any("vendor-cache" in path for path in captured), captured
    assert not bind_mount_report["canary_in_snapshot"]
    assert not bind_mount_report["canary_in_envelope"]
