"""Command-line doorway for the Dex Lens local concierge."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from capability_exchange.concierge.server import session_for_roots, start_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dex-lens",
        description=(
            "Open the local, read-only Dex Lens alpha in a private browser session."
        ),
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="Folders to offer on the permission screen for read-only inspection.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Print the private loopback URL without opening a browser.",
    )
    args = parser.parse_args(argv)
    roots = tuple(path.expanduser().resolve() for path in args.roots)
    invalid = tuple(path for path in roots if not path.is_dir())
    if invalid:
        rendered = ", ".join(str(path) for path in invalid)
        print(
            f"dex-lens: each approved root must be an existing directory: {rendered}",
            file=sys.stderr,
        )
        return 2
    session = session_for_roots(roots)
    server = start_server(session)
    url = f"http://127.0.0.1:{server.server_port}/?token={session.bootstrap_token}"
    print(url, flush=True)
    if not args.no_open:
        webbrowser.open(url)
    exit_code = 0
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        session.terminate()
        server.server_close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
