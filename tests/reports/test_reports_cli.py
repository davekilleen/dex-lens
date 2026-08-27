"""`dex-lens reports`, exercised the way the skill actually calls it.

The skill saves a report at the end of every diagnosis and reads the previous
one at the start of the next, so the two things worth holding down are that
saving tells the caller where the *previous* report is, and that "there is no
previous report" is an answer rather than a crash or an empty success.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capability_exchange.reports import cli


@pytest.fixture
def reports_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "state" / "reports"
    monkeypatch.setattr(cli, "default_report_directory", lambda _roots: directory)
    monkeypatch.setattr(cli, "_ledger_gate", lambda _path: (None, []))
    return directory


def _report(tmp_path: Path, text: str, name: str = "report.md") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _complete(title: str) -> str:
    """A report that clears the evidence gate, so tests exercise the flow.

    Anything thinner is refused at save time by design, which is what
    :class:`TestTheEvidenceGate` is for.
    """
    return (
        f"# {title}\n\n"
        "## What I read\n"
        "- Inventory: /tmp/vault, 12 distinct items across 40 files\n\n"
        "## What is working especially well\n"
        "### Careful inventory boundaries\n"
        "> 6,405 of the 6,829 files (94%) sit inside `worktrees` folders\n"
        "> - `inventory.md`\n"
        "The setup distinguishes active work from old working copies.\n\n"
        "## What Dex should learn from you\n"
        "No transferable method cleared the evidence bar.\n\n"
        "## Worth borrowing from Dex\n"
        "No Dex addition cleared the evidence bar this time.\n\n"
        "## Fragility and contradictions\n"
        "I checked the rules in `~/.claude/CLAUDE.md` against your skills and "
        "found no conflicts.\n\n"
        "## Coverage and limits\n"
        "- Every signed catalogue entry has a disposition in the accompanying ledger.\n"
        "- Live operating-system state was not assessed.\n\n"
        "## Since the last look\n"
        "- Nothing has changed since then.\n\n"
        "## What happens next\n"
        "- Nothing has changed on your machine.\n"
    )


class TestSave:
    def test_it_prints_where_the_report_landed(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source = _report(tmp_path, _complete("Dex Lens: my vault"))

        assert cli.reports_main(["save", source, "--label", "vault"]) == 0

        captured = capsys.readouterr()
        saved = Path(captured.out.strip())
        assert saved.parent == reports_directory
        assert saved.read_text(encoding="utf-8").startswith("# Dex Lens: my vault")
        assert "nothing in that folder was changed" in captured.err

    def test_save_keeps_the_ledger_beside_the_report(
        self,
        tmp_path: Path,
        reports_directory: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger = tmp_path / "ledger.json"
        ledger.write_text('{"catalogue_version":5}', encoding="utf-8")
        monkeypatch.setattr(cli, "_ledger_gate", lambda _path: (object(), []))

        assert (
            cli.reports_main(
                ["save", _report(tmp_path, _complete("With ledger")), "--ledger", str(ledger)]
            )
            == 0
        )

        saved = Path(capsys.readouterr().out.strip())
        assert saved.with_suffix(".ledger.json").read_text(encoding="utf-8") == (
            '{"catalogue_version":5}'
        )

    def test_the_first_report_says_there_is_nothing_to_compare_with(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert cli.reports_main(["save", _report(tmp_path, _complete("First"))]) == 0

        assert "first report on this machine" in capsys.readouterr().err

    def test_a_later_report_points_at_the_one_before_it(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """This line is what makes `what changed since last time` possible."""
        cli.reports_main(["save", _report(tmp_path, _complete("First"), "first.md")])
        first = Path(capsys.readouterr().out.strip())

        assert cli.reports_main(["save", _report(tmp_path, _complete("Second"), "second.md")]) == 0

        captured = capsys.readouterr()
        assert str(first) in captured.err
        assert "say what has changed since" in captured.err

    def test_it_reads_the_report_from_standard_input(
        self,
        reports_directory: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", _Stdin(_complete("Piped")))

        assert cli.reports_main(["save", "-"]) == 0
        saved = Path(capsys.readouterr().out.strip())
        assert saved.read_text(encoding="utf-8") == _complete("Piped")

    def test_a_missing_file_is_refused_without_writing_anything(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert cli.reports_main(["save", str(tmp_path / "absent.md")]) == 2

        assert "no such report file" in capsys.readouterr().err
        assert not reports_directory.exists()

    def test_an_empty_report_is_refused(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert cli.reports_main(["save", _report(tmp_path, "\n \n")]) == 2

        assert "not a report" in capsys.readouterr().err

    def test_for_a_folder_that_would_contain_app_storage_it_refuses(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The read-only promise is checked before the write, not after it."""
        vault = tmp_path / "vault"
        vault.mkdir()
        monkeypatch.setenv("XDG_STATE_HOME", str(vault / "state"))

        source = _report(tmp_path, _complete("X"))

        assert cli.reports_main(["save", source, "--for", str(vault)]) == 2
        assert "outside the approved read scope" in capsys.readouterr().err


