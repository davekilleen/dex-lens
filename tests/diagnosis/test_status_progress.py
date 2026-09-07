"""Item 8: live status progress that speaks in the person's units.

Design: docs/superpowers/plans/2026-09-07-dex-lens-10x-experience.md, item 8.
Per the completion goal every guarantee here was observed failing first on the
unchanged tree: ``status`` named only the stage and the next action — no
per-family completion, no elapsed time, no bounded pace estimate — and
``WorkReceipt`` carried no engine-recorded timestamp any honest estimate could
be derived from.  Twenty-six silent minutes is how an honest run still felt
broken; these tests pin the fix.

The estimate is observed pace, never a promise: it is absent until at least
one packet holds a recorded completion timestamp, and an old saved run whose
receipts predate the timestamp still loads and reports its progress with the
estimate absent.  Everything except the elapsed clock is byte-stable for one
stored run state.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.diagnosis.test_focused_mode import (
    SELECTED,
    _focused_catalogue,
    _focused_fingerprint,
    _verdicts_for_packet,
)
from tests.diagnosis.test_real_comparer_guided_run import RealComparerHarness

from capability_exchange.diagnosis.defaults import (
    CachedCatalogueLoader,
    UnknownUntilProposedComparer,
)
from capability_exchange.diagnosis.orchestrator import (
    DeterministicDiagnosisEngine,
    PrepareDiagnosisRequest,
)
from capability_exchange.diagnosis.run import DiagnosisStage
from capability_exchange.diagnosis.work import AnalysisMode, WorkReceipt

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

#: The nine issued packets of a guided/focused queue: eight normal roles plus
#: the locked sceptical reconciler.
QUEUE_SIZE = 9

#: The synthetic catalogue titles the family map derives (see the ``_family``
#: fixture: ``family_id.replace("-", " ").title()``), in the sorted family-id
#: order the progress rows must keep.
_BACKUP_TITLE = "Backup And Restore Confidence"
_MEMORY_TITLE = "Durable Work Memory"
_MEETING_TITLE = "Meeting Follow Through"


class _SteppingClock:
    """Injected engine clock the tests advance explicitly."""

    def __init__(self) -> None:
        self.now = NOW

    def advance(self, **kwargs: int) -> None:
        self.now = self.now + timedelta(**kwargs)

    def __call__(self) -> datetime:
        return self.now


def _inject_clock(harness: RealComparerHarness, clock: _SteppingClock) -> None:
    harness.engine = DeterministicDiagnosisEngine(
        run_store=harness.run_store,
        consent_authority=harness.consent_authority,
        collector=harness.collector,
        catalogue_loader=CachedCatalogueLoader(harness.store),
        comparer=UnknownUntilProposedComparer(harness.store),
        report_store=harness.report_store,
        clock=clock,
    )


def _clocked_harness(tmp_path: Path) -> tuple[RealComparerHarness, _SteppingClock]:
    harness = RealComparerHarness(
        tmp_path,
        catalogue=_focused_catalogue(),
        fingerprint=_focused_fingerprint(),
    )
    clock = _SteppingClock()
    _inject_clock(harness, clock)
    return harness, clock


def _run_at_planned(harness: RealComparerHarness, mode: AnalysisMode) -> str:
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=mode)
    )
    run_id = prepared.run_id
    if mode is AnalysisMode.FOCUSED:
        harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)
        harness.engine.focus(run_id, SELECTED)
    harness.run_to(run_id, DiagnosisStage.ANALYSIS_PLANNED)
    return run_id


def _submit_first_packets(
    harness: RealComparerHarness,
    run_id: str,
    *,
    count: int,
    clock: _SteppingClock,
    minutes_each: int = 1,
) -> None:
    """Complete the first ``count`` pending packets, one clock step apart."""

    for packet in harness.engine.pending_work(run_id)[:count]:
        clock.advance(minutes=minutes_each)
        harness.engine.submit_work(
            run_id, packet.packet_id, _verdicts_for_packet(packet)
        )


def test_status_on_a_half_complete_focused_run_carries_typed_progress(
    tmp_path: Path,
) -> None:
    """Per-family completion, findings, elapsed, and the bounded estimate.

    Two of nine packets are done, one minute apart, when the person asks
    three minutes later: elapsed is five minutes, the observed pace is one
    packet a minute, and seven packets remain — about seven minutes at this
    pace.  The backup family's dive is done with exactly one engine-counted
    finding; the first pending packet's family is running; the rest queue.
    """

    harness, clock = _clocked_harness(tmp_path)
    run_id = _run_at_planned(harness, AnalysisMode.FOCUSED)
    # Packet order is the closed role order: tools, automations (the backup
    # family's primary), people (meeting follow-through's primary), ...
    _submit_first_packets(harness, run_id, count=2, clock=clock)
    clock.advance(minutes=3)

    progress = harness.engine.status(run_id).progress
    assert progress is not None
    assert progress.packets_total == QUEUE_SIZE
    assert progress.packets_done == 2
    assert progress.packets_pending == QUEUE_SIZE - 2
    assert progress.elapsed_seconds == 5 * 60
    # Observed pace: two timed completions across two minutes -> 60s each.
    assert progress.estimated_remaining_seconds == (QUEUE_SIZE - 2) * 60

    rows = {dive.family_id: dive for dive in progress.families}
    assert set(rows) == set(SELECTED)
    assert rows["backup-and-restore-confidence"].state.value == "done"
    assert rows["backup-and-restore-confidence"].finding_count == 1
    assert rows["meeting-follow-through"].state.value == "running"
    assert rows["meeting-follow-through"].finding_count is None
    assert rows["durable-work-memory"].state.value == "queued"

    assert progress.headline == (
        f"{_BACKUP_TITLE} dive done — 1 finding; "
        f"{_MEMORY_TITLE} dive queued; "
        f"{_MEETING_TITLE} dive running; "
        "about 7 minutes left at this pace"
    )
    # The typed progress reaches every status wire (CLI --json and MCP both
    # serve dump_for_storage).
    payload = harness.engine.status(run_id).dump_for_storage()
    assert payload["progress"]["headline"] == progress.headline
    assert payload["progress"]["packets_done"] == 2


def test_the_estimate_is_absent_before_any_packet_completes(
    tmp_path: Path,
) -> None:
    """No completion, no pace: the estimate is never invented."""

    harness, clock = _clocked_harness(tmp_path)
    run_id = _run_at_planned(harness, AnalysisMode.FOCUSED)
    clock.advance(minutes=2)

    progress = harness.engine.status(run_id).progress
    assert progress is not None
    assert progress.packets_done == 0
    assert progress.elapsed_seconds == 2 * 60
    assert progress.estimated_remaining_seconds is None
    assert "at this pace" not in progress.headline


def test_an_old_saved_run_without_receipt_timestamps_still_reports_progress(
    tmp_path: Path,
) -> None:
    """The stored-format addition tolerates old runs (the B1 lesson).

    A run saved before receipts carried ``recorded_at`` must still load and
    report done/pending and elapsed — with the estimate absent rather than
    invented.  Simulated exactly as such a run exists on disk: the persisted
    work-queue, work-responses, and work-audit records carry no timestamp
    field at all.
    """

    harness, clock = _clocked_harness(tmp_path)
    run_id = _run_at_planned(harness, AnalysisMode.FOCUSED)
    _submit_first_packets(harness, run_id, count=2, clock=clock)

    checkpoint = harness.run_store.load(run_id)
    queue_payload = copy.deepcopy(
        harness.engine._find_kind(checkpoint, "work-queue")  # noqa: SLF001
    )
    for receipt in queue_payload["receipts"]:
        receipt.pop("recorded_at", None)
    responses_payload = copy.deepcopy(
        harness.engine._find_kind(checkpoint, "work-responses")  # noqa: SLF001
    )
    for record in responses_payload:
        record["receipt"].pop("recorded_at", None)
    audit_payload = copy.deepcopy(
        harness.engine._find_kind(checkpoint, "work-audit")  # noqa: SLF001
    )
    for receipt in audit_payload["receipts"]:
        receipt.pop("recorded_at", None)
    digests = (
        harness.engine._put("work-queue", queue_payload),  # noqa: SLF001
        harness.engine._put("work-responses", responses_payload),  # noqa: SLF001
        harness.engine._put("work-audit", audit_payload),  # noqa: SLF001
    )
    harness.run_store.save(
        checkpoint.model_copy(
            update={"artifact_digests": (*checkpoint.artifact_digests, *digests)}
        )
    )
    harness.reopen()
    _inject_clock(harness, clock)

    clock.advance(minutes=3)
    progress = harness.engine.status(run_id).progress
    assert progress is not None
    assert progress.packets_done == 2
    assert progress.packets_pending == QUEUE_SIZE - 2
    assert progress.elapsed_seconds == 5 * 60
    assert progress.estimated_remaining_seconds is None
    assert "at this pace" not in progress.headline
    # And such a run still resumes its work loop, not just its status.
    assert harness.engine.pending_work(run_id)


def test_everything_except_the_elapsed_clock_is_byte_stable(
    tmp_path: Path,
) -> None:
    """Two reads of the same stored state differ only in elapsed_seconds."""

    harness, clock = _clocked_harness(tmp_path)
    run_id = _run_at_planned(harness, AnalysisMode.FOCUSED)
    _submit_first_packets(harness, run_id, count=2, clock=clock)

    clock.advance(minutes=1)
    first = harness.engine.status(run_id).progress
    clock.advance(seconds=90)
    second = harness.engine.status(run_id).progress
    assert first is not None and second is not None

    first_payload = first.model_dump(mode="json")
    second_payload = second.model_dump(mode="json")
    assert first_payload.pop("elapsed_seconds") == 3 * 60
    assert second_payload.pop("elapsed_seconds") == 3 * 60 + 90
    first_bytes = json.dumps(first_payload, sort_keys=True)
    second_bytes = json.dumps(second_payload, sort_keys=True)
    assert first_bytes == second_bytes


def test_a_guided_run_reports_packet_progress_without_family_rows(
    tmp_path: Path,
) -> None:
    """Guided runs have no selection, so progress speaks in packets."""

    harness, clock = _clocked_harness(tmp_path)
    run_id = _run_at_planned(harness, AnalysisMode.GUIDED)
    clock.advance(minutes=1)

    progress = harness.engine.status(run_id).progress
    assert progress is not None
    assert progress.families == ()
    assert progress.packets_total == QUEUE_SIZE
    assert progress.headline == f"0 of {QUEUE_SIZE} specialist packets done"


def test_progress_is_absent_outside_the_work_window(tmp_path: Path) -> None:
    """Before planning and after completion, status carries no progress."""

    harness, clock = _clocked_harness(tmp_path)
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=AnalysisMode.FOCUSED)
    )
    run_id = prepared.run_id
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)
    assert harness.engine.status(run_id).progress is None

    harness.engine.focus(run_id, SELECTED)
    harness.run_to(run_id, DiagnosisStage.ANALYSIS_PLANNED)
    for packet in harness.engine.pending_work(run_id):
        harness.engine.submit_work(
            run_id, packet.packet_id, _verdicts_for_packet(packet)
        )
    for packet in harness.engine.pending_work(run_id):
        harness.engine.submit_work(run_id, packet.packet_id, ())
    harness.run_to(run_id, DiagnosisStage.ANALYSIS_COMPLETED)
    assert harness.engine.status(run_id).progress is None


def test_receipt_timestamps_are_engine_recorded_and_tolerant(
    tmp_path: Path,
) -> None:
    """Receipts carry the engine clock; old payloads without one still load."""

    harness, clock = _clocked_harness(tmp_path)
    run_id = _run_at_planned(harness, AnalysisMode.FOCUSED)
    _submit_first_packets(harness, run_id, count=1, clock=clock)

    checkpoint = harness.run_store.load(run_id)
    queue_payload = harness.engine._find_kind(checkpoint, "work-queue")  # noqa: SLF001
    (stored,) = queue_payload["receipts"]
    receipt = WorkReceipt.model_validate(stored)
    assert receipt.recorded_at == NOW + timedelta(minutes=1)

    legacy = dict(stored)
    legacy.pop("recorded_at", None)
    assert WorkReceipt.model_validate(legacy).recorded_at is None
    naive = dict(stored)
    naive["recorded_at"] = "2026-09-07T12:01:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        WorkReceipt.model_validate(naive)


def test_shipped_cli_status_renders_the_progress_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --json the CLI speaks one plain engine-composed line."""

    from capability_exchange.diagnosis import cli

    harness, clock = _clocked_harness(tmp_path)
    run_id = _run_at_planned(harness, AnalysisMode.FOCUSED)
    _submit_first_packets(harness, run_id, count=2, clock=clock)
    clock.advance(minutes=3)
    monkeypatch.setattr(cli, "build_engine", lambda: harness.engine)

    assert cli.diagnosis_main(["status", "--run", run_id, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["progress"]["packets_done"] == 2
    assert "about 7 minutes left at this pace" in payload["progress"]["headline"]

    assert cli.diagnosis_main(["status", "--run", run_id]) == 0
    rendered = capsys.readouterr().out
    assert f"{_BACKUP_TITLE} dive done — 1 finding" in rendered
    assert "about 7 minutes left at this pace" in rendered
