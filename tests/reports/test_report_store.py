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
