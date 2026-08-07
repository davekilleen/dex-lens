"""Run the Host Adapter conformance suite from the command line.

Runnable, not prose (HANDOFF 5.4)::

    python -m capability_exchange.conformance --adapter claude-code-local --root PATH
    python -m capability_exchange.conformance --adapter claude-code-local --self-check

``--self-check`` builds a benign synthetic system in a scratch workspace
and runs the suite against it — the CI entry point. Exit status 0 means no
check failed; an honest containment refusal is reported loudly and exits 0
only because refusing is the mandated fail-closed behavior, while any
FAILED check exits 1.
"""

from __future__ import annotations

import argparse
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
    print(format_report(report))
    return 0 if report.conformant else 1


if __name__ == "__main__":
    sys.exit(main())
