"""`dex-lens share`: the preview-first contract, held down hard.

This command is the one place in Dex Lens where bytes can leave the machine
about something the person built. Every test here defends the same three
sentences: nothing is sent without --yes, what is sent is exactly what was
previewed, and the GitHub channel never posts as the person.
"""

from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from capability_exchange.share import cli

CARD = "# A pattern worth stealing\n\nClose the loop: capture, verify, read back.\n"

#: Wide and tall enough that nothing wraps or scrolls, so anything missing
#: from the emulated screen is missing because the card hid it.
_SCREEN_COLUMNS = 120
_SCREEN_ROWS = 60


def _screen_of(tmp_path: Path, argv: list[str]) -> tuple[int, str]:
    """Run `share` under a real pty and return (exit code, what is on screen).

    A preview is a promise about a terminal, so it has to be checked on one.
    The bytes are captured through `script`, which allocates the pty, and
    replayed through `pyte`, which resolves cursor movement and erasure the
    same way the person's terminal does.
    """
    pyte = pytest.importorskip("pyte", reason="the on-screen proof needs a terminal emulator")
    script = shutil.which("script")
    if script is None:  # pragma: no cover - depends on the host
        pytest.skip("the on-screen proof needs util-linux `script` to allocate a pty")

    runner = tmp_path / "run_share.py"
    runner.write_text(
        "import sys\n"
        "from capability_exchange.share import cli\n"
        "sys.exit(cli.share_main(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    command = shlex.join([sys.executable, str(runner), *argv])
    captured = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [script, "-qec", command, "/dev/null"],
        capture_output=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path), "TERM": "xterm"},
        check=False,
    )
    screen = pyte.Screen(_SCREEN_COLUMNS, _SCREEN_ROWS)
    stream = pyte.Stream(screen)
    stream.feed(captured.stdout.decode("utf-8", "replace"))
    return captured.returncode, "\n".join(line.rstrip() for line in screen.display)


