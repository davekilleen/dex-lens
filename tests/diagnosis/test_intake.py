"""The intake questions: asked first, answered once, honest forever.

Goal: docs/superpowers/plans/2026-09-08-dex-lens-intake-goal.md, G1-G4.
Every test here was observed to fail on the tree without the intake stage.
Fixtures are the stale-install vault and its no-Dex variant — never minimal
dioramas — per the goal's fixture rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.diagnosis.test_job_axis import _eight_job_catalogue
from tests.diagnosis.test_orchestrator import _replace_stored_artifact
from tests.diagnosis.test_real_comparer_guided_run import RealComparerHarness
from tests.diagnosis.test_stale_install_coverage import (
    PRE_INSTALL_SINCE_RELEASE,
    _catalogue_with_member_since,
)
from tests.evals.stale_install_fixture import write_stale_install

from capability_exchange.diagnosis.orchestrator import PrepareDiagnosisRequest
from capability_exchange.diagnosis.run import (
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.work import AnalysisMode

#: A complete, ordinary set of answers for someone who has Dex.
DEX_ANSWERS = {
    "dex-installed": "yes",
    "customisation": "quite-a-bit",
    "first-installed": "at-launch",
    "last-update": "never",
}

#: A complete set for someone who has never installed Dex.
NO_DEX_ANSWERS = {
    "dex-installed": "no",
    "from-open-source": "yes",
    "project-link": "https://example.invalid/an-invented-system",
    "customisation": "barely-touched",
}

#: The person who does not know. Every question accepts this.
NOT_SURE_ANSWERS = {
    "dex-installed": "not-sure",
    "customisation": "not-sure",
    "first-installed": "not-sure",
    "last-update": "not-sure",
}


def _harness(tmp_path: Path, *, dex_present: bool = True) -> RealComparerHarness:
    fingerprint = write_stale_install(tmp_path / "vault", dex_present=dex_present)
    return RealComparerHarness(
        tmp_path,
        catalogue=_catalogue_with_member_since(PRE_INSTALL_SINCE_RELEASE),
        fingerprint=fingerprint,
    )


def _prepared(harness: RealComparerHarness, mode: AnalysisMode) -> str:
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=mode)
    )
    return prepared.run_id


def _at_scope_approved(harness: RealComparerHarness, mode: AnalysisMode) -> str:
    run_id = _prepared(harness, mode)
    harness.approve(run_id)
    view = harness.engine.status(run_id)
    if view.stage is DiagnosisStage.CREATED:
        harness.engine.advance(run_id)
    return run_id


# --- G1: the stage cannot be skipped -----------------------------------------


def test_advancing_without_answers_is_refused_and_names_the_first_question(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    with pytest.raises(DiagnosisStateError, match="dex-installed"):
        harness.engine.advance(run_id)


def test_a_partial_answer_set_is_refused_naming_the_missing_question(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    partial = {key: value for key, value in DEX_ANSWERS.items() if key != "last-update"}
    with pytest.raises(DiagnosisStateError, match="last-update"):
        harness.engine.intake(run_id, partial)


def test_recorded_answers_open_the_gate(tmp_path: Path) -> None:
    """The positive control: with answers recorded, the run moves on."""

    harness = _harness(tmp_path)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    view = harness.engine.intake(run_id, DEX_ANSWERS)
    assert view.stage is DiagnosisStage.INTAKE_RECORDED
    assert harness.engine.advance(run_id).stage is DiagnosisStage.CAPTURED


# --- G2: "not sure" always works, end to end ----------------------------------


def test_a_run_answered_entirely_not_sure_reaches_closed(tmp_path: Path) -> None:
    fingerprint = write_stale_install(tmp_path / "vault")
    harness = RealComparerHarness(
        tmp_path, catalogue=_eight_job_catalogue(), fingerprint=fingerprint
    )
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    harness.engine.intake(run_id, NOT_SURE_ANSWERS)
    view = harness.engine.status(run_id)
    while view.stage is not DiagnosisStage.CLOSED:
        view = harness.engine.advance(run_id)

    assert view.stage is DiagnosisStage.CLOSED


# --- G3: two branches, closed options, bounded link ---------------------------


def test_an_answer_outside_the_options_is_refused_typed(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    answers = {**DEX_ANSWERS, "customisation": "sort-of"}
    with pytest.raises(DiagnosisStateError, match="customisation"):
        harness.engine.intake(run_id, answers)


def test_an_unknown_question_id_is_refused_typed(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    answers = {**DEX_ANSWERS, "favourite-colour": "green"}
    with pytest.raises(DiagnosisStateError, match="favourite-colour"):
        harness.engine.intake(run_id, answers)


def test_a_dex_branch_question_on_a_no_dex_run_is_refused(tmp_path: Path) -> None:
    harness = _harness(tmp_path, dex_present=False)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    answers = {**NO_DEX_ANSWERS, "last-update": "never"}
    with pytest.raises(DiagnosisStateError, match="last-update"):
        harness.engine.intake(run_id, answers)


def test_the_no_dex_branch_accepts_a_complete_answer_set(tmp_path: Path) -> None:
    harness = _harness(tmp_path, dex_present=False)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    view = harness.engine.intake(run_id, NO_DEX_ANSWERS)
    assert view.stage is DiagnosisStage.INTAKE_RECORDED


def test_a_non_https_or_oversized_project_link_is_refused(tmp_path: Path) -> None:
    harness = _harness(tmp_path, dex_present=False)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    with pytest.raises(DiagnosisStateError, match="project-link"):
        harness.engine.intake(
            run_id, {**NO_DEX_ANSWERS, "project-link": "http://example.invalid/x"}
        )
    with pytest.raises(DiagnosisStateError, match="project-link"):
        harness.engine.intake(
            run_id,
            {**NO_DEX_ANSWERS, "project-link": "https://example.invalid/" + "a" * 300},
        )


def test_a_project_link_without_an_open_source_yes_is_refused(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, dex_present=False)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    answers = {
        **NO_DEX_ANSWERS,
        "from-open-source": "no-built-it-myself",
    }
    with pytest.raises(DiagnosisStateError, match="project-link"):
        harness.engine.intake(run_id, answers)


# --- G4: stamped once, tamper-refused, deterministic --------------------------


def test_an_exact_replay_is_idempotent_and_a_different_set_is_refused(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    first = harness.engine.intake(run_id, DEX_ANSWERS)
    replay = harness.engine.intake(run_id, DEX_ANSWERS)
    assert replay.intake == first.intake

    with pytest.raises(DiagnosisStateError, match="already recorded"):
        harness.engine.intake(run_id, {**DEX_ANSWERS, "last-update": "last-week"})


def test_identical_answers_produce_a_byte_identical_receipt(tmp_path: Path) -> None:
    """No clock, no ordering wobble: the receipt is a pure function of answers.

    Two runs differ only in the run identity they are bound to; nothing else —
    in particular no timestamp — may make otherwise-identical receipts differ.
    """

    harness = _harness(tmp_path)
    first_run = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)
    second_run = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    first = harness.engine.intake(first_run, DEX_ANSWERS).intake
    again = harness.engine.status(first_run).intake
    assert first is not None and again is not None
    assert first.model_dump(mode="json") == again.model_dump(mode="json")

    second = harness.engine.intake(second_run, DEX_ANSWERS).intake
    assert second is not None
    first_payload = first.model_dump(mode="json")
    second_payload = second.model_dump(mode="json")
    differing = {
        key
        for key in first_payload
        if first_payload[key] != second_payload[key]
    }
    assert differing <= {"run_id", "intake_digest"}, (
        "identical answers may differ only in the run binding — a timestamp or "
        "any other wobble breaks byte-identity"
    )


def test_a_tampered_stored_intake_receipt_is_refused_on_reload(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)
    view = harness.engine.intake(run_id, DEX_ANSWERS)
    assert view.intake is not None

    tampered = view.intake.model_dump(mode="json")
    for answer in tampered["answers"]:
        if answer["question_id"] == "customisation":
            answer["answer"] = "unrecognisable"
    _replace_stored_artifact(harness, run_id, "intake-receipt", tampered)

    # Status keeps reporting proved progress without the tampered record...
    assert harness.engine.status(run_id).intake is None
    # ...and the consuming surface fails closed before anything is read.
    with pytest.raises(DiagnosisStateError, match="intake answers"):
        harness.engine.advance(run_id)
