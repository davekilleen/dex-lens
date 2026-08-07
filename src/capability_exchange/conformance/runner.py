"""Run the whole conformance suite against one adapter (HANDOFF 5.4).

The runner drives one entire inspection of the given system root, wraps it
in the zero-writes witness, and evaluates every check. An adapter that
refuses the inspection honestly (containment unavailable on this host,
G1 fail-closed) yields ``refused-honestly`` outcomes for the checks that
needed the inspection — after the refusal itself has been verified — and
that is reported loudly, never silently upgraded to a pass.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from capability_exchange.conformance.checks import (
    CheckOutcome,
    CheckResult,
    check_contract_declaration_completeness,
    check_honest_fallback,
    check_result_envelope_conformance,
    check_snapshot_semantics,
    tree_identity,
)

if TYPE_CHECKING:
    from capability_exchange.conformance.subject import AdapterConformanceSubject

__all__ = ["ConformanceReport", "format_report", "run_conformance_suite"]


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    """Every check outcome for one adapter run. No aggregate score exists —
    only pass/fail per named check (the axes stay separate, HANDOFF M-D)."""

    adapter_id: str
    system_root: str
    results: tuple[CheckResult, ...]

    @property
    def failed(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.outcome is CheckOutcome.FAILED)

    @property
    def refused_honestly(self) -> tuple[CheckResult, ...]:
        return tuple(
            r for r in self.results if r.outcome is CheckOutcome.REFUSED_HONESTLY
        )

    @property
    def conformant(self) -> bool:
        """True when nothing failed. An honest refusal is not a failure —
        and not a full pass either; consumers must read the outcomes."""
        return not self.failed

    @property
    def fully_passed(self) -> bool:
        return all(r.outcome is CheckOutcome.PASSED for r in self.results)


def _zero_writes_and_envelope(
    subject: AdapterConformanceSubject, system_root: Path
) -> tuple[CheckResult, CheckResult]:
    """The zero-writes proof around one entire inspection, plus the
    envelope-conformance verdict for the envelope that inspection produced."""
    zero_id, envelope_id = "zero-writes-proof", "result-envelope-conformance"
    roots = [str(system_root)]
    contract = subject.build_contract(roots)
    before = tree_identity(system_root)
    try:
        envelope = subject.inspect(roots)
    except subject.refusal_error as refusal:
        after = tree_identity(system_root)
        if after != before:
            return (
                CheckResult(
                    check_id=zero_id,
                    gate="G1",
                    outcome=CheckOutcome.FAILED,
                    detail="the refusal path itself modified the inspected tree",
                ),
                CheckResult(
                    check_id=envelope_id,
                    gate="R2",
                    outcome=CheckOutcome.FAILED,
                    detail="not evaluated: the refusal path modified the inspected tree",
                ),
            )
        guidance = getattr(refusal, "fallback_guidance", "")
        refused = CheckOutcome.REFUSED_HONESTLY if str(guidance).strip() else (
            CheckOutcome.FAILED
        )
        detail = (
            "adapter refused the inspection with fallback guidance (containment "
            "unavailable on this host); inspected tree verified untouched"
            if refused is CheckOutcome.REFUSED_HONESTLY
            else "adapter refused the inspection but carried no fallback guidance"
        )
        return (
            CheckResult(check_id=zero_id, gate="G1", outcome=refused, detail=detail),
            CheckResult(
                check_id=envelope_id,
                gate="R2",
                outcome=refused,
                detail="not evaluated: no envelope was produced (honest refusal)",
            ),
        )
    after = tree_identity(system_root)
    if after != before:
        changed = sorted(
            path
            for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        )
        zero = CheckResult(
            check_id=zero_id,
            gate="G1",
            outcome=CheckOutcome.FAILED,
            detail=(
                f"the inspected tree changed across the inspection "
                f"({len(changed)} path(s), first: {changed[0]!r})"
            ),
        )
    else:
        zero = CheckResult(
            check_id=zero_id,
            gate="G1",
            outcome=CheckOutcome.PASSED,
            detail=(
                f"full recursive identity of {len(before)} path(s) byte-identical "
                f"across the entire inspection"
            ),
        )
    return (zero, check_result_envelope_conformance(contract, envelope))


def run_conformance_suite(
    subject: AdapterConformanceSubject,
    system_root: Path,
    *,
    workspace: Path | None = None,
) -> ConformanceReport:
    """Every M1 check against one adapter over one system root.

    ``workspace`` is where the suite builds its own scratch trees (snapshot
    semantics); it must not be inside ``system_root``. Defaults to a fresh
    temporary directory.
    """
    system_root = system_root.resolve()
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="conformance-workspace-"))
    workspace = workspace.resolve()
    if str(workspace).startswith(str(system_root)):
        raise ValueError(
            "the conformance workspace may not live inside the inspected root"
        )

    results: list[CheckResult] = []
    results.append(
        check_contract_declaration_completeness(subject, [str(system_root)])
    )
    zero_writes, envelope_conformance = _zero_writes_and_envelope(subject, system_root)
    results.append(zero_writes)
    results.append(envelope_conformance)
    results.append(check_snapshot_semantics(subject, workspace))
    results.append(check_honest_fallback(subject, [str(system_root)], system_root))
    return ConformanceReport(
        adapter_id=subject.adapter_id,
        system_root=str(system_root),
        results=tuple(results),
    )


def format_report(report: ConformanceReport) -> str:
    """Plain-text rendering: one line per check, no aggregate score."""
    lines = [
        f"Host Adapter conformance — {report.adapter_id}",
        f"system root: {report.system_root}",
        "",
    ]
    for result in report.results:
        marker = {
            CheckOutcome.PASSED: "PASS",
            CheckOutcome.FAILED: "FAIL",
            CheckOutcome.REFUSED_HONESTLY: "REFUSED-HONESTLY",
        }[result.outcome]
        lines.append(f"[{marker}] ({result.gate}) {result.check_id}: {result.detail}")
    lines.append("")
    if report.failed:
        lines.append(
            f"NON-CONFORMANT: {len(report.failed)} check(s) failed — this "
            f"adapter must not ship (HANDOFF 5.4)."
        )
    elif report.refused_honestly:
        lines.append(
            "CONTAINMENT UNAVAILABLE ON THIS HOST: the adapter refused "
            "honestly; deep inspection is disabled here and diagnosis falls "
            "back to guided/export-assisted evidence."
        )
    else:
        lines.append("CONFORMANT: every check passed.")
    return "\n".join(lines)
