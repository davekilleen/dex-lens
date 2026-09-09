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
import os
import sys
import urllib.parse
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from capability_exchange.diagnosis.cli import build_engine
from capability_exchange.diagnosis.payload_guard import (
    HostilePayloadError,
    refuse_hostile_payload,
)
from capability_exchange.diagnosis.run import (
    INTAKE_NOT_SURE,
    INTAKE_PROJECT_LINK,
    DiagnosisStage,
)

__all__ = ["NEWSLETTER_URL", "newsletter_main", "share_answers_main", "share_main"]

#: Where the anonymous channel goes: Dex's intake, and nowhere else.
INTAKE_URL = "https://heydex.ai/lens/share"

#: Where the named channel goes: a new-issue page the person submits themselves.
ISSUES_URL = "https://github.com/davekilleen/dex-lens/issues/new"

#: Where a newsletter signup goes, and nowhere else. This is the same
#: doorway the heydex.ai site's own signup form posts to — it needs no key,
#: it reads exactly an email and a source label, and the source names Lens
#: so signups from here are tellable apart. The address travels in that one
#: request and is never written into any run artifact or report.
NEWSLETTER_URL = "https://api.heydex.ai/api/newsletter/subscribe"

#: The source label the newsletter doorway stores next to the address.
NEWSLETTER_SOURCE = "dex-lens"

#: The intake-answers destination is not baked into the build: it is the
#: address of Dave's own receiving table, configured by this one environment
#: variable and by nothing else. Unset means sharing answers is off and
#: nothing can be sent.
INTAKE_ANSWERS_URL_VARIABLE = "DEX_LENS_INTAKE_URL"

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


#: The only two control characters a terminal shows rather than obeys, and
#: the only two a card needs. Everything else in the C0 and C1 ranges is an
#: instruction: move the cursor, erase the line, retitle the window.
_TEXT_CONTROLS = frozenset({"\n", "\t"})


def _control_character_fault(text: str, *, allowed: frozenset[str]) -> tuple[str, str] | None:
    """Where the first character a terminal would obey is, or ``None``.

    This is the whole of what makes "this, exactly, is everything that would
    be shared" true. `\x1b[1A\x1b[2K` erases the line printed above it, so a
    card carrying it shows one thing on the screen and carries another into
    the link or the intake — the exact gap the preview exists to close. A card
    is written by an assistant out of the person's own files, so such a
    sequence needs no attacker to arrive; refusing it is the only shape where
    the preview and the payload are the same bytes by construction.
    """
    for index, character in enumerate(text):
        if character in allowed:
            continue
        if not (character <= "\x1f" or "\x7f" <= character <= "\x9f"):
            continue
        line = text.count("\n", 0, index) + 1
        column = index - text.rfind("\n", 0, index)
        where = f"a control character (0x{ord(character):02x}) at line {line}, character {column}"
        return character, where
    return None


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
    fault = _control_character_fault(text, allowed=_TEXT_CONTROLS)
    if fault is not None:
        character, where = fault
        # A carriage return is far more often a Windows line ending than an
        # attack, and "0x0d" alone would send someone hunting for nothing.
        hint = (
            " Carriage returns usually mean the card was saved with Windows "
            "line endings; save it with plain newlines."
            if character == "\r"
            else ""
        )
        print(
            f"dex-lens: the card contains {where}. A terminal obeys that "
            "instead of showing it — an escape sequence can erase the line "
            "above itself — so the preview would not be the card that "
            f"travels. Tabs and newlines are text; take the rest out.{hint}",
            file=sys.stderr,
        )
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
    if channel == "github":
        print("Nothing else travels: only the card above goes into the link.")
        print(
            "Channel: a pre-filled GitHub issue link, printed by the same "
            "command run again with --yes. Nothing is posted by this command; "
            "the person opens the link and submits it themselves, under their "
            "own name."
        )
    else:
        if contact:
            print(f"Plus this contact line, because one was given: {contact}")
        else:
            print("No name, no contact.")
        # Every byte that leaves is in the preview — including the one this
        # command adds itself. A preview that omits anything the send
        # includes is a preview that lies by silence.
        print(f"Plus the version of Lens doing the sending: {_lens_version()}")
        print("Channel: one anonymous request to Dex's intake at " + INTAKE_URL + ".")
    print()
    if channel == "github":
        print("Nothing has been sent and no link has been printed yet. To print")
        print("the link after the person has read this and said yes, run the")
        print("same command again with --yes.")
    else:
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

    fault = _control_character_fault(args.contact, allowed=frozenset())
    if fault is not None:
        print(
            f"dex-lens: the contact line contains {fault[1]}. It is one line "
            "that is printed in the preview and travels with the card; a "
            "newline or an escape sequence in it can forge the end of the "
            "preview and hide what follows.",
            file=sys.stderr,
        )
        return 2

    if args.to == "github" and args.contact:
        # Not silently dropped, and not silently included either: a GitHub
        # issue is already submitted under the person's own name, and a
        # public issue is no place to publish an email address.
        print(
            "dex-lens: --contact is for the anonymous channel. A GitHub issue "
            "is submitted under your own name, which is already the way to "
            "reach you; a public issue is no place for a contact line.",
            file=sys.stderr,
        )
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