class TestAccountingForTheLastLook:
    """A second look that repeats the first teaches people to stop reading."""

    def test_a_second_report_that_ignores_the_first_is_refused(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cli.reports_main(["save", _report(tmp_path, _complete("First"), "a.md")])
        capsys.readouterr()
        without = _complete("Second").replace("## Since the last look", "## Notes")

        assert cli.reports_main(["save", _report(tmp_path, without, "b.md")]) == 2

        captured = capsys.readouterr()
        assert "say what has changed" in captured.err
        assert len(list(reports_directory.glob("*.md"))) == 1

    def test_the_first_report_needs_no_comparison(
        self,
        tmp_path: Path,
        reports_directory: Path,
    ) -> None:
        first = _complete("First").replace("## Since the last look", "## Notes")

        assert cli.reports_main(["save", _report(tmp_path, first)]) == 0

    def test_nothing_has_changed_is_a_complete_answer(
        self,
        tmp_path: Path,
        reports_directory: Path,
    ) -> None:
        cli.reports_main(["save", _report(tmp_path, _complete("First"), "a.md")])

        assert cli.reports_main(["save", _report(tmp_path, _complete("Second"), "b.md")]) == 0

    def test_a_different_system_is_not_asked_to_compare_itself_with_another(
        self,
        tmp_path: Path,
        reports_directory: Path,
    ) -> None:
        """Two systems keep two histories; the work vault is not the home one."""
        cli.reports_main(["save", _report(tmp_path, _complete("Work"), "a.md"), "--label", "work"])
        home = _complete("Home").replace("## Since the last look", "## Notes")

        assert (
            cli.reports_main(["save", _report(tmp_path, home, "b.md"), "--label", "home"]) == 0
        )


class TestListAndLast:
    def test_no_reports_yet_is_said_plainly(
        self, reports_directory: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.reports_main([]) == 1

        assert "no report has been saved" in capsys.readouterr().err

    def test_the_listing_shows_every_report_newest_first(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cli.reports_main(["save", _report(tmp_path, _complete("Older"), "a.md")])
        cli.reports_main(["save", _report(tmp_path, _complete("Newer"), "b.md")])
        capsys.readouterr()

        assert cli.reports_main(["list"]) == 0

        out = capsys.readouterr().out
        assert out.index("Newer") < out.index("Older")
        assert str(reports_directory) in out

    def test_last_prints_the_most_recent_report_in_full(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cli.reports_main(["save", _report(tmp_path, _complete("Older"), "a.md")])
        cli.reports_main(["save", _report(tmp_path, _complete("Newer"), "b.md")])
        capsys.readouterr()

        assert cli.reports_main(["--last"]) == 0

        captured = capsys.readouterr()
        assert captured.out == _complete("Newer")
        assert "2026" in captured.err or ".md" in captured.err

    def test_last_with_nothing_saved_exits_non_zero_and_prints_no_report(
        self, reports_directory: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A caller must be able to tell `first run` from `nothing changed`."""
        assert cli.reports_main(["last"]) == 1

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "no report has been saved" in captured.err

    def test_path_only_gives_a_path_a_caller_can_read_next(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cli.reports_main(["save", _report(tmp_path, _complete("One"))])
        capsys.readouterr()

        assert cli.reports_main(["last", "--path-only"]) == 0

        printed = Path(capsys.readouterr().out.strip())
        assert printed.read_text(encoding="utf-8") == _complete("One")


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


class TestTheLabelMeansOneThing:
    """`--label` names one system, wherever in the line it is written.

    It used to mean three things. Before the action it was silently dropped by
    the subparser's own default, so a report meant for "my-vault" was filed
    under "diagnosis" and the success line said nothing about it. After
    `list` it narrowed nothing. After `last` it was rejected outright. The
    person's report was, in effect, invisible to every command they would use
    to find it again.
    """

    def _saved_name(self, capsys: pytest.CaptureFixture[str]) -> str:
        return Path(capsys.readouterr().out.strip()).name

    def test_the_label_before_the_action_is_the_label_it_is_saved_under(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source = _report(tmp_path, _complete("Vault"))

        assert cli.reports_main(["--label", "my-vault", "save", source]) == 0

        assert self._saved_name(capsys).endswith("--my-vault.md")

    def test_the_label_after_the_action_still_means_the_same_thing(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """This is the position the skill writes, so it must not change."""
        source = _report(tmp_path, _complete("Vault"))

        assert cli.reports_main(["save", source, "--label", "my-vault"]) == 0

        assert self._saved_name(capsys).endswith("--my-vault.md")

    @pytest.mark.parametrize(
        "argv",
        [
            ["--label", "my-vault", "list"],
            ["list", "--label", "my-vault"],
            ["--label", "my-vault"],
        ],
        ids=["leading", "trailing", "no-action"],
    )
    def test_a_saved_report_can_be_listed_by_its_label(
        self,
        argv: list[str],
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cli.reports_main(["--label", "my-vault", "save", _report(tmp_path, _complete("V"))])
        capsys.readouterr()

        assert cli.reports_main(argv) == 0

        assert "my-vault" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "argv",
        [["last", "--label", "my-vault"], ["--label", "my-vault", "--last"]],
        ids=["trailing", "leading"],
    )
    def test_the_last_report_can_be_asked_for_by_label(
        self,
        argv: list[str],
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cli.reports_main(["save", _report(tmp_path, _complete("V")), "--label", "my-vault"])
        capsys.readouterr()

        assert cli.reports_main(argv) == 0

        assert capsys.readouterr().out == _complete("V")

    def test_another_system_label_finds_nothing_rather_than_the_wrong_report(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Two systems, two baselines: narrowing must actually narrow."""
        cli.reports_main(["save", _report(tmp_path, _complete("V")), "--label", "my-vault"])
        capsys.readouterr()

        assert cli.reports_main(["last", "--label", "other-vault"]) == 1

    def test_the_same_label_written_twice_is_accepted(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source = _report(tmp_path, _complete("V"))

        exit_code = cli.reports_main(["--label", "my-vault", "save", source, "--label", "my-vault"])

        assert exit_code == 0
        assert self._saved_name(capsys).endswith("--my-vault.md")

    def test_two_different_labels_in_one_line_are_refused(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Ambiguous is refused, not guessed at: one of the two would lose,
        and whichever lost would be filed somewhere nobody looks."""
        source = _report(tmp_path, _complete("V"))

        with pytest.raises(SystemExit) as exit_code:
            cli.reports_main(["--label", "work", "save", source, "--label", "home"])

        assert exit_code.value.code == 2
        assert "--label was given twice" in capsys.readouterr().err
        assert not reports_directory.exists()


class TestAFolderThePersonOwns:
    """One foreign file in the reports folder must not cost them the run."""

    @pytest.fixture
    def hostile(self, reports_directory: Path) -> Path:
        reports_directory.mkdir(parents=True)
        (reports_directory / "my-notes.md").write_bytes(
            "Notes on the café project\n".encode("latin-1")
        )
        (reports_directory / "a-folder.md").mkdir()
        (reports_directory / "dangling.md").symlink_to(reports_directory / "gone.md")
        return reports_directory

    def test_saving_survives_a_file_it_cannot_read(
        self,
        tmp_path: Path,
        hostile: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The severe one: the diagnosis was lost to someone else's note."""
        assert cli.reports_main(["save", _report(tmp_path, _complete("Today"))]) == 0

        saved = Path(capsys.readouterr().out.strip())
        assert saved.read_text(encoding="utf-8") == _complete("Today")

    def test_listing_survives_it_and_shows_it(
        self, hostile: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.reports_main(["list"]) == 0

        assert "my-notes.md" in capsys.readouterr().out

    def test_last_prints_what_could_be_read_and_says_it_could_not_read_it_all(
        self, hostile: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Degraded out loud, never silently: the file itself is untouched."""
        assert cli.reports_main(["last"]) == 0

        captured = capsys.readouterr()
        assert captured.out.startswith("Notes on the caf")
        assert "\ufffd" in captured.out
        assert "not UTF-8" in captured.err
        assert (hostile / "my-notes.md").read_bytes() == (
            "Notes on the café project\n".encode("latin-1")
        )

    def test_a_report_that_is_not_utf8_is_refused_rather_than_mangled(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A dated file holding a mangled diagnosis is read by the next run as
        what was found."""
        source = tmp_path / "report.md"
        source.write_bytes(_complete("Café").encode("latin-1"))

        assert cli.reports_main(["save", str(source)]) == 2

        assert "must be UTF-8" in capsys.readouterr().err
        assert not reports_directory.exists()
