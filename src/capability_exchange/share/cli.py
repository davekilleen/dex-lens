"""``dex-lens share``: send one idea card back to Dex, on the person's terms.

Two channels, chosen by the person, never for them:

- ``--to heydex`` — one anonymous request to Dex's intake. No account, no
  name, nothing about their system beyond the card they read and approved.
- ``--to github`` — a pre-filled GitHub issue **link**. This command never
  posts anything: it prints the address, the person's own browser opens it,
  and they press submit under their own name, or close the tab.

The contract that matters more than either channel: **preview is the
default**. Run without ``--yes``, this command prints the exact bytes that
would leave the machine and sends nothing. ``--yes`` exists so the person's
AI can send after — and only after — the person has read the preview and
said so in their own words. A tool whose default sends is a tool whose
preview is theatre.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__all__ = ["share_main"]

#: Where the anonymous channel goes: Dex's intake, and nowhere else.
INTAKE_URL = "https://heydex.ai/lens/share"

#: Where the named channel goes: a new-issue page the person submits themselves.
ISSUES_URL = "https://github.com/davekilleen/dex-lens/issues/new"

#: An idea card is a page, not a payload. Anything longer than this has
#: stopped being a first-principles pattern and started being a document —
#: and a generous cap is also what keeps the intake unattractive to abuse.
MAX_CARD_BYTES = 16 * 1024

#: GitHub truncates very long prefilled URLs; past this the link is printed
#: alongside the body to paste rather than pretending the whole card fits.
_MAX_PREFILL_URL = 6 * 1024

_TIMEOUT_SECONDS = 15.0


def _lens_version() -> str:
    try:
        return version("capability_exchange")
    except PackageNotFoundError:  # a source checkout without install metadata
        return "unknown"


def _read_card(source: str) -> bytes | None:
    """The card bytes, or ``None`` after explaining the refusal."""
    if source == "-":
        raw = sys.stdin.buffer.read()
    else:
        path = Path(source)
        if not path.is_file():
            print(f"dex-lens: no such card file: {path}", file=sys.stderr)
            return None
        raw = path.read_bytes()
    if not raw.strip():
        print("dex-lens: the card is empty; there is nothing to share.", file=sys.stderr)
        return None
    if len(raw) > MAX_CARD_BYTES:
        print(
            f"dex-lens: the card is {len(raw)} bytes; the cap is {MAX_CARD_BYTES}. "
            "A shared idea is a page describing a pattern, not a document — "
            "cut it down to the idea.",
            file=sys.stderr,
        )
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        print("dex-lens: the card must be plain text.", file=sys.stderr)
        return None
    if not text.lstrip().startswith("# "):
        print(
            "dex-lens: the card needs a one-line `# ` title so the idea can be "
            "referred to by name.",
            file=sys.stderr,
        )
        return None
    return raw


def _preview(card: bytes, *, channel: str, contact: str) -> None:
    """Show exactly what would leave, byte for byte, and what would not."""
    print("This, exactly, is everything that would be shared:")
    print()
    print("---8<---------------------------------------------------------")
    sys.stdout.write(card.decode("utf-8"))
    if not card.endswith(b"\n"):
        print()
    print("--->8---------------------------------------------------------")
    if contact:
        print(f"Plus this contact line, because one was given: {contact}")
    else:
        print("No name, no contact, nothing else: the card above is the whole of it.")
    if channel == "github":
        print(
            "Channel: a pre-filled GitHub issue link. Nothing is posted by this "
            "command; the person submits it themselves, under their own name."
        )
    else:
        print("Channel: one anonymous request to Dex's intake at " + INTAKE_URL + ".")
    print()
    print("Nothing has been sent. To send after the person has read this and")
    print("said yes, run the same command again with --yes.")


def _send_heydex(card: bytes, contact: str) -> int:
    payload = json.dumps(
        {
            "card": card.decode("utf-8"),
            "contact": contact or None,
            "lens_version": _lens_version(),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        INTAKE_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read(4096).decode("utf-8", "replace").strip()
    except OSError as exc:
        print(
            f"dex-lens: the share did not go through ({exc}). Nothing was "
            "recorded on the other side; try again later, or use --to github.",
            file=sys.stderr,
        )
        return 1
    print(body or "Shared. Thank you — Dave reads every one of these.")
    return 0


def _github_link(card: bytes) -> int:
    text = card.decode("utf-8")
    title = text.lstrip().splitlines()[0].lstrip("# ").strip()[:120]
    url = (
        f"{ISSUES_URL}?labels=shared-idea&title={urllib.parse.quote(f'Shared idea: {title}')}"
        f"&body={urllib.parse.quote(text)}"
    )
    if len(url) <= _MAX_PREFILL_URL:
        print("Open this link; the issue is pre-filled and nothing is posted until")
        print("the person presses submit, under their own GitHub name:")
        print()
        print(url)
        return 0
    # An honest fallback beats a silently truncated card.
    print("The card is too long for a pre-filled link, so: open this page,")
    print("paste the card below as the issue body, and submit:")
    print()
    print(f"{ISSUES_URL}?labels=shared-idea&title={urllib.parse.quote(f'Shared idea: {title}')}")
    print()
    sys.stdout.write(text)
    return 0


def share_main(argv: list[str] | None = None) -> int:
    """Preview by default; send only on ``--yes``; never post as the person."""

    parser = argparse.ArgumentParser(
        prog="dex-lens share",
        description=(
            "Share one idea card back to Dex. Without --yes this prints exactly "
            "what would be sent and sends nothing."
        ),
    )
    parser.add_argument("card", help="The card file, or `-` to read it from standard input.")
    parser.add_argument(
        "--to",
        choices=("heydex", "github"),
        default="heydex",
        help=(
            "heydex: one anonymous request to Dex's intake. github: print a "
            "pre-filled issue link the person submits themselves."
        ),
    )
    parser.add_argument(
        "--contact",
        default="",
        help=(
            "Optional way to reach the person, included only because they chose "
            "to give one. Anonymous is the default and is fine."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Actually send. Use only after the person has read the exact "
            "preview and said yes in their own words."
        ),
    )
    args = parser.parse_args(argv)

    if len(args.contact) > 200:
        print("dex-lens: the contact line is longer than 200 characters.", file=sys.stderr)
        return 2

    card = _read_card(args.card)
    if card is None:
        return 2

    if not args.yes:
        _preview(card, channel=args.to, contact=args.contact)
        return 0

    if args.to == "github":
        return _github_link(card)
    return _send_heydex(card, args.contact)
