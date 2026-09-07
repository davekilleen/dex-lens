"""Pass-1 deterministic family map, derived before any specialist work.

Design: docs/superpowers/plans/2026-09-07-dex-lens-10x-experience.md, item 1.
Per the completion goal, every guarantee here was observed failing first:
either on the unchanged tree (no FAMILY_MAPPED stage, no map surface) or with
the specific guard removed (the compare-time stored-map refusal, and the
old-run tolerance whose absence wedges pre-stage saved runs).

Per RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT the stored family-map artifact is an
audit record only: every read surface re-derives the map from the stored
verified inputs, and comparison refuses a stored map that disagrees.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.diagnosis.test_real_comparer_guided_run import RealComparerHarness
from tests.diagnosis.test_significant_family_assessment import (
    _catalogue,
    _family,
    _fingerprint,
    _observation,
)

from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS
from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.diagnosis.orchestrator import PrepareDiagnosisRequest
from capability_exchange.diagnosis.run import (
    DiagnosisStage,
    DiagnosisStateError,
    RequiredStep,
)
from capability_exchange.diagnosis.work import AnalysisMode


def _wow_catalogue():
    families = tuple(
        _family(
            family_id,
            profile="filesystem",
            members=["workflow-skill"],
            components=[
                {"component_type": "capability", "capability_id": "workflow-skill"}
            ],
        )
        for family_id in WOW_EXPECTATIONS
    )
    return _catalogue(*families)


def _wow_fingerprint():
    return _fingerprint(_observation(ObservationKind.SKILL, "workflow-skill"))


def _harness(tmp_path: Path) -> RealComparerHarness:
    return RealComparerHarness(
        tmp_path,
        catalogue=_wow_catalogue(),
        fingerprint=_wow_fingerprint(),
    )


def _prepare(harness: RealComparerHarness, mode: AnalysisMode) -> str:
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=mode)
    )
    return prepared.run_id


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def test_zero_receipt_run_exposes_all_fourteen_family_rows(tmp_path: Path) -> None:
    """The whole 14-row map is readable before one specialist packet exists.

    Observed failing on the unchanged tree: assessments existed only inside
    ``compare()``, unreachable before analysis completed, and the stage
    ``FAMILY_MAPPED`` did not exist.
    """

    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.GUIDED)
    view = harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)
    assert view.stage is DiagnosisStage.FAMILY_MAPPED
    # Zero specialist receipts: analysis has not even been planned yet, so no
    # work packet — and therefore no receipt — can exist for this run.
    with pytest.raises(DiagnosisStateError, match="analysis planning"):
        harness.engine.pending_work(run_id)

    status_map = harness.engine.status(run_id).family_map
    assert status_map is not None
    assert tuple(row.family_id for row in status_map.rows) == WOW_EXPECTATIONS
    assert all(row.evidence_references for row in status_map.rows)
    assert all(row.reason for row in status_map.rows)
    assert all(row.title for row in status_map.rows)

    direct = harness.engine.family_map(run_id)
    assert direct == status_map


def test_family_map_is_refused_before_catalogue_verification(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.GUIDED)
    harness.run_to(run_id, DiagnosisStage.CAPTURED)

    with pytest.raises(DiagnosisStateError, match="family map") as failure:
        harness.engine.family_map(run_id)
    assert failure.value.required_step is RequiredStep.MAP_FAMILIES
    assert harness.engine.status(run_id).family_map is None


def test_two_derivations_of_the_same_run_are_byte_identical(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.INVENTORY_ONLY)
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)

    first = harness.engine.family_map(run_id)
    second = harness.engine.family_map(run_id)

    assert first == second
    assert _canonical(first.model_dump(mode="json")) == _canonical(
        second.model_dump(mode="json")
    )


def test_map_rows_equal_the_closed_ledgers_expectation_rows(tmp_path: Path) -> None:
    """One derivation, two call sites: the map and compare() cannot drift."""

    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.INVENTORY_ONLY)
    harness.run_to(run_id, DiagnosisStage.CLOSED)

    ledger = harness.engine.result(run_id).ledger
    family_map = harness.engine.family_map(run_id)

    assert [
        (row.family_id, row.state, row.evidence_references, row.reason)
        for row in family_map.rows
    ] == [
        (item.family_id, item.state, tuple(sorted(item.evidence_ids)), item.reason)
        for item in ledger.expectations
    ]


def test_reads_ignore_a_forged_stored_map_and_compare_refuses_it(
    tmp_path: Path,
) -> None:
    """The stored family-map artifact is never trusted over re-derivation.

    Mirrors RISK-GUIDED-COMPARE-TRUSTS-ARTIFACT: a forged stored map (written
    through the engine's own content-addressed store, so its digest is valid)
    must not reach any read surface, and comparison must refuse the run
    rather than closing over a map the inputs do not support.  The refusal was
    observed accepted (run closed normally) with the compare-time guard
    removed.
    """

    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.INVENTORY_ONLY)
    harness.run_to(run_id, DiagnosisStage.JOBS_CONFIRMED)

    forged = harness.engine.family_map(run_id).model_dump(mode="json")
    forged["rows"] = forged["rows"][:1]
    checkpoint = harness.run_store.load(run_id)
    digest = harness.engine._put("family-map", forged)  # noqa: SLF001
    harness.run_store.save(
        checkpoint.model_copy(
            update={"artifact_digests": (*checkpoint.artifact_digests, digest)}
        )
    )

    # Every read surface re-derives: the forgery never reaches a reader.
    assert len(harness.engine.family_map(run_id).rows) == 14
    status_map = harness.engine.status(run_id).family_map
    assert status_map is not None and len(status_map.rows) == 14

    # And comparison refuses the run whose stored audit record disagrees.
    with pytest.raises(DiagnosisStateError, match="family map"):
        harness.engine.advance(run_id)


def test_shipped_cli_map_command_prints_the_map_from_a_real_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`dex-lens diagnosis map --run <id> --json` end to end over the real engine."""

    from capability_exchange.diagnosis import cli

    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.GUIDED)
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)
    monkeypatch.setattr(cli, "build_engine", lambda: harness.engine)

    assert cli.diagnosis_main(["map", "--run", run_id, "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [row["family_id"] for row in payload["rows"]] == list(WOW_EXPECTATIONS)
    assert all(row["evidence_references"] for row in payload["rows"])

    assert cli.diagnosis_main(["map", "--run", run_id]) == 0
    rendered = capsys.readouterr().out
    for family_id in WOW_EXPECTATIONS:
        assert family_id in rendered


def test_a_run_saved_before_the_stage_existed_still_completes(tmp_path: Path) -> None:
    """Old-stage-sequence saved runs must not wedge on upgrade.

    A run persisted before FAMILY_MAPPED existed holds no family-map artifact.
    Simulated here by stripping the artifact from the checkpoint; observed
    wedging (DiagnosisStateError at comparison, no exit) against the naive
    implementation that required the artifact at compare time.
    """

    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.INVENTORY_ONLY)
    harness.run_to(run_id, DiagnosisStage.JOBS_CONFIRMED)

    checkpoint = harness.run_store.load(run_id)
    kept = tuple(
        digest
        for digest in checkpoint.artifact_digests
        if harness.engine._get(digest).get("kind") != "family-map"  # noqa: SLF001
    )
    assert kept != checkpoint.artifact_digests  # the artifact existed and is gone now
    harness.run_store.save(checkpoint.model_copy(update={"artifact_digests": kept}))
    harness.reopen()

    closed = harness.run_to(run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED
    # The map surface still answers, re-derived from the stored verified inputs.
    assert len(harness.engine.family_map(run_id).rows) == 14
