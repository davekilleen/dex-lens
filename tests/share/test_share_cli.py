"""`dex-lens share`: the preview-first contract, held down hard.

This command is the one place in Dex Lens where bytes can leave the machine
about something the person built. Every test here defends the same three
sentences: nothing is sent without --yes, what is sent is exactly what was
previewed, and the GitHub channel never posts as the person.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from capability_exchange.share import cli

CARD = "# A pattern worth stealing\n\nClose the loop: capture, verify, read back.\n"


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

    def test_the_preview_says_when_the_card_is_the_whole_of_it(
        self, card_file: Path, no_network: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.share_main([str(card_file)])

        assert "the card above is the whole of it" in capsys.readouterr().out

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
