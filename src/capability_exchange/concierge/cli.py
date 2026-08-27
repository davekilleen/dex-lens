"""Command-line doorway for Dex Lens.

Two shapes share one command. ``dex-lens catalogue`` and ``dex-lens brief``
serve the Dex Lens skill, which does its analysis inside the person's own AI
and needs from here only the part a prompt must not be trusted to do: fetching
Dex's catalogue and proving the signature. ``dex-lens <folder>`` opens the
original local browser journey, which is frozen (see ``docs/STATUS.md``).

Subcommands are dispatched by hand rather than through argparse subparsers so
that ``dex-lens /some/folder`` keeps working exactly as it always did. A
folder cannot be mistaken for a subcommand: dispatch requires an exact match,
and no subcommand name begins with ``/``, ``~`` or ``.``.

The reverse must hold too, and it is the harder half. A bare word that is not
a subcommand — ``inventary``, ``Inventory``, ``reports-save`` — is a mistyped
command, not a folder, even on the days it happens to name one in the current
directory. Serving it would start the frozen journey and hang, silently, on
the strength of a typo. So a bare word fails closed with the nearest real
command; a folder is opened when it is *written* as a path, which is what
``./inventary`` is for.
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys
import webbrowser
from pathlib import Path

from capability_exchange.adapters.claude_code.inventory_cli import inventory_main
from capability_exchange.catalogue.cli import brief_main, catalogue_main
from capability_exchange.concierge.folder_picker import FolderPickerError, choose_folder
from capability_exchange.concierge.server import session_for_roots, start_server
from capability_exchange.contribution.cli import contributions_main
from capability_exchange.reports.cli import reports_main
from capability_exchange.share.cli import share_main

#: Exact first-argument matches that route away from the browser journey.
_SUBCOMMANDS = {
    "brief": brief_main,
    "catalogue": catalogue_main,
    "contributions": contributions_main,
    "inventory": inventory_main,
    "reports": reports_main,
    "share": share_main,
}


#: What someone sees the first time they type the name of the thing they just
#: installed. Before this, a bare `dex-lens` answered with an argparse usage
#: error about the frozen browser journey — a stack of flags, aimed at a
#: journey nobody is meant to use, at the exact moment a person is deciding
#: whether this was worth installing.
_WELCOME = """Dex Lens is installed.

It is a second opinion on the personal AI system you have already built: what
it does well, what has quietly rotted, and the few things Dex has that might
be worth borrowing. It reads. It never changes your system.

You do not run it from here. Open Claude Code and ask, in your own words:

    Have a look at my setup and tell me what Dex has that I don't.

Your assistant does the reading and calls these when it needs them:

    dex-lens inventory <folder>    what your system is made of
    dex-lens catalogue             what Dex publishes, signature checked here
    dex-lens brief <id>            how to rebuild one capability yourself
    dex-lens reports               the dated reports past looks left behind
    dex-lens contributions         manage Cards you explicitly sent for review
    dex-lens share <card>          prepare a private GitHub handoff; never posts

Add --help to any of them.
"""

#: Written on their own, these ask for the welcome rather than for the frozen
#: browser journey's argparse usage. The welcome is where every command
#: is named, so it is the only useful answer to "what is this".
_HELP_WORDS = frozenset({"--help", "-h", "help"})


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in _SUBCOMMANDS:
        return _SUBCOMMANDS[arguments[0]](arguments[1:])
    if not arguments or (len(arguments) == 1 and arguments[0] in _HELP_WORDS):
        print(_WELCOME, end="")
        return 0
    if _is_written_as_a_command(arguments[0]):
        return _refuse_unknown_command(arguments[0])
    return _serve_main(arguments)


def _is_written_as_a_command(word: str) -> bool:
    """Is this first argument a word someone typed *as a command*?

    A folder written as a path never is: it begins with ``/``, ``~`` or
    ``.``, or it carries a separator. A flag never is either — those belong
    to the folder doorway. Everything else is a bare word, and by this point
    it is not one of ``_SUBCOMMANDS``.
    """
    if word.startswith(("/", "~", ".", "-")):
        return False
    separators = {separator for separator in (os.sep, os.altsep, "/") if separator}
    return not any(separator in word for separator in separators)


def _refuse_unknown_command(word: str) -> int:
    """Say what was probably meant, and stop. Never guess by running one."""
    known = sorted(_SUBCOMMANDS)
    near = difflib.get_close_matches(word.lower(), known, n=1)
    lines = [f"dex-lens: {word!r} is not a dex-lens command."]
    if near:
        lines.append(f"Did you mean: dex-lens {near[0]}")
    else:
        lines.append("Commands: " + ", ".join(known))
    lines.append(f"If you meant the folder, write it as a path: dex-lens ./{word}")
    lines.append("Run dex-lens on its own for what each command is for.")
    print("\n".join(lines), file=sys.stderr)
    return 2


def _serve_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dex-lens",
        description=(
            "Open the local, read-only Dex Lens alpha in a private browser session."
        ),
    )
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        help="Folders to offer on the permission screen for read-only inspection.",
    )
    parser.add_argument(
        "--choose-folder",
        action="store_true",
        help="Choosing a folder does not scan it.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Print the private loopback URL without opening a browser.",
    )
    parser.add_argument(
        "--corrects-contribution",
        metavar="RECEIPT_ID",
        help=(
            "Run a fresh preview-and-consent journey that replaces this saved "
            "contribution receipt."
        ),
    )
    args = parser.parse_args(argv)
    if args.choose_folder and args.roots:
        parser.error("--choose-folder cannot be combined with an explicit folder")
    if args.choose_folder:
        try:
            selected = choose_folder()
        except FolderPickerError as exc:
            print(f"dex-lens: {exc}. Nothing was read.", file=sys.stderr)
            return 2
        if selected is None:
            print("dex-lens: No folder was selected. Nothing was read.", file=sys.stderr)
            return 0
        roots = (selected.expanduser().resolve(),)
    else:
        roots = tuple(path.expanduser().resolve() for path in args.roots)
    if not roots:
        parser.error("provide an existing folder or use --choose-folder")
    invalid = tuple(path for path in roots if not path.is_dir())
    if invalid:
        rendered = ", ".join(str(path) for path in invalid)
        print(
            f"dex-lens: each approved root must be an existing directory: {rendered}",
            file=sys.stderr,
        )
        return 2
    if args.corrects_contribution is None:
        session = session_for_roots(roots)
    else:
        session = session_for_roots(
            roots,
            correction_receipt_id=args.corrects_contribution,
        )
    server = None
    exit_code = 0
    try:
        server = start_server(session)
        url = f"http://127.0.0.1:{server.server_port}/?token={session.bootstrap_token}"
        print(url, flush=True)
        if not args.no_open:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        session.terminate()
        wait_for_stop = getattr(session, "wait_for_collection_stop", None)
        if callable(wait_for_stop):
            wait_for_stop()
        if server is not None:
            server.server_close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
