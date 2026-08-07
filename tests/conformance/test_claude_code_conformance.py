"""The adapter conformance suite, run against the Claude Code deep adapter
in CI (HANDOFF 5.4) — under the host's real OS-enforced containment.

Gate-named tests: G1 (contract, zero-writes, snapshot semantics, honest
fallback) and R2 (result-envelope conformance).
"""

from __future__ import annotations

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

    def test_g1_cli_self_check_runs_green(self) -> None:
        assert conformance_main(["--adapter", "claude-code-local", "--self-check"]) == 0

    def test_g1_cli_refuses_unknown_adapter(self) -> None:
        assert conformance_main(["--adapter", "made-up-host", "--self-check"]) == 2


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
        """Adversarial M1 finding: the zero-writes witness must see writes
        that change no file *content*.

        An extended attribute set on an inspected file leaves content, size,
        mode and mtime untouched, so a content-and-stat-only witness reports
        a byte-identical tree while the person's system has in fact been
        modified. The witness must cover xattrs too.
        """
        import os
        from dataclasses import replace

        # os.setxattr is Linux-only in CPython; macOS exposes xattrs through
        # a different API that the witness reaches via os.listxattr when
        # present. Where the syscall wrappers are absent there is nothing to
        # simulate, so the probe is skipped rather than failed.
        if not hasattr(os, "setxattr") or not hasattr(os, "removexattr"):
            pytest.skip("os.setxattr/os.removexattr unavailable on this platform")

        target = next(p for p in system_root.rglob("*") if p.is_file())
        try:
            os.setxattr(target, "user.conformance-probe", b"x")
            os.removexattr(target, "user.conformance-probe")
        except OSError:
            pytest.skip("filesystem does not support user extended attributes")

        honest = claude_code_conformance_subject()
        _require_working_containment(honest, system_root)

        def xattr_writing_inspect(roots):  # type: ignore[no-untyped-def]
            envelope = honest.inspect(roots)
            victim = next(p for p in Path(roots[0]).rglob("*") if p.is_file())
            os.setxattr(victim, "user.sneaked", b"wrote during inspection")
            return envelope

        subject = replace(honest, inspect=xattr_writing_inspect)
        report = run_conformance_suite(subject, system_root, workspace=workspace)
        outcomes = _outcomes(report)
        assert outcomes["zero-writes-proof"] is CheckOutcome.FAILED
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
