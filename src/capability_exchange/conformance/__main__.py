"""Run the Host Adapter conformance suite from the command line.

Runnable, not prose (HANDOFF 5.4)::

    python -m capability_exchange.conformance --adapter claude-code-local --root PATH
    python -m capability_exchange.conformance --adapter claude-code-local --self-check

``--self-check`` builds a benign synthetic system in a scratch workspace
and runs the suite against it — the CI entry point.

Exit status:

===  ==========================================================================
0    every check that ran passed, and nothing was waived that the caller
     required
1    at least one check FAILED — the adapter is non-conformant
2    usage error (unknown adapter, root that is not a directory)
3    checks were waived because OS-enforced containment could not be
     established, and ``--require-os-enforcement`` was in effect
===  ==========================================================================

Status 3 exists because the two situations it separates are genuinely
different. An honest containment refusal is *correct product behavior*
(G1 fail-closed: the deep adapter disables itself and diagnosis downgrades
to guided/export-assisted evidence) and the refusal path is itself verified
before the waiver is granted. It is *not* evidence of containment, so it
must not satisfy a release gate: a run that proves only that the adapter
declined to run would let a broken macOS sandbox profile — or a wheel that
shipped without the profile at all — go green forever.

``--require-os-enforcement`` therefore defaults **on** wherever ``CI`` is
set in the environment, and CI passes it explicitly as well so the gate
never depends on that inference. Developers on a host without containment
get the tolerant default; use ``--no-require-os-enforcement`` to force it.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from capability_exchange.conformance.registry import (
    UnknownAdapterError,
    conformance_subject_for,
    registered_adapter_ids,
)
from capability_exchange.conformance.runner import format_report, run_conformance_suite


def _build_self_check_system(workspace: Path) -> Path:
    root = workspace / "self-check-system"
    (root / ".claude" / "skills" / "demo").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("Synthetic instructions for the self-check.\n")
    (root / ".claude" / "settings.json").write_text('{"model": "opus"}\n')
    (root / ".claude" / "skills" / "demo" / "SKILL.md").write_text("# demo skill\n")
    (root / "notes.md").write_text("Synthetic weekly notes.\n")
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m capability_exchange.conformance",
        description="Runnable Host Adapter conformance suite (HANDOFF 5.4).",
    )
    parser.add_argument(
        "--adapter",
        default="claude-code-local",
        help=f"adapter id to drive (registered: {', '.join(registered_adapter_ids())})",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--root", type=Path, help="system root to inspect (read-only) during the run"
    )
    scope.add_argument(
        "--self-check",
        action="store_true",
        help="build a benign synthetic system in a scratch workspace and run against it",
    )
    parser.add_argument(
        "--require-os-enforcement",
        action=argparse.BooleanOptionalAction,
        default=bool(os.environ.get("CI")),
        help=(
            "treat checks waived for unavailable OS containment as a gate "
            "failure (exit 3). An honest refusal remains correct product "
            "behavior; it is simply not proof of containment. "
            "Default: on when CI is set in the environment."
        ),
    )
    arguments = parser.parse_args(argv)

    try:
        subject = conformance_subject_for(arguments.adapter)
    except UnknownAdapterError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    workspace = Path(tempfile.mkdtemp(prefix="conformance-"))
    system_root = (
        _build_self_check_system(workspace) if arguments.self_check else arguments.root
    )
    if not system_root.is_dir():
        print(f"system root {system_root} is not a directory", file=sys.stderr)
        return 2

    report = run_conformance_suite(subject, system_root, workspace=workspace / "scratch")
    print(format_report(report, require_os_enforcement=arguments.require_os_enforcement))
    if not report.conformant:
        return 1
    if arguments.require_os_enforcement and not report.os_enforcement_established:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
