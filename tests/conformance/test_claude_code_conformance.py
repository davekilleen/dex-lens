"""The adapter conformance suite, run against the Claude Code deep adapter
in CI (HANDOFF 5.4) — under the host's real OS-enforced containment.

Gate-named tests: G1 (contract, zero-writes, snapshot semantics, honest
fallback) and R2 (result-envelope conformance).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from tests.fixtures.hostile.catalog import build_benign_system, build_credentialed_system

from capability_exchange.conformance import (
    CheckOutcome,
    check_contract_declaration_completeness,
    check_honest_fallback,
    check_result_envelope_conformance,
    check_snapshot_semantics,
    conformance_subject_for,
    format_report,
    run_conformance_suite,
)
from capability_exchange.conformance.__main__ import main as conformance_main
from capability_exchange.conformance.registry import claude_code_conformance_subject


@pytest.fixture
def subject():  # type: ignore[no-untyped-def]
    return conformance_subject_for("claude-code-local")


@pytest.fixture
def system_root(tmp_path: Path) -> Path:
    return build_benign_system(tmp_path / "system-home")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


def _outcomes(report):  # type: ignore[no-untyped-def]
    return {result.check_id: result.outcome for result in report.results}


class TestIndividualChecks:
    def test_g1_contract_declaration_completeness(self, subject, system_root) -> None:  # type: ignore[no-untyped-def]
        result = check_contract_declaration_completeness(subject, [str(system_root)])
        assert result.outcome is CheckOutcome.PASSED, result.detail
        assert result.gate == "G1"

    def test_g1_snapshot_semantics(self, subject, workspace) -> None:  # type: ignore[no-untyped-def]
        result = check_snapshot_semantics(subject, workspace)
        assert result.outcome is CheckOutcome.PASSED, result.detail

    def test_g1_honest_fallback_when_containment_unavailable(  # type: ignore[no-untyped-def]
        self, subject, system_root
    ) -> None:
        result = check_honest_fallback(subject, [str(system_root)], system_root)
        assert result.outcome is CheckOutcome.PASSED, result.detail

    def test_r2_result_envelope_conformance(self, subject, system_root) -> None:  # type: ignore[no-untyped-def]
        contract = subject.build_contract([str(system_root)])
        try:
            envelope = subject.inspect([str(system_root)])
        except subject.refusal_error as refusal:
            pytest.skip(f"containment unavailable on this host: {refusal}")
        result = check_result_envelope_conformance(contract, envelope)
        assert result.outcome is CheckOutcome.PASSED, result.detail
        assert result.gate == "R2"


class TestFullSuite:
    def test_g1_full_suite_conformant_for_claude_code(  # type: ignore[no-untyped-def]
        self, subject, system_root, workspace
    ) -> None:
        report = run_conformance_suite(subject, system_root, workspace=workspace)
        assert report.conformant, format_report(report)
        # On a host with working containment the suite fully passes; an
        # honest refusal is tolerated only as the mandated G1 downgrade.
        assert report.fully_passed or report.refused_honestly, format_report(report)

    def test_g1_zero_writes_proof_over_secret_bearing_system(  # type: ignore[no-untyped-def]
        self, subject, tmp_path
    ) -> None:
        root = build_credentialed_system(tmp_path / "cred-home")
        report = run_conformance_suite(subject, root, workspace=tmp_path / "ws")
        outcomes = _outcomes(report)
        assert outcomes["zero-writes-proof"] in (
            CheckOutcome.PASSED,
            CheckOutcome.REFUSED_HONESTLY,
        ), format_report(report)
        assert not report.failed, format_report(report)

    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="the default CLI gate requires live OS containment; macOS proves honest refusal",
    )
    def test_g1_cli_self_check_runs_green(self) -> None:
        assert conformance_main(["--adapter", "claude-code-local", "--self-check"]) == 0

    def test_g1_cli_refuses_unknown_adapter(self) -> None:
        assert conformance_main(["--adapter", "made-up-host", "--self-check"]) == 2


#: An extended-attribute name this platform will accept. Linux only permits
#: the ``user.`` namespace from an unprivileged process; macOS has no
#: namespace requirement.
XATTR_PROBE_NAME = (
    "dex.conformance-probe" if sys.platform == "darwin" else "user.dex-conformance-probe"
)


def set_extended_attribute(path: Path, name: str, value: bytes) -> None:
    """Set one extended attribute on ``path``, however this platform allows.

    ``os.setxattr`` is Linux-only in CPython, so a test written against it
    raises ``AttributeError`` on macOS — the pilot's platform — and stops
    exercising the witness exactly where it matters most. macOS goes
    through libc instead (the same syscall ``/usr/bin/xattr -w`` uses, minus
    the dependency on a system Python being installed). Raises ``OSError``
    when the filesystem has no extended-attribute support, which callers
    turn into an honest skip.

    Test-side only: the conformance instrument itself never writes.
    """
    if sys.platform != "darwin":
        os.setxattr(path, name, value)
        return
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.setxattr.restype = ctypes.c_int
    libc.setxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    if libc.setxattr(os.fsencode(path), name.encode(), value, len(value), 0, 0) != 0:
        errno_value = ctypes.get_errno()
        raise OSError(errno_value, os.strerror(errno_value), str(path))


def _honestly_refusing_subject():  # type: ignore[no-untyped-def]
    """A subject whose whole inspection takes the adapter's real refusal path.

    Not a stub: ``force_containment_unavailable`` drives the production
    ``contained_inspection`` with a strategy that genuinely cannot be
    established on this host, so the refusal, its typed error and its
    fallback guidance are the real ones.
    """
    honest = claude_code_conformance_subject()
    return replace(honest, inspect=honest.force_containment_unavailable)


class _SilentRefusal(Exception):
    """A refusal carrying no fallback guidance — dishonest, so it FAILS."""

    fallback_guidance = ""


class TestOsEnforcementIsRequiredOfTheGate:
    """An honest refusal is correct product behavior and a useless gate.

    G1 fail-closed says a host that cannot establish containment disables the
    deep adapter — that is right, and the runner keeps reporting it that way.
    But the CI step exists to prove containment *works*, and it reported
    green on a run that proved only that the adapter declined to start. A
    regression in the macOS sandbox profile, or a wheel built without it,
    would have shipped behind a green check indefinitely.
    """

    def test_g1_refusal_is_conformant_but_not_proof_of_enforcement(
        self, system_root, workspace
    ) -> None:  # type: ignore[no-untyped-def]
        report = run_conformance_suite(
            _honestly_refusing_subject(), system_root, workspace=workspace
        )
        assert report.refused_honestly, "the subject must actually have refused"
        assert report.conformant  # correct product behavior: nothing failed
        assert not report.os_enforcement_established  # and precisely not a proven gate
        assert not report.fully_passed

    def test_g1_report_says_loudly_that_the_gate_is_unsatisfied(
        self, system_root, workspace
    ) -> None:  # type: ignore[no-untyped-def]
        report = run_conformance_suite(
            _honestly_refusing_subject(), system_root, workspace=workspace
        )
        tolerant = format_report(report)
        strict = format_report(report, require_os_enforcement=True)
        assert "CONTAINMENT UNAVAILABLE ON THIS HOST" in tolerant
        assert "GATE NOT SATISFIED" not in tolerant
        assert "GATE NOT SATISFIED" in strict

    @staticmethod
    def _with_refusing_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
        import capability_exchange.conformance.__main__ as cli

        monkeypatch.setattr(
            cli, "conformance_subject_for", lambda _adapter: _honestly_refusing_subject()
        )

    def test_g1_cli_exits_nonzero_on_refusal_when_enforcement_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_refusing_adapter(monkeypatch)
        assert conformance_main(
            ["--adapter", "claude-code-local", "--self-check", "--require-os-enforcement"]
        ) == 3

    def test_g1_cli_still_exits_zero_when_enforcement_not_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The honest-refusal path itself stays intact: a developer on a host
        # without containment is not blocked — only a release gate is.
        self._with_refusing_adapter(monkeypatch)
        assert conformance_main(
            ["--adapter", "claude-code-local", "--self-check", "--no-require-os-enforcement"]
        ) == 0

    @pytest.mark.parametrize(("ci_value", "expected"), [("true", 3), ("1", 3), (None, 0)])
    def test_g1_cli_requires_enforcement_by_default_under_ci(
        self, monkeypatch: pytest.MonkeyPatch, ci_value: str | None, expected: int
    ) -> None:
        self._with_refusing_adapter(monkeypatch)
        if ci_value is None:
            monkeypatch.delenv("CI", raising=False)
        else:
            monkeypatch.setenv("CI", ci_value)
        assert conformance_main(["--adapter", "claude-code-local", "--self-check"]) == expected

    def test_g1_a_failed_check_outranks_the_unproven_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Non-conformant (1) must never be reported as merely unproven (3).
        import capability_exchange.conformance.__main__ as cli

        def silently_refusing(_adapter):  # type: ignore[no-untyped-def]
            def inspect(roots):  # type: ignore[no-untyped-def]
                raise _SilentRefusal("containment unavailable, and no guidance offered")

            return replace(
                claude_code_conformance_subject(),
                inspect=inspect,
                refusal_error=_SilentRefusal,
            )

        monkeypatch.setattr(cli, "conformance_subject_for", silently_refusing)
        assert conformance_main(
            ["--adapter", "claude-code-local", "--self-check", "--require-os-enforcement"]
        ) == 1


def _require_working_containment(subject, root: Path) -> None:  # type: ignore[no-untyped-def]
    try:
        subject.inspect([str(root)])
    except subject.refusal_error as refusal:
        pytest.skip(f"containment unavailable on this host: {refusal}")


class TestSuiteCatchesViolations:
    """The instrument itself must be able to fail — a suite that cannot
    detect a violation proves nothing."""

    def test_g1_detects_a_write_during_inspection(self, system_root, workspace) -> None:  # type: ignore[no-untyped-def]
        from dataclasses import replace

        honest = claude_code_conformance_subject()
        _require_working_containment(honest, system_root)

        def writing_inspect(roots):  # type: ignore[no-untyped-def]
            envelope = honest.inspect(roots)
            (Path(roots[0]) / "dropped-marker.txt").write_text("wrote during inspection")
            return envelope

        subject = replace(honest, inspect=writing_inspect)
        report = run_conformance_suite(subject, system_root, workspace=workspace)
        outcomes = _outcomes(report)
        assert outcomes["zero-writes-proof"] is CheckOutcome.FAILED
        assert not report.conformant

    def test_g1_detects_a_metadata_only_write_during_inspection(  # type: ignore[no-untyped-def]
        self, system_root, workspace
    ) -> None:
        """The zero-writes witness must see writes that change no content.

        An extended attribute set on an inspected file leaves content, size,
        mode and mtime untouched, so a content-and-stat-only witness reports
        a byte-identical tree while the person's system has in fact been
        modified. The witness covers xattrs on both platforms, so this runs
        on both — a macOS skip here would leave the pilot's platform with an
        unexercised witness.
        """
        from dataclasses import replace

        # Doubles as the support probe and as a pre-existing attribute: the
        # violation below rewrites the same name with a different value, so
        # a witness that only noticed names appearing would still fail here.
        target = next(p for p in system_root.rglob("*") if p.is_file())
        try:
            set_extended_attribute(target, XATTR_PROBE_NAME, b"before-inspection")
        except OSError as exc:
            pytest.skip(f"filesystem does not support extended attributes: {exc}")

        honest = claude_code_conformance_subject()
        _require_working_containment(honest, system_root)

        def xattr_writing_inspect(roots):  # type: ignore[no-untyped-def]
            envelope = honest.inspect(roots)
            victim = next(p for p in Path(roots[0]).rglob("*") if p.is_file())
            set_extended_attribute(victim, XATTR_PROBE_NAME, b"wrote during inspection")
            return envelope

        subject = replace(honest, inspect=xattr_writing_inspect)
        report = run_conformance_suite(subject, system_root, workspace=workspace)
        outcomes = _outcomes(report)
        assert outcomes["zero-writes-proof"] is CheckOutcome.FAILED, format_report(report)
        assert not report.conformant

    def test_r2_detects_a_contract_envelope_mismatch(self, system_root) -> None:  # type: ignore[no-untyped-def]
        subject = claude_code_conformance_subject()
        contract = subject.build_contract([str(system_root)])
        wrong = contract.model_copy(update={"adapter_id": "someone-else"})
        try:
            envelope = subject.inspect([str(system_root)])
        except subject.refusal_error as refusal:
            pytest.skip(f"containment unavailable on this host: {refusal}")
        result = check_result_envelope_conformance(wrong, envelope)
        assert result.outcome is CheckOutcome.FAILED
        assert "someone-else" in result.detail

    def test_g1_detects_a_snapshot_that_reads_live_disk(self, workspace) -> None:  # type: ignore[no-untyped-def]
        from dataclasses import replace

        class LiveDiskFake:
            def __init__(self, root: str) -> None:
                self._root = root

            def canonical_paths(self) -> tuple[str, ...]:
                base = Path(self._root)
                return tuple(sorted(str(p) for p in base.rglob("*") if p.is_file()))

            def content_of(self, canonical_path: str) -> bytes:
                return Path(canonical_path).read_bytes()  # live read: violation

        subject = replace(
            claude_code_conformance_subject(),
            capture_snapshot=lambda roots: LiveDiskFake(roots[0]),
        )
        result = check_snapshot_semantics(subject, workspace)
        assert result.outcome is CheckOutcome.FAILED
        assert "live" in result.detail

    def test_g1_detects_a_missing_honest_refusal(self, system_root) -> None:  # type: ignore[no-untyped-def]
        from dataclasses import replace

        honest = claude_code_conformance_subject()
        _require_working_containment(honest, system_root)

        def proceeds_anyway(roots):  # type: ignore[no-untyped-def]
            return honest.inspect(roots)  # never refuses: violation

        subject = replace(honest, force_containment_unavailable=proceeds_anyway)
        result = check_honest_fallback(subject, [str(system_root)], system_root)
        assert result.outcome is CheckOutcome.FAILED
        assert "never proceed" in result.detail
