"""``dex-lens reports``: keep the diagnosis, and find the last one.

The skill ends every diagnosis by saving it here, which buys two things a
chat transcript cannot. The person can find the report a month later without
having kept the conversation. And the *next* run can read the last one, so it
can say what changed rather than repeating findings the person already knows
about — which is the difference between a recurring check worth keeping and
one that gets switched off.

Exit codes are meaningful because an agent reads them: 0 means the command did
what it said, 1 means there was nothing to show (no report saved yet), and 2
means the request itself was wrong.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from capability_exchange.reports.store import (
    LensReportStore,
    default_report_directory,
    missing_report_requirements,
)

__all__ = ["reports_main"]


def _store(inspected_root: Path | None) -> LensReportStore:
    """The report store, with the read-only promise checked on the way in.

    Passing the inspected folder is not bookkeeping: it is what makes the
    guarantee provable at the moment it matters. If app storage ever sat
    inside the folder being diagnosed, saving a report would write into the
    system Lens promised never to touch, and this raises instead.
    """
    roots = (inspected_root,) if inspected_root is not None else ()
    return LensReportStore(default_report_directory(roots))


def _read_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    path = Path(source).expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def reports_main(argv: list[str] | None = None) -> int:
    """List past diagnoses, print the last one, or save a new one."""

    parser = argparse.ArgumentParser(
        prog="dex-lens reports",
        description=(
            "Dated diagnosis reports, kept outside the folder they describe. "
            "With no arguments, lists what has been saved on this machine."
        ),
    )
    parser.add_argument(
        "--last",
        action="store_true",
        help="Print the most recent report instead of listing them.",
    )
    parser.add_argument(
        "--label",
        help="Only reports saved under this label, for one system among several.",
    )
    actions = parser.add_subparsers(dest="action")

    save = actions.add_parser(
        "save",
        help="Save a report. Give a file, or `-` to read it from standard input.",
    )
    save.add_argument("source", help="Markdown file holding the report, or `-` for stdin.")
    save.add_argument(
        "--label",
        default="diagnosis",
        help="A short name for the system this describes, so several can coexist.",
    )
    save.add_argument(
        "--for",
        dest="inspected_root",
        type=Path,
        help=(
            "The folder this report is about. Given, the command proves the "
            "report is being written outside it before writing anything."
        ),
    )

    check = actions.add_parser(
        "check",
        help="Say whether a report is complete enough to save, and save nothing.",
    )
    check.add_argument("source", help="Markdown file holding the report, or `-` for stdin.")

    actions.add_parser("list", help="List saved reports, newest first.")

    last = actions.add_parser("last", help="Print the most recent saved report.")
    last.add_argument(
        "--path-only",
        action="store_true",
        help="Print only where the most recent report is, not its contents.",
    )

    args = parser.parse_args(argv)
    action = args.action or ("last" if args.last else "list")

    if action == "save":
        return _save(args)
    if action == "check":
        return _check(args)
    return _show(action, args)


def _report_problems(problems: list[str]) -> None:
    print(
        "dex-lens: this report is not finished. A diagnosis is only worth "
        "keeping if it shows its evidence:",
        file=sys.stderr,
    )
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)


def _check(args: argparse.Namespace) -> int:
    """Say what a report still needs, and write nothing either way."""
    try:
        markdown = _read_source(args.source)
    except FileNotFoundError as exc:
        print(f"dex-lens: no such report file: {exc.args[0]}", file=sys.stderr)
        return 2
    problems = missing_report_requirements(markdown)
    if problems:
        _report_problems(problems)
        return 2
    print("dex-lens: this report shows its evidence and is ready to save.", file=sys.stderr)
    return 0


def _save(args: argparse.Namespace) -> int:
    try:
        markdown = _read_source(args.source)
    except FileNotFoundError as exc:
        print(f"dex-lens: no such report file: {exc.args[0]}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"dex-lens: could not read the report: {exc}", file=sys.stderr)
        return 2

    if not markdown.strip():
        # Said plainly and first: an empty file is a different mistake from an
        # unfinished report, and listing four missing sections would bury it.
        print("dex-lens: a report with no content is not a report", file=sys.stderr)
        return 2

    # The evidence rule is checked here, where skipping it is not an option
    # that exists. A rule that lives only in the skill's prose holds until the
    # run is long and the assistant is tired.
    problems = missing_report_requirements(markdown)
    if problems:
        _report_problems(problems)
        print(
            "dex-lens: nothing was saved. Fix these and save it again.",
            file=sys.stderr,
        )
        return 2

    try:
        store = _store(args.inspected_root)
    except ValueError as exc:
        print(f"dex-lens: {exc}", file=sys.stderr)
        return 2

    # Read before writing: once the new report is on disk it is the most
    # recent one, and the previous one is what the reader wants pointed out.
    previous = store.last(label=args.label)
    try:
        saved = store.save(markdown, label=args.label)
    except ValueError as exc:
        print(f"dex-lens: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"dex-lens: could not save the report: {exc}", file=sys.stderr)
        return 1

    print(saved.path)
    print(
        "dex-lens: report saved. It is outside the folder it describes, and "
        "nothing in that folder was changed.",
        file=sys.stderr,
    )
    if previous is not None:
        print(
            f"dex-lens: the previous one is {previous.path} "
            f"({previous.saved_at.strftime('%Y-%m-%d')}); "
            "read it to say what has changed since.",
            file=sys.stderr,
        )
    else:
        print(
            "dex-lens: this is the first report on this machine, so there is "
            "nothing yet to compare it with.",
            file=sys.stderr,
        )
    return 0


def _show(action: str, args: argparse.Namespace) -> int:
    try:
        store = _store(None)
    except ValueError as exc:
        print(f"dex-lens: {exc}", file=sys.stderr)
        return 2

    if action == "last":
        report = store.last(label=args.label)
        if report is None:
            print(
                "dex-lens: no report has been saved on this machine yet.",
                file=sys.stderr,
            )
            return 1
        if getattr(args, "path_only", False):
            print(report.path)
            return 0
        print(f"dex-lens: {report.path}", file=sys.stderr)
        print(report.read(), end="")
        return 0

    reports = store.list(label=args.label)
    if not reports:
        print(
            "dex-lens: no report has been saved on this machine yet. "
            "One is written at the end of each diagnosis.",
            file=sys.stderr,
        )
        return 1
    print(f"# Saved Dex Lens reports ({len(reports)}) in {store.directory}")
    print()
    for report in reports:
        print(f"- {report.listing_line()}")
        print(f"  `{report.path}`")
    return 0
