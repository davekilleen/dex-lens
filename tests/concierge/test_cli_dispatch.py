"""One command, two shapes, and a folder that must never look like a verb.

`dex-lens catalogue|brief|inventory` serve the skill. `dex-lens <folder>`
opens the frozen browser journey. Dispatch is by hand rather than through
argparse subparsers precisely so the second form keeps working unchanged, and
that is worth holding down: a folder silently reinterpreted as a subcommand
would fail in a way nobody would think to look for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capability_exchange.concierge import cli


class TestSubcommandDispatch:
    @pytest.mark.parametrize("name", ["catalogue", "brief", "inventory", "reports"])
    def test_a_subcommand_routes_away_from_the_browser_journey(
        self, name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        def record(argv: list[str]) -> int:
            seen.extend(argv)
            return 0

        monkeypatch.setitem(cli._SUBCOMMANDS, name, record)
        monkeypatch.setattr(
            cli, "_serve_main", lambda _argv: pytest.fail("the server must not start")
        )

        assert cli.main([name, "--flag", "value"]) == 0
        assert seen == ["--flag", "value"]

    def test_a_folder_still_opens_the_browser_journey(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        served: list[list[str]] = []
        monkeypatch.setattr(cli, "_serve_main", lambda argv: served.append(list(argv)) or 0)

        assert cli.main([str(tmp_path)]) == 0
        assert served == [[str(tmp_path)]]

    def test_a_folder_named_like_a_subcommand_is_still_a_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dispatch requires an exact match, and a path never is one."""
        folder = tmp_path / "catalogue"
        folder.mkdir()
        served: list[list[str]] = []
        monkeypatch.setattr(cli, "_serve_main", lambda argv: served.append(list(argv)) or 0)

        assert cli.main([str(folder)]) == 0
        assert served == [[str(folder)]]

    def test_no_arguments_says_how_to_start_rather_than_printing_usage(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The first thing a person types after installing.

        It used to be an argparse usage error about the frozen browser
        journey: a stack of flags, aimed at a journey nobody is meant to use,
        at the moment they are deciding whether this was worth installing.
        """
        monkeypatch.setattr(
            cli, "_serve_main", lambda _argv: pytest.fail("the server must not start")
        )

        assert cli.main([]) == 0

        out = capsys.readouterr().out
        assert "Open Claude Code and ask" in out
        assert "It reads. It never changes your system." in out

    def test_no_subcommand_name_could_ever_be_a_path(self) -> None:
        for name in cli._SUBCOMMANDS:
            assert not name.startswith(("/", "~", ".")), name
            assert "/" not in name, name


class TestHelpReachesTheWelcome:
    """`--help` is where a person goes after the welcome tells them to.

    The welcome ends "Add --help to any of them." — so `dex-lens --help`
    itself must not answer with the argparse usage of the frozen browser
    journey (`docs/STATUS.md`), which mentions none of the commands the
    product is actually made of.
    """

    @pytest.mark.parametrize("word", ["--help", "-h", "help"])
    def test_bare_help_prints_the_welcome_not_the_frozen_journey_usage(
        self, word: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            cli, "_serve_main", lambda _argv: pytest.fail("the server must not start")
        )

        assert cli.main([word]) == 0

        out = capsys.readouterr().out
        assert "Open Claude Code and ask" in out
        assert "--choose-folder" not in out

    def test_the_welcome_lists_every_subcommand_that_exists(self) -> None:
        for name in cli._SUBCOMMANDS:
            assert f"dex-lens {name}" in cli._WELCOME, name

    def test_share_is_named_in_the_welcome(self) -> None:
        """A real subcommand the welcome used to leave out entirely."""
        assert "dex-lens share" in cli._WELCOME

    def test_help_alongside_other_arguments_still_reaches_the_folder_doorway(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`dex-lens --choose-folder --help` is a question about that flag."""
        served: list[list[str]] = []
        monkeypatch.setattr(cli, "_serve_main", lambda argv: served.append(list(argv)) or 0)

        assert cli.main(["--choose-folder", "--help"]) == 0
        assert served == [["--choose-folder", "--help"]]

    def test_a_subcommands_own_help_is_never_intercepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[list[str]] = []
        monkeypatch.setitem(
            cli._SUBCOMMANDS, "inventory", lambda argv: seen.append(list(argv)) or 0
        )

        assert cli.main(["inventory", "--help"]) == 0
        assert seen == [["--help"]]


class TestMistypedSubcommand:
    """A near-miss must never be read as a folder to serve.

    `dex-lens inventary`, in a directory that happens to contain a folder of
    that name, used to start the frozen browser journey and hang. Failing
    closed here means: say what was meant, and stop.
    """

    @pytest.mark.parametrize(
        ("typo", "suggestion"),
        [
            ("inventary", "inventory"),
            ("Inventory", "inventory"),
            ("REPORTS", "reports"),
            ("reports-save", "reports"),
            ("catalog", "catalogue"),
        ],
    )
    def test_a_near_miss_suggests_the_real_command_and_refuses(
        self,
        typo: str,
        suggestion: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(
            cli, "_serve_main", lambda _argv: pytest.fail("the server must not start")
        )

        assert cli.main([typo]) == 2

        err = capsys.readouterr().err
        assert typo in err
        assert f"dex-lens {suggestion}" in err

    def test_a_bare_word_that_is_a_real_directory_is_still_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The reproduced defect: the typo named a folder, so it got served."""
        (tmp_path / "inventary").mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            cli, "_serve_main", lambda _argv: pytest.fail("the server must not start")
        )

        assert cli.main(["inventary"]) == 2
        assert "dex-lens inventory" in capsys.readouterr().err

    def test_an_ambiguous_folder_name_asks_for_an_explicit_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`vault` is a plausible folder and a plausible verb. Choose safety."""
        (tmp_path / "vault").mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            cli, "_serve_main", lambda _argv: pytest.fail("the server must not start")
        )

        assert cli.main(["vault"]) == 2

        err = capsys.readouterr().err
        assert "./vault" in err

    def test_the_refusal_never_names_the_frozen_journeys_vocabulary(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            cli, "_serve_main", lambda _argv: pytest.fail("the server must not start")
        )

        cli.main(["Inventory"])

        assert "approved root" not in capsys.readouterr().err

    @pytest.mark.parametrize("written", ["/tmp", "./here", "~/here", ".", "..", "a/b"])
    def test_anything_written_as_a_path_still_opens_the_browser_journey(
        self, written: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The module docstring's promise, held from the other side."""
        served: list[list[str]] = []
        monkeypatch.setattr(cli, "_serve_main", lambda argv: served.append(list(argv)) or 0)

        assert cli.main([written]) == 0
        assert served == [[written]]

    def test_a_leading_flag_still_reaches_the_folder_doorway(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        served: list[list[str]] = []
        monkeypatch.setattr(cli, "_serve_main", lambda argv: served.append(list(argv)) or 0)

        assert cli.main(["--no-open", "./here"]) == 0
        assert served == [["--no-open", "./here"]]
