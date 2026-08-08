"""Command-line doorway for the Dex Lens local concierge."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from capability_exchange.concierge.server import session_for_roots, start_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the private Dex Lens concierge.")
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
    session = session_for_roots(roots)
    server = start_server(session)
    url = f"http://127.0.0.1:{server.server_port}/?token={session.bootstrap_token}"
    print(url, flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        session.terminate()
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
