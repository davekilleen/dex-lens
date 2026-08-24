"""The evidence rule, enforced where skipping it is not an option.

"Every claim carries a quotation" is the rule the whole report format exists
to serve, and until now it lived only in the skill's prose. Prose holds until
the run is long and the assistant is tired. These tests hold it down at the
moment the report is written, which is the last point at which a thin
diagnosis can still be caught.

What is checked is structural, never wording: nothing here has an opinion
about how a finding should be phrased, only that it shows where it came from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capability_exchange.reports import cli
from capability_exchange.reports.store import missing_report_requirements

COMPLETE = """# Dex Lens: my vault — 2026-08-24

## What I read
- Inventory: /vault, 240 distinct items across 6,829 files
- Read in full: `CLAUDE.md`

## What is strong
### Meeting handling — Verified
> then re-open the person page and confirm the commitment appears
> - `skills/meetings/SKILL.md`
Closes the loop: it writes back and checks the write.

## Contradictions and fragility
I checked the rules in your instruction files against your skills and found
no conflicts.

## What happens next
- Nothing has changed on your machine.
"""


def _without(section: str) -> str:
    return COMPLETE.replace(section, "")


class TestWhatAReportMustShow:
    def test_a_complete_report_passes(self) -> None:
        assert missing_report_requirements(COMPLETE) == []

    def test_a_report_with_no_quotations_is_refused(self) -> None:
        """The whole rule, in one case: a judgement with nothing under it."""
        stripped = "\n".join(
            line for line in COMPLETE.splitlines() if not line.startswith(">")
        )

        problems = missing_report_requirements(stripped)

        assert any("quote something" in problem for problem in problems)

    def test_it_says_which_section_is_missing(self) -> None:
        problems = missing_report_requirements(_without("## What I read"))

        assert any("What I read" in problem for problem in problems)

    def test_a_report_that_never_says_nothing_changed_is_refused(self) -> None:
        problems = missing_report_requirements(_without("## What happens next"))

        assert any("What happens next" in problem for problem in problems)

    def test_a_scored_finding_with_no_evidence_is_named(self) -> None:
        report = COMPLETE + (
            "\n## Worth borrowing from Dex\n"
            "### Meeting Closeout (`meeting-closeout`)\n"
            "It would help you.\n"
            "\n## Considered and rejected\n- `account-planning` - no accounts here.\n"
        )

        problems = missing_report_requirements(report)

        assert any("Meeting Closeout" in problem for problem in problems)

    def test_an_honest_unknown_is_accepted_where_a_quote_is_not_possible(self) -> None:
        """The rubric working, not failing: unread means Unknown, and says so."""
        report = COMPLETE + (
            "\n## Worth borrowing from Dex\n"
            "### Meeting Closeout (`meeting-closeout`) - Unknown\n"
            "I did not read your meeting skill in full, so I cannot score it.\n"
            "\n## Considered and rejected\n- `account-planning` - no accounts here.\n"
        )

        assert missing_report_requirements(report) == []

    def test_a_report_that_never_hunted_for_contradictions_is_refused(self) -> None:
        """The most valuable finding in a diagnosis is also the easiest to
        quietly not go looking for."""
        problems = missing_report_requirements(
            _without("## Contradictions and fragility")
        )

        assert any("Contradictions" in problem for problem in problems)

    def test_an_empty_contradictions_heading_is_refused(self) -> None:
        """The heading surviving while the search never happened is the exact
        failure this guards: the reader cannot tell the difference."""
        report = COMPLETE.replace(
            "I checked the rules in your instruction files against your skills and found\n"
            "no conflicts.",
            "Nothing of note here.",
        )

        problems = missing_report_requirements(report)

        assert any("show the contradiction hunt" in problem for problem in problems)

    def test_finding_none_is_a_complete_answer(self) -> None:
        assert missing_report_requirements(COMPLETE) == []

    def test_a_two_sided_quoted_finding_passes(self) -> None:
        report = COMPLETE.replace(
            "I checked the rules in your instruction files against your skills and found\n"
            "no conflicts.",
            "### The calendar rule is broken by eight skills\n"
            "The rule:\n"
            "> Use Google Calendar. Do NOT use the local Apple Calendar MCP.\n"
            "> - `CLAUDE.md`\n"
            "What contradicts it:\n"
            "> calendar_get_events_with_attendees\n"
            "> - `skills/daily-plan-dave/SKILL.md`\n"
            "Why it matters: which instruction wins is unpredictable.",
        )

        assert missing_report_requirements(report) == []

    def test_a_shortlist_with_no_rejections_is_refused(self) -> None:
        """A shortlist with nothing ruled out cannot be told from one that
        never compared."""
        report = COMPLETE + (
            "\n## Worth borrowing from Dex\n"
            "### Meeting Closeout - Verified\n"
            "> your meeting skill stops at extraction\n"
            "> - `skills/meetings/SKILL.md`\n"
        )

        problems = missing_report_requirements(report)

        assert any("Considered and rejected" in problem for problem in problems)


    def test_the_word_unknown_in_passing_does_not_waive_the_quotation(self) -> None:
        """The waiver is for a finding labelled Unknown, not for any sentence
        that happens to contain the word.

        It used to be a substring test, so "it calls an unknown tool" — a
        confident, specific, entirely unquoted claim — passed the gate.
        """
        report = COMPLETE + (
            "\n## Worth borrowing from Dex\n"
            "### Meeting Closeout (`meeting-closeout`) - Verified\n"
            "Your meeting skill calls an unknown tool, so this would help.\n"
            "\n## Considered and rejected\n- `account-planning` - no accounts here.\n"
        )

        problems = missing_report_requirements(report)

        assert any("Meeting Closeout" in problem for problem in problems)

    def test_an_unknown_label_on_its_own_line_still_waives_it(self) -> None:
        report = COMPLETE + (
            "\n## Worth borrowing from Dex\n"
            "### Meeting Closeout (`meeting-closeout`)\n"
            "Confidence: Unknown\n"
            "I did not read your meeting skill in full.\n"
            "\n## Considered and rejected\n- `account-planning` - no accounts here.\n"
        )

        assert missing_report_requirements(report) == []


class TestTheGateInTheCommand:
    @pytest.fixture
    def reports_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        directory = tmp_path / "state" / "reports"
        monkeypatch.setattr(cli, "default_report_directory", lambda _roots: directory)
        return directory

    def test_saving_a_thin_report_writes_nothing_and_says_what_is_missing(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        thin = tmp_path / "thin.md"
        thin.write_text("# Dex Lens\n\nYour system looks good.\n", encoding="utf-8")

        assert cli.reports_main(["save", str(thin)]) == 2

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "not finished" in captured.err
        assert "quote something" in captured.err
        assert not reports_directory.exists(), "a refused report must leave nothing behind"

    def test_check_reports_the_same_thing_without_saving(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        good = tmp_path / "good.md"
        good.write_text(COMPLETE, encoding="utf-8")

        assert cli.reports_main(["check", str(good)]) == 0

        assert "ready to save" in capsys.readouterr().err
        assert not reports_directory.exists(), "check writes nothing, even when happy"

    def test_check_applies_the_same_rule_save_does_about_the_last_look(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A check that approves what save refuses is worse than no check.

        `check` used to skip the "account for the previous report" rule, so it
        gave a green light that cost the reader a rewrite they had been told
        they had already avoided.
        """
        first = tmp_path / "first.md"
        first.write_text(COMPLETE, encoding="utf-8")
        assert cli.reports_main(["save", str(first), "--label", "vault"]) == 0
        capsys.readouterr()
        second = tmp_path / "second.md"
        second.write_text(COMPLETE.replace("2026-08-24", "2026-09-01"), encoding="utf-8")

        checked = cli.reports_main(["check", str(second), "--label", "vault"])
        check_said = capsys.readouterr().err
        saved = cli.reports_main(["save", str(second), "--label", "vault"])
        save_said = capsys.readouterr().err

        assert (checked, saved) == (2, 2)
        assert "say what has changed" in check_said
        assert "say what has changed" in save_said

    def test_check_fails_on_a_thin_report(
        self,
        tmp_path: Path,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        thin = tmp_path / "thin.md"
        thin.write_text("# Dex Lens\n\nAll good.\n", encoding="utf-8")

        assert cli.reports_main(["check", str(thin)]) == 2
        assert "not finished" in capsys.readouterr().err