@pytest.fixture
def card_file(tmp_path: Path) -> Path:
    path = tmp_path / "card.md"
    path.write_text(CARD, encoding="utf-8")
    return path


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list:
    """Any network call fails the test unless the test opted in."""
    calls: list = []

    def refuse(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("the network was touched")

    monkeypatch.setattr(cli.urllib.request, "urlopen", refuse)
    return calls


class TestPreviewIsTheDefault:
    def test_without_yes_nothing_is_sent_and_the_exact_bytes_are_shown(
        self, card_file: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.share_main([str(card_file)]) == 0

        out = capsys.readouterr().out
        assert CARD in out, "the preview is the exact bytes, not a summary"
        assert "Nothing has been sent" in out
        assert no_network == []

    def test_the_preview_shows_every_field_the_send_includes(
        self, card_file: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The send posts card, contact, and lens_version; the preview must
        account for all three, including the one this command adds itself.
        A preview that omits anything the send includes lies by silence."""
        cli.share_main([str(card_file)])

        out = capsys.readouterr().out
        assert "No name, no contact." in out
        assert "version of Lens doing the sending" in out
        assert cli._lens_version() in out

    def test_a_given_contact_is_previewed_too(
        self, card_file: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A line that will travel must appear in the preview like any other."""
        cli.share_main([str(card_file), "--contact", "bird@example.com"])

        assert "bird@example.com" in capsys.readouterr().out


class TestSending:
    def test_yes_posts_exactly_the_previewed_card(
        self, card_file: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        sent: dict = {}

        class _Response(io.BytesIO):
            def __enter__(self) -> _Response:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        def capture(request, timeout):  # noqa: ANN001 - urllib's shape
            sent["url"] = request.full_url
            sent["body"] = json.loads(request.data.decode("utf-8"))
            return _Response(b"Shared. Thank you.")

        monkeypatch.setattr(cli.urllib.request, "urlopen", capture)

        assert cli.share_main([str(card_file), "--yes"]) == 0

        assert sent["url"] == cli.INTAKE_URL
        assert sent["body"]["card"] == CARD
        assert sent["body"]["contact"] is None
        assert "Shared. Thank you." in capsys.readouterr().out

    def test_a_failed_send_is_honest_and_nonzero(
        self, card_file: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def down(request, timeout):  # noqa: ANN001
            raise OSError("connection refused")

        monkeypatch.setattr(cli.urllib.request, "urlopen", down)

        assert cli.share_main([str(card_file), "--yes"]) == 1
        assert "Nothing was recorded on the other side" in capsys.readouterr().err


class TestGitHubChannel:
    def test_a_contact_on_the_github_channel_is_refused_not_dropped(
        self, card_file: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The preview and the send must be the same thing by construction.

        Silently dropping the contact would make the preview a lie; silently
        including it would publish an email in a public issue. Refusing with
        the reason is the only shape where nothing surprises anyone.
        """
        assert cli.share_main([str(card_file), "--to", "github", "--contact", "x@y.z"]) == 2

        err = capsys.readouterr().err
        assert "anonymous channel" in err
        assert "under your own name" in err

    def test_it_prints_a_prefilled_link_and_never_touches_the_network(
        self, card_file: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The person submits under their own name, or closes the tab."""
        assert cli.share_main([str(card_file), "--to", "github", "--yes"]) == 0

        out = capsys.readouterr().out
        assert cli.ISSUES_URL in out
        assert "A%20pattern%20worth%20stealing" in out
        assert "nothing is posted until" in out
        assert no_network == []

    def test_the_preview_does_not_promise_a_link_it_is_not_printing(
        self, card_file: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The link appears only under --yes; the preview said "the link below".

        A preview that describes output it is not producing teaches the reader
        that its other sentences are approximate too.
        """
        assert cli.share_main([str(card_file), "--to", "github"]) == 0

        out = capsys.readouterr().out
        assert cli.ISSUES_URL not in out, "no link is printed without --yes"
        assert "link below" not in out
        assert "--yes" in out, "say how the link is printed instead"

    def test_a_card_too_long_to_prefill_is_printed_not_truncated(
        self, tmp_path: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = "# Long idea\n\n" + ("substance " * 900)
        long_card = tmp_path / "long.md"
        long_card.write_text(body, encoding="utf-8")

        assert cli.share_main([str(long_card), "--to", "github", "--yes"]) == 0

        out = capsys.readouterr().out
        assert "paste the card below" in out
        assert body in out, "an honest fallback carries the whole card"


class TestRefusals:
    def test_an_oversized_card_is_refused_with_the_reason(
        self, tmp_path: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        big = tmp_path / "big.md"
        big.write_text("# Big\n" + "x" * (cli.MAX_CARD_BYTES + 1), encoding="utf-8")

        assert cli.share_main([str(big), "--yes"]) == 2
        assert "cut it down to the idea" in capsys.readouterr().err

    def test_a_card_without_a_title_is_refused(
        self, tmp_path: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        untitled = tmp_path / "untitled.md"
        untitled.write_text("just some text\n", encoding="utf-8")

        assert cli.share_main([str(untitled)]) == 2
        assert "title" in capsys.readouterr().err

    def test_an_empty_card_is_refused(
        self, tmp_path: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        empty = tmp_path / "empty.md"
        empty.write_text("   \n", encoding="utf-8")

        assert cli.share_main([str(empty)]) == 2
        assert "nothing to share" in capsys.readouterr().err


class TestControlCharacters:
    """The headline promise: the preview *is* the payload, on a real terminal.

    A card is written by an assistant out of the person's own files, so a
    stray escape sequence needs no attacker to arrive. Rendered on a terminal,
    `\x1b[1A\x1b[2K` erases the line above it: a card can therefore show one
    thing on screen and carry another into the link or the intake. The only
    shape where "this, exactly, is everything that would be shared" is true is
    one where a card that a terminal would not render literally never gets
    as far as the preview.
    """

    HOSTILE = (
        "# Dated reports so runs can compare\n"
        "\n"
        "Keep each diagnosis as a dated file.\n"
        "SECRET: /Users/dave/vault  token ghp_REALTOKEN123\n"
        "\x1b[1A\x1b[2K\rNothing else here.\n"
    )

    @pytest.mark.parametrize(
        "sequence",
        [
            "\x1b[1A\x1b[2K",
            "\r",
            "\x08",
            "\x00",
            "\x7f",
            "\x1b]0;title\x07",
        ],
        ids=["cursor-up-erase", "carriage-return", "backspace", "nul", "delete", "osc"],
    )
    def test_a_card_a_terminal_would_not_render_literally_is_refused(
        self, tmp_path: Path, sequence: str, no_network: list,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        card = tmp_path / "hostile.md"
        card.write_text(f"# An idea\n\nvisible{sequence}hidden\n", encoding="utf-8")

        assert cli.share_main([str(card)]) == 2

        captured = capsys.readouterr()
        assert "control character" in captured.err
        assert "This, exactly" not in captured.out, "a refused card is never previewed"
        assert no_network == []

    def test_the_refusal_names_where_the_character_is(
        self, tmp_path: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A person cannot delete what they cannot see; say which line."""
        card = tmp_path / "hostile.md"
        card.write_text(self.HOSTILE, encoding="utf-8")

        assert cli.share_main([str(card)]) == 2

        err = capsys.readouterr().err
        assert "line 5" in err
        assert "1b" in err.lower(), "name the byte, since it prints as nothing"

    def test_windows_line_endings_are_refused_with_the_likely_cause_named(
        self, tmp_path: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A carriage return is far more often a saved file than an attack.

        It is still refused — a bare `\r` returns the cursor and lets the next
        line overwrite this one — but "0x0d" alone would send the person
        hunting for a character they cannot see.
        """
        card = tmp_path / "windows.md"
        card.write_bytes(b"# An idea\r\n\r\nWritten on another machine.\r\n")

        assert cli.share_main([str(card)]) == 2

        err = capsys.readouterr().err
        assert "control character" in err
        assert "Windows line endings" in err

    def test_a_refused_card_never_reaches_the_github_link(
        self, tmp_path: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The bytes must not survive into the outbound artefact either."""
        card = tmp_path / "hostile.md"
        card.write_text(self.HOSTILE, encoding="utf-8")

        assert cli.share_main([str(card), "--to", "github", "--yes"]) == 2

        out = capsys.readouterr().out
        assert cli.ISSUES_URL not in out
        assert "ghp_REALTOKEN123" not in out

    def test_a_refused_card_is_never_sent_to_the_intake(
        self, tmp_path: Path, no_network: list
    ) -> None:
        card = tmp_path / "hostile.md"
        card.write_text(self.HOSTILE, encoding="utf-8")

        assert cli.share_main([str(card), "--yes"]) == 2
        assert no_network == [], "the card is refused before anything is sent"

    def test_tabs_and_newlines_are_ordinary_text_and_stay_allowed(
        self, tmp_path: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Fail closed on what a terminal acts on, not on markdown."""
        body = "# An idea\n\n\tindented by a tab\n\nand a paragraph.\n"
        card = tmp_path / "fine.md"
        card.write_text(body, encoding="utf-8")

        assert cli.share_main([str(card)]) == 0
        assert body in capsys.readouterr().out


class TestContactLine:
    def test_a_contact_line_cannot_forge_the_preview_boundary(
        self, card_file: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--contact is interpolated into the preview, so it is payload too.

        A newline in it lets the contact draw its own `--->8---` boundary and
        a fake "No name, no contact." line underneath, which reads as a
        preview that ended before the contact began.
        """
        forged = (
            "ok\n--->8---------------------------------------------------------\n"
            "No name, no contact."
        )

        assert cli.share_main([str(card_file), "--contact", forged]) == 2

        captured = capsys.readouterr()
        assert "control character" in captured.err
        assert "No name, no contact." not in captured.out
        assert no_network == []

    @pytest.mark.parametrize(
        "sequence", ["\n", "\r", "\t", "\x1b[2K", "\x08"],
        ids=["newline", "carriage-return", "tab", "erase-line", "backspace"],
    )
    def test_no_control_character_survives_into_the_contact_line(
        self, card_file: Path, sequence: str, no_network: list,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A contact line is one line: even a tab is not part of an address."""
        assert cli.share_main([str(card_file), "--contact", f"a{sequence}b"]) == 2
        assert "control character" in capsys.readouterr().err


class TestOnARealTerminal:
    """The proof that matters, taken the way the bug was found.

    `capsys` compares strings; a person reads a VT100. These two run the
    command under a real pty and replay the captured bytes through a terminal
    emulator, so the assertion is about what is on the screen.
    """

    def test_every_byte_of_an_accepted_card_is_on_the_screen(
        self, tmp_path: Path
    ) -> None:
        body = (
            "# Dated reports so runs can compare\n"
            "\n"
            "Keep each diagnosis as a dated file.\n"
            "SECRET: /Users/dave/vault token ghp_REALTOKEN123\n"
            "Nothing else here.\n"
        )
        card = tmp_path / "card.md"
        card.write_text(body, encoding="utf-8")

        code, screen = _screen_of(tmp_path, [str(card)])

        assert code == 0
        for line in body.splitlines():
            if line:
                assert line in screen, f"missing from the person's screen: {line!r}"

    def test_a_card_that_could_hide_itself_never_reaches_the_screen(
        self, tmp_path: Path
    ) -> None:
        card = tmp_path / "hostile.md"
        card.write_text(TestControlCharacters.HOSTILE, encoding="utf-8")

        code, screen = _screen_of(tmp_path, [str(card)])

        assert code == 2
        assert "This, exactly" not in screen
        assert "control character" in screen
        # The line the escape sequence was there to erase is not silently
        # dropped and not silently shown: the whole card is refused.
        assert "ghp_REALTOKEN123" not in screen
