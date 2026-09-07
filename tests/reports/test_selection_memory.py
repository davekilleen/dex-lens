"""Selection memory: what past runs examined by choice, read back mechanically.

Design item 10 (2026-09-07): the focused selection recorded in a report's
"What you decided" section — and each share-back offer's recorded fate — must
survive the conversation that produced it. The reports store derives, from
every saved report and nothing else, which families have ever been selected
for a deep dive, which of the 14 signed manifest families have never been
examined by choice, and which share-back ideas already have a fate — so the
next run can open with "last time you looked at backup and memory; these N
areas have never had a deep dive — want one?" and the once-per-idea-ever rule
holds across runs. Everything here is report-derived: no host-invented memory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.diagnosis.test_run import NOW, RUN_ID

from capability_exchange.diagnosis.comparison import ComparisonLedger
from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS
from capability_exchange.diagnosis.report import ReportModel, canonical_ledger_digest
from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    INPUT_SCHEMA_VERSION,
    RunIdentity,
)
from capability_exchange.reports import cli
from capability_exchange.reports.store import LensReportStore, selection_memory

SELECTED = (
    "backup-and-restore-confidence",
    "durable-work-memory",
    "proactive-health-and-recovery",
)
UNSELECTED = tuple(sorted(set(WOW_EXPECTATIONS) - set(SELECTED)))


def _focused_ledger() -> ComparisonLedger:
    return ComparisonLedger.model_validate(
        {
            "catalogue_version": 1,
            "catalogue_sha256": "a" * 64,
            "capabilities": [],
            "entries": [
                {
                    "capability_id": "unassigned",
                    "catalogue_id": "invented-capability-000",
                    "disposition": "not-relevant",
                    "evidence_references": [],
                    "method_compared": False,
                    "reason": "Not relevant to the invented setup.",
                }
            ],
            "reciprocal_answer": "No transferable method cleared the evidence bar.",
            "focus_selected_family_ids": list(SELECTED),
            "focus_unselected_family_ids": list(UNSELECTED),
        }
    )


def _engine_rendered_focused_report() -> str:
    """A genuine engine render, so the memory reads what the engine writes."""

    ledger = _focused_ledger()
    report = ReportModel.from_result(
        run_identity=RunIdentity(
            run_id=RUN_ID,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            analysis_mode="focused-analysis",
            created_at=NOW,
        ),
        ledger=ledger,
        ledger_sha256=canonical_ledger_digest(ledger),
    )
    return report.render_markdown(ledger)


def _host_report(decided: str, *, title: str = "Host report") -> str:
    return f"# {title}\n\n## What you decided\n{decided}\n"


def _store(tmp_path: Path) -> LensReportStore:
    return LensReportStore(tmp_path / "reports")


def _stamp(day: int) -> datetime:
    return datetime(2026, 9, day, 9, 0, 0, tzinfo=UTC)


class TestSelectionMemoryFromSavedReports:
    def test_a_saved_focused_report_yields_the_never_examined_remainder(
        self, tmp_path: Path
    ) -> None:
        """The plan's red test: save a report from a 3-family focused run and
        the memory names the 11 manifest families never examined by choice."""

        store = _store(tmp_path)
        store.save(_engine_rendered_focused_report(), now=_stamp(1))

        memory = selection_memory(store.list())

        assert memory.last_selected == SELECTED
        assert memory.ever_selected == SELECTED
        assert len(memory.never_examined) == 11
        assert memory.never_examined == tuple(
            family_id for family_id in WOW_EXPECTATIONS if family_id not in SELECTED
        )

    def test_ever_selected_accumulates_across_runs(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.save(
            _host_report("- Focused this run on: meeting-follow-through"),
            now=_stamp(1),
        )
        store.save(_engine_rendered_focused_report(), now=_stamp(2))

        memory = selection_memory(store.list())

        assert memory.last_selected == SELECTED
        assert "meeting-follow-through" in memory.ever_selected
        assert "meeting-follow-through" not in memory.never_examined
        assert len(memory.never_examined) == 10

    def test_no_recorded_selection_leaves_the_whole_manifest_unexamined(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        store.save(_host_report("No decisions were on the table this time."), now=_stamp(1))

        memory = selection_memory(store.list())

        assert memory.last_selected == ()
        assert memory.never_examined == WOW_EXPECTATIONS

    def test_share_back_fates_are_read_back_with_the_latest_fate_winning(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        store.save(
            _host_report("- Share-back idea `weekly-ledger` — deferred"),
            now=_stamp(1),
        )
        store.save(
            _host_report(
                '- Share-back idea `weekly-ledger` — declined, because "not now"'
            ),
            now=_stamp(2),
        )

        memory = selection_memory(store.list())

        assert len(memory.share_back_fates) == 1
        fate = memory.share_back_fates[0]
        assert fate.idea == "weekly-ledger"
        assert fate.fate == "declined"
        assert fate.recorded_at == _stamp(2)

    def test_placeholder_and_malformed_lines_contribute_nothing(
        self, tmp_path: Path
    ) -> None:
        """Template placeholders and free prose are not memory."""

        store = _store(tmp_path)
        store.save(
            _host_report(
                "- Focused this run on: <family-ids, exactly as the engine "
                "recorded them>\n"
                "- Share-back idea `<idea-slug>` — shared | declined | deferred\n"
                "We talked about focusing on backup next time."
            ),
            now=_stamp(1),
        )

        memory = selection_memory(store.list())

        assert memory.last_selected == ()
        assert memory.share_back_fates == ()

    def test_lines_outside_the_decided_section_are_not_memory(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        store.save(
            "# Report\n\n## What I read\n"
            "- Focused this run on: meeting-follow-through\n\n"
            "## What you decided\nNo decisions were on the table this time.\n",
            now=_stamp(1),
        )

        memory = selection_memory(store.list())

        assert memory.ever_selected == ()


@pytest.fixture
def reports_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "state" / "reports"
    monkeypatch.setattr(cli, "default_report_directory", lambda _roots: directory)
    monkeypatch.setattr(cli, "_ledger_gate", lambda _path: (None, []))
    return directory


class TestReportsLastSurfacesTheMemory:
    """``reports --last`` is where the next run reads its opening from."""

    def test_last_speaks_the_selection_memory(
        self,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        LensReportStore(reports_directory).save(
            _engine_rendered_focused_report(), now=_stamp(1)
        )

        assert cli.reports_main(["last"]) == 0

        err = capsys.readouterr().err
        assert (
            "last time the focused deep dives were: "
            "backup-and-restore-confidence, durable-work-memory, "
            "proactive-health-and-recovery." in err
        )
        assert "11 of the 14 signed capability areas have never had a focused deep dive" in err
        assert "meeting-follow-through" in err
        assert "one ask away" in err

    def test_last_speaks_recorded_share_back_fates(
        self,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        LensReportStore(reports_directory).save(
            _host_report("- Share-back idea `weekly-ledger` — declined"),
            now=_stamp(1),
        )

        assert cli.reports_main(["last"]) == 0

        err = capsys.readouterr().err
        assert "share-back idea `weekly-ledger` — declined" in err
        assert "never offered again" in err

    def test_a_history_with_no_focus_still_names_the_whole_manifest(
        self,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        LensReportStore(reports_directory).save(
            _host_report("No decisions were on the table this time."),
            now=_stamp(1),
        )

        assert cli.reports_main(["last"]) == 0

        err = capsys.readouterr().err
        assert "14 of the 14 signed capability areas have never had a focused deep dive" in err
        assert "last time the focused deep dives were" not in err

    def test_path_only_stays_machine_readable(
        self,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        LensReportStore(reports_directory).save(
            _engine_rendered_focused_report(), now=_stamp(1)
        )

        assert cli.reports_main(["last", "--path-only"]) == 0

        captured = capsys.readouterr()
        assert "deep dive" not in captured.err
        assert captured.out.strip().endswith(".md")

    def test_the_memory_is_scoped_to_the_label_asked_for(
        self,
        reports_directory: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store = LensReportStore(reports_directory)
        store.save(_engine_rendered_focused_report(), label="vault-a", now=_stamp(1))
        store.save(
            _host_report("- Focused this run on: meeting-follow-through"),
            label="vault-b",
            now=_stamp(2),
        )

        assert cli.reports_main(["last", "--label", "vault-a"]) == 0

        err = capsys.readouterr().err
        assert "backup-and-restore-confidence" in err
        assert "last time the focused deep dives were: meeting-follow-through" not in err
