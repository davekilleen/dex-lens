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
        "## The mirror\n"
        "### Leftover working copies\n"
        "> 6,405 of the 6,829 files (94%) sit inside `worktrees` folders\n"
        "> - `inventory.md`\n"
        "What it costs: 6.2 GB, and every count you see is wrong.\n\n"
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
