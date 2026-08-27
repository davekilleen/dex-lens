"""Dated reports, and the two promises they have to keep.

A report is the only durable output of a diagnosis, so the store has exactly
two jobs it must not get wrong: never write inside the folder being inspected,
and never lose or silently replace a report that was already written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_exchange.reports.store import (
    LensReportStore,
    default_report_directory,
)

NOW = datetime(2026, 8, 24, 19, 2, 35, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> LensReportStore:
    return LensReportStore(tmp_path / "reports")


class TestWhereReportsGo:
    def test_the_directory_is_app_storage_not_the_inspected_folder(
        self, tmp_path: Path
    ) -> None:
        environ = {"XDG_STATE_HOME": str(tmp_path / "state")}
        directory = default_report_directory((tmp_path / "vault",), environ=environ)

        assert directory == (tmp_path / "state" / "dex-lens" / "reports").resolve()
        assert not directory.is_relative_to(tmp_path / "vault")

    def test_it_refuses_a_reports_directory_inside_an_inspected_root(
        self, tmp_path: Path
    ) -> None:
        """The read-only promise, checked rather than assumed.

        If app storage were ever configured inside the folder under
        inspection, saving a report would write into the system Lens promised
        never to touch. That must raise, not warn.
        """
        vault = tmp_path / "vault"
        environ = {"XDG_STATE_HOME": str(vault / "state")}

        with pytest.raises(ValueError, match="outside the approved read scope"):
            default_report_directory((vault,), environ=environ)


class TestSaving:
    def test_it_writes_a_dated_file_and_says_where(self, store: LensReportStore) -> None:
        saved = store.save("# Dex Lens: my vault\n\nFindings.\n", label="Vault", now=NOW)

        assert saved.path.name == "2026-08-24T190235Z--vault.md"
        assert saved.path.read_text(encoding="utf-8").startswith("# Dex Lens: my vault")
        assert saved.title == "Dex Lens: my vault"
        assert saved.label == "vault"

    def test_a_second_report_in_the_same_second_does_not_replace_the_first(
        self, store: LensReportStore
    ) -> None:
        """These files are the only record that a run happened."""
        first = store.save("# One\n", now=NOW)
        second = store.save("# Two\n", now=NOW)

        assert first.path != second.path
        assert first.path.read_text(encoding="utf-8") == "# One\n"
        assert second.path.read_text(encoding="utf-8") == "# Two\n"

    def test_an_empty_report_is_refused(self, store: LensReportStore) -> None:
        """A dated empty file reads to the next run as `nothing was found`."""
        with pytest.raises(ValueError, match="no content"):
            store.save("   \n\n")

        assert store.list() == []


class TestFindingTheLastOne:
    def test_nothing_saved_yet_is_none_not_an_error(self, store: LensReportStore) -> None:
        assert store.last() is None
        assert store.list() == []

    def test_the_most_recent_report_comes_back_first(self, store: LensReportStore) -> None:
        store.save("# Older\n", now=NOW)
        newer = store.save("# Newer\n", now=NOW.replace(day=25))

        assert store.last() is not None
        assert store.last().path == newer.path
        assert [report.title for report in store.list()] == ["Newer", "Older"]

    def test_a_second_report_in_the_same_second_keeps_its_label(
        self, store: LensReportStore
    ) -> None:
        """The collision counter must not be read back as part of the label.

        It was: the second report of the second landed as `--vault-2.md` and
        every lookup by label missed it — the listing, and worse, the baseline
        the next run compares itself against.
        """
        store.save("# First\n\nOne.\n", label="vault", now=NOW)
        second = store.save("# Second\n\nTwo.\n", label="vault", now=NOW)

        assert second.label == "vault"
        assert [report.label for report in store.list(label="vault")] == ["vault", "vault"]
        assert store.last(label="vault").path == second.path
        assert store.last(label="vault").title == "Second"

    def test_a_label_that_ends_in_a_number_is_still_its_own_label(
        self, store: LensReportStore
    ) -> None:
        """"run-2" is a label someone chose, not the second report of "run"."""
        saved = store.save("# Numbered\n", label="run-2", now=NOW)

        assert saved.label == "run-2"
        assert store.last(label="run-2").path == saved.path
        assert store.list(label="run") == []

    def test_labels_keep_two_systems_apart(self, store: LensReportStore) -> None:
        """Someone with a work vault and a personal one has two baselines."""
        work = store.save("# Work\n", label="work", now=NOW)
        store.save("# Home\n", label="home", now=NOW.replace(day=25))

        assert store.last(label="work").path == work.path
        assert [report.label for report in store.list(label="home")] == ["home"]

    def test_a_file_lens_did_not_name_is_still_listed(
        self, store: LensReportStore
    ) -> None:
        """Skipping an unfamiliar name would answer `what did last time say?`
        with the wrong file."""
        store.directory.mkdir(parents=True)
        (store.directory / "hand-written-notes.md").write_text("# Notes\n", encoding="utf-8")

        listed = store.list()

        assert [report.title for report in listed] == ["Notes"]
        assert listed[0].saved_at.tzinfo is not None


def test_a_listing_line_reads_without_instructions(store: LensReportStore) -> None:
    saved = store.save("# Dex Lens: my vault\n", label="vault", now=NOW)

    assert saved.listing_line() == "2026-08-24 19:02 UTC  vault  Dex Lens: my vault"


class TestAFolderThePersonOwns:
    """The reports directory belongs to them, so it will contain their things.

    They are told to keep it, share it, and put what they like in it, which
    means one `latin-1` note, one folder, one broken link. Every one of those
    used to end `list`, `last` and — worst — `save` in a traceback, with the
    diagnosis of that run still unwritten and now unrecoverable.
    """

    @pytest.fixture
    def hostile(self, store: LensReportStore) -> LensReportStore:
        store.directory.mkdir(parents=True)
        (store.directory / "my-notes.md").write_bytes(
            "Notes on the café project\n".encode("latin-1")
        )
        (store.directory / "readable.md").write_text("# Kept by hand\n", encoding="utf-8")
        (store.directory / "a-folder.md").mkdir()
        (store.directory / "dangling.md").symlink_to(store.directory / "gone.md")
        return store

    def test_a_file_in_another_encoding_is_still_listed(
        self, hostile: LensReportStore
    ) -> None:
        """Hiding it would answer "what did the last run say?" with the wrong
        file — the exact failure listing an unfamiliar name exists to avoid."""
        names = [report.path.name for report in hostile.list()]

        assert "my-notes.md" in names
        assert "readable.md" in names

    def test_what_could_be_read_of_the_title_comes_back(
        self, hostile: LensReportStore
    ) -> None:
        (hostile.directory / "titled.md").write_bytes("# Caf\xe9 notes\n".encode("latin-1"))

        titled = next(r for r in hostile.list() if r.path.name == "titled.md")

        assert titled.title.startswith("Caf")
        assert titled.is_valid_utf8 is False
        assert "notes" in titled.read()

    def test_saving_still_works_with_all_of_it_in_the_folder(
        self, hostile: LensReportStore
    ) -> None:
        """The one that loses work: the report of the run that just finished."""
        saved = hostile.save("# Today\n\nFindings.\n", now=NOW)

        assert saved.path.read_text(encoding="utf-8").startswith("# Today")
        assert saved.path.name in [report.path.name for report in hostile.list()]

    def test_the_most_recent_report_can_still_be_found(
        self, hostile: LensReportStore
    ) -> None:
        assert hostile.last() is not None

    def test_what_holds_no_report_is_not_listed_as_one(
        self, hostile: LensReportStore
    ) -> None:
        """A folder and a broken link named `*.md` are not reports, and
        neither is an error."""
        names = [report.path.name for report in hostile.list()]

        assert "a-folder.md" not in names
        assert "dangling.md" not in names

    def test_a_dated_name_on_something_unreadable_is_not_listed(
        self, hostile: LensReportStore
    ) -> None:
        """The name alone must not be enough to become a report."""
        (hostile.directory / "2026-08-24T190235Z--vault.md").symlink_to(
            hostile.directory / "also-gone.md"
        )

        assert hostile.list(label="vault") == []


class TestSaveResult:
    def test_it_renders_typed_markdown_and_verifies_the_three_digests(
        self, store: LensReportStore
    ) -> None:
        from tests.diagnosis.test_report_model import run_identity
        from tests.evals.real_session_fixture import real_session_ledger

        from capability_exchange.diagnosis.orchestrator import DiagnosisResult
        from capability_exchange.diagnosis.report import (
            ReportModel,
            canonical_fact_block,
            canonical_ledger_digest,
        )

        ledger = real_session_ledger()
        result = DiagnosisResult(
            report=ReportModel.from_result(
                run_identity=run_identity(),
                ledger=ledger,
                ledger_sha256=canonical_ledger_digest(ledger),
            ),
            ledger=ledger,
        )

        saved = store.save_result(result, label="vault", now=NOW)

        markdown = saved.path.read_text(encoding="utf-8")
        assert canonical_fact_block(ledger) in markdown
        assert saved.ledger_path.is_file()
        assert saved.result_path.is_file()
        stored = saved.result_path.read_text(encoding="utf-8")
        assert canonical_ledger_digest(ledger) in stored

    def test_it_refuses_arbitrary_markdown_without_a_typed_result(
        self, store: LensReportStore
    ) -> None:
        with pytest.raises(ValueError, match="typed result"):
            store.save_result("# Invented prose\n")