def _payload_bytes(payload: dict[str, object]) -> bytes:
    """One canonical form, used for the preview and the send alike.

    The preview and the payload being the same bytes by construction is the
    whole guarantee; nothing may serialize this twice differently.
    """

    return json.dumps(
        payload, ensure_ascii=True, indent=2, sort_keys=True
    ).encode("utf-8")


def _print_fenced(payload_bytes: bytes) -> None:
    print("---8<---")
    sys.stdout.write(payload_bytes.decode("utf-8"))
    print()
    print("--->8---")


def share_answers_main(argv: list[str] | None = None) -> int:
    """Offer the run's recorded answers to Dave: preview by default.

    Lawful only after the run's report is saved, so the offer can never come
    before the person has what they came for. The payload is built from the
    engine-validated answers alone — question ids, chosen options, the project
    link if one was given, the run's own timestamp, and the Lens version.
    Nothing read from the person's files can enter it.
    """

    parser = argparse.ArgumentParser(
        prog="dex-lens share-answers",
        description=(
            "Send the questions you answered at the start of a run to Dave, to "
            "help improve Dex Lens. Without --yes this prints exactly what "
            "would be sent and sends nothing."
        ),
    )
    parser.add_argument("--run", required=True, help="Diagnosis run ID.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Actually send. Use only after the person has read the exact "
            "preview and said yes in their own words."
        ),
    )
    args = parser.parse_args(argv)

    engine = build_engine()
    view = engine.status(args.run)
    if view.stage not in {DiagnosisStage.SAVED, DiagnosisStage.CLOSED}:
        print(
            "dex-lens: this offer comes after the report. Save the report "
            "first; nothing was sent.",
            file=sys.stderr,
        )
        return 2
    if view.intake is None:
        print(
            "dex-lens: this run recorded no answers, so there is nothing to "
            "share. Nothing was sent.",
            file=sys.stderr,
        )
        return 2

    answers = {item.question_id: item.answer for item in view.intake.answers}
    link = answers.pop(INTAKE_PROJECT_LINK, None)
    result = engine.result(args.run)
    payload: dict[str, object] = {
        "answers": answers,
        "project_link": (
            link if link is not None and link != INTAKE_NOT_SURE else None
        ),
        "submitted_at": result.report.run_identity.created_at.isoformat(),
        "lens_version": _lens_version(),
    }
    try:
        refuse_hostile_payload(payload)
    except HostilePayloadError:
        print(
            "dex-lens: these answers carry content that must not leave this "
            "machine. Nothing was sent.",
            file=sys.stderr,
        )
        return 2
    payload_bytes = _payload_bytes(payload)

    if not args.yes:
        print("This is exactly what would be sent to Dave — nothing else:")
        _print_fenced(payload_bytes)
        print(
            "That is the whole payload: your answers, the run's date, and the "
            "version of Lens doing the sending. No file names, no folder "
            "names, nothing read from your files, and no email address."
        )
        print("Nothing has been sent. To send it, run again with --yes.")
        return 0

    destination = os.environ.get(INTAKE_ANSWERS_URL_VARIABLE, "")
    if not destination.startswith("https://"):
        print(
            "dex-lens: no destination is configured for shared answers "
            f"(set {INTAKE_ANSWERS_URL_VARIABLE}). Nothing was sent.",
            file=sys.stderr,
        )
        return 2
    _print_fenced(payload_bytes)
    request = urllib.request.Request(
        destination,
        data=payload_bytes,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS):
            pass
    except OSError as error:
        print(f"dex-lens: sending failed ({error}). Try again later.", file=sys.stderr)
        return 1
    print("Sent. Thank you — this helps make Dex Lens better.")
    return 0


def newsletter_main(argv: list[str] | None = None) -> int:
    """Sign one email address up for heydex.ai updates: preview by default.

    Its own command and its own yes, never bundled with anything else. The
    address travels in this one request and is written into no run artifact,
    no report, and no shared answers.
    """

    parser = argparse.ArgumentParser(
        prog="dex-lens newsletter",
        description=(
            "Sign up for heydex.ai updates. Without --yes this prints exactly "
            "what would be sent and sends nothing."
        ),
    )
    parser.add_argument("email", help="The email address to sign up.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Actually sign up. Use only after the person has read the exact "
            "preview and said yes in their own words."
        ),
    )
    args = parser.parse_args(argv)

    email = args.email.strip()
    if (
        len(email) > 200
        or email.count("@") != 1
        or email.startswith("@")
        or email.endswith("@")
        or any(character.isspace() or ord(character) < 32 for character in email)
    ):
        print("dex-lens: that does not look like an email address.", file=sys.stderr)
        return 2

    payload_bytes = _payload_bytes(
        {"email": email, "source": NEWSLETTER_SOURCE}
    )
    if not args.yes:
        print("This is exactly what would be sent to heydex.ai — nothing else:")
        _print_fenced(payload_bytes)
        print("Nothing has been sent. To sign up, run again with --yes.")
        return 0
    request = urllib.request.Request(
        NEWSLETTER_URL,
        data=payload_bytes,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS):
            pass
    except OSError as error:
        print(f"dex-lens: signing up failed ({error}). Try again later.", file=sys.stderr)
        return 1
    print("Signed up. You can unsubscribe from any email heydex.ai sends.")
    return 0
