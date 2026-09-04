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
import re
import sys
from pathlib import Path

from capability_exchange.catalogue.subscription import default_lens_app_storage
from capability_exchange.catalogue.v2 import (
    CatalogueVerificationError,
    VerifiedCatalogueStore,
    default_keyring,
)
from capability_exchange.diagnosis.comparison import ComparisonLedger
from capability_exchange.reports.ledger import load_and_validate_ledger
from capability_exchange.reports.store import (
    DEFAULT_LABEL,
    LensReportStore,
    SavedReport,
    default_report_directory,
    missing_comparison_with,
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
    """The report as written, or a refusal — never a traceback.

    A report that is not UTF-8 is refused rather than repaired: saving a
    mangled copy of someone's diagnosis under a dated name is worse than
    saying plainly that the file could not be read.
    """
    if source == "-":
        return sys.stdin.read()
    path = Path(source).expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


#: What `--label` means, in whichever position it is written. The help text is
#: shared for the same reason the option is: two spellings of one flag is how
#: it came to mean three different things.
_LABEL_HELP = (
    "A short name for the system this is about, so several can coexist. "
    "It decides which previous report a new one has to account for, and "
    "which reports are listed."
)


def _one_label(parser: argparse.ArgumentParser, args: argparse.Namespace) -> str | None:
    """The single label this invocation asked for, or ``None`` for all of them.

    `--label` is accepted before the action and after it, because both read
    naturally and the skill writes it after. What must not happen is the two
    positions meaning different things: the trailing one used to overwrite the
    leading one with its own default, so `reports --label my-vault save` filed
    the report under "diagnosis" and `reports --label my-vault list` then
    could not find it. Given twice with two different values, the request is
    ambiguous and is refused rather than guessed at.
    """
    leading, trailing = args.leading_label, args.trailing_label
    if leading is not None and trailing is not None and leading.strip() != trailing.strip():
        parser.error(
            f"--label was given twice, as {leading!r} and {trailing!r}. "
            "Give it once: it names one system."
        )
    return trailing if trailing is not None else leading


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
    parser.add_argument("--label", dest="leading_label", metavar="LABEL", help=_LABEL_HELP)
    parser.set_defaults(leading_label=None, trailing_label=None)
    actions = parser.add_subparsers(dest="action")

    save = actions.add_parser(
        "save",
        help="Save a report. Give a file, or `-` to read it from standard input.",
    )
    save.add_argument("source", help="Markdown file holding the report, or `-` for stdin.")
    save.add_argument(
        "--for",
        dest="inspected_root",
        type=Path,
        help=(
            "The folder this report is about. Given, the command proves the "
            "report is being written outside it before writing anything."
        ),
    )
    save.add_argument(
        "--ledger",
        type=Path,
        help="JSON ledger accounting for every entry in the verified Dex catalogue.",
    )

    check = actions.add_parser(
        "check",
        help="Say whether a report is complete enough to save, and save nothing.",
    )
    check.add_argument("source", help="Markdown file holding the report, or `-` for stdin.")
    check.add_argument(
        "--ledger",
        type=Path,
        help="JSON ledger accounting for every entry in the verified Dex catalogue.",
    )

    listing = actions.add_parser("list", help="List saved reports, newest first.")

    last = actions.add_parser("last", help="Print the most recent saved report.")
    last.add_argument(
        "--path-only",
        action="store_true",
        help="Print only where the most recent report is, not its contents.",
    )

    # One option, declared once and accepted after any action too, so that
    # `--label vault` means the same thing wherever the person writes it.
    for action_parser in (save, check, listing, last):
        action_parser.add_argument(
            "--label", dest="trailing_label", metavar="LABEL", help=_LABEL_HELP
        )

    args = parser.parse_args(argv)
    args.label = _one_label(parser, args)
    action = args.action or ("last" if args.last else "list")

    if action == "save":
        return _save(args)
    if action == "check":
        return _check(args)
    return _show(action, args)


def _gate(
    markdown: str,
    previous: SavedReport | None,
    ledger_problems: list[str] | None = None,
) -> list[str]:
    """Everything wrong with this report, in one place.

    Called by `save` and by `check` with the same inputs, because a `check`
    that approves what `save` then refuses is worse than no check at all: it
    is a green light that costs the reader a rewrite they were told they had
    already avoided.
    """
    problems = missing_report_requirements(markdown)
    unaccounted = missing_comparison_with(previous, markdown)
    if unaccounted is not None:
        problems.append(unaccounted)
    problems.extend(ledger_problems or [])
    return problems


#: The ledger digest a saved report records about itself, exactly as the
#: canonical fact block writes it. A report that carries this line has named
#: the one ledger it accounts for, so the ledger offered beside it has to be
#: that ledger — byte for byte, over every field the digest binds.
_RECORDED_LEDGER_DIGEST = re.compile(
    r"^- Ledger digest: (sha256:[0-9a-f]{64})\s*$", re.MULTILINE
)


def _ledger_binding_problems(markdown: str, ledger: ComparisonLedger | None) -> list[str]:
    """Whether the supplied ledger is the one this report says it accounts for.

    Validating the ledger against the catalogue proves the catalogue-owned
    rows, but the run-derived rows — insights, expectations, the work audit —
    have no external truth to re-derive them from. The report's own recorded
    digest is the only thing that binds them, so beside a supplied ledger the
    digest line is mandatory: a check that let its absence stand made the
    binding opt-out, and stripping one line from the report laundered any
    tamper of the run-derived rows. A report checked *without* a ledger makes
    no binding claim and nothing new is demanded of it.
    """
    if ledger is None:
        return []
    recorded = set(_RECORDED_LEDGER_DIGEST.findall(markdown))
    if not recorded:
        return [
            "this report records no ledger digest for the supplied ledger: a "
            "diagnosis that produced both writes the digest line into the "
            "report, so its absence means this is not the pair the diagnosis "
            "wrote. Re-run the diagnosis rather than editing either file."
        ]
    from capability_exchange.diagnosis.report import canonical_ledger_digest

    if recorded != {canonical_ledger_digest(ledger)}:
        return [
            "the supplied ledger does not match the ledger digest this report "
            "records: the saved ledger or the report changed after the "
            "diagnosis wrote them. Re-run the diagnosis rather than editing "
            "either file."
        ]
    return []


def _ledger_gate(path: Path | None) -> tuple[ComparisonLedger | None, list[str]]:
    """Validate a supplied ledger against the last locally verified catalogue."""
    if path is None:
        return None, [
            "add --ledger with the complete JSON comparison ledger produced from "
            "the verified catalogue"
        ]
    store = VerifiedCatalogueStore(default_lens_app_storage())
    try:
        state = store.load_last_verified_state(keyring=default_keyring())
    except CatalogueVerificationError as exc:
        return None, [f"the stored Dex catalogue could not be verified: {exc}"]
    if state.catalogue is None:
        return None, [
            "fetch and verify the Dex catalogue before checking a comparison ledger"
        ]
    return load_and_validate_ledger(path, state.catalogue)


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
    except UnicodeDecodeError:
        # Refused, not repaired: a dated file holding a mangled copy of the
        # diagnosis would be read by the next run as what was found.
        print(
            f"dex-lens: the report must be UTF-8 text, and {args.source} is not. "
            "Nothing was written.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"dex-lens: could not read the report: {exc}", file=sys.stderr)
        return 2
    try:
        store = _store(None)
    except ValueError as exc:
        print(f"dex-lens: {exc}", file=sys.stderr)
        return 2

    label = args.label or DEFAULT_LABEL
    ledger, ledger_problems = _ledger_gate(args.ledger)
    ledger_problems.extend(_ledger_binding_problems(markdown, ledger))
    problems = _gate(markdown, store.last(label=label), ledger_problems)
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
    except UnicodeDecodeError:
        # Refused, not repaired: a dated file holding a mangled copy of the
        # diagnosis would be read by the next run as what was found.
        print(
            f"dex-lens: the report must be UTF-8 text, and {args.source} is not. "
            "Nothing was written.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"dex-lens: could not read the report: {exc}", file=sys.stderr)
        return 2

    if not markdown.strip():
        # Said plainly and first: an empty file is a different mistake from an
        # unfinished report, and listing four missing sections would bury it.
        print("dex-lens: a report with no content is not a report", file=sys.stderr)
        return 2

    try:
        store = _store(args.inspected_root)
    except ValueError as exc:
        print(f"dex-lens: {exc}", file=sys.stderr)
        return 2

    # Read before writing: once the new report is on disk it is the most
    # recent one, and the previous one is what the reader wants pointed out.
    label = args.label or DEFAULT_LABEL
    previous = store.last(label=label)

    # The evidence rule is checked here, where skipping it is not an option
    # that exists. A rule that lives only in the skill's prose holds until the
    # run is long and the assistant is tired.
    ledger, ledger_problems = _ledger_gate(args.ledger)
    ledger_problems.extend(_ledger_binding_problems(markdown, ledger))
    problems = _gate(markdown, previous, ledger_problems)
    if problems:
        _report_problems(problems)
        print(
            "dex-lens: nothing was saved. Fix these and save it again.",
            file=sys.stderr,
        )
        return 2

    try:
        ledger_json = args.ledger.read_text(encoding="utf-8") if ledger is not None else None
        saved = store.save(markdown, label=label, ledger_json=ledger_json)
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
        if not report.is_valid_utf8:
            # Said out loud rather than degraded quietly: the file is shown
            # with its undecodable bytes marked, and nothing on disk changes.
            print(
                "dex-lens: this file is not UTF-8 text. Bytes that could not be "
                "read are shown as \ufffd; the file itself is untouched.",
                file=sys.stderr,
            )
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
