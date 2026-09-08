"""What the person told us: framed as theirs, never dressed as evidence.

Goal: docs/superpowers/plans/2026-09-08-dex-lens-intake-goal.md, G5-G7.
Every test here was observed to fail on the tree without the report wiring.
Fixtures are the stale-install vault and its no-Dex variant.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.diagnosis.test_intake import (
    DEX_ANSWERS,
    NO_DEX_ANSWERS,
    _at_scope_approved,
)
from tests.diagnosis.test_job_axis import _eight_job_catalogue
from tests.diagnosis.test_real_comparer_guided_run import RealComparerHarness
from tests.evals.stale_install_fixture import write_stale_install

from capability_exchange.diagnosis.run import (
    INTAKE_QUESTION_OPTIONS,
    DiagnosisStage,
    DiagnosisStateError,
)
from capability_exchange.diagnosis.work import AnalysisMode

#: Insider vocabulary no rendered sentence a person reads may contain.
#: "non-lineage" is covered by "lineage"; each word is matched at a word
#: start so "loan" also catches "loans" and "loaned".
BANNED_WORDS = ("loan", "lineage", "delta", "fingerprint", "ledger", "axis")


def _banned_hits(text: str) -> list[str]:
    visible = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    hits = []
    for word in BANNED_WORDS:
        for line in visible.splitlines():
            if re.search(rf"\b{word}", line, re.IGNORECASE):
                hits.append(f"{word}: {line.strip()[:80]}")
    return hits


def _closed_report(
    tmp_path: Path, answers: dict[str, str], *, dex_present: bool = True
) -> str:
    fingerprint = write_stale_install(tmp_path / "vault", dex_present=dex_present)
    harness = RealComparerHarness(
        tmp_path, catalogue=_eight_job_catalogue(), fingerprint=fingerprint
    )
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)
    harness.engine.intake(run_id, answers)
    view = harness.engine.status(run_id)
    while view.stage is not DiagnosisStage.CLOSED:
        view = harness.engine.advance(run_id)
    return harness.engine.result(run_id).render_markdown()


# --- G5: attested framing, verified counts -------------------------------------


def test_the_report_says_what_the_person_told_us_in_their_words(
    tmp_path: Path,
) -> None:
    rendered = _closed_report(tmp_path, DEX_ANSWERS)

    assert "## What you told me" in rendered
    assert "You told me" in rendered


def test_intake_answers_cannot_move_a_verified_count(tmp_path: Path) -> None:
    """The release counts belong to the signed record, not to testimony."""

    honest = _closed_report(tmp_path, DEX_ANSWERS)
    embellished = _closed_report(
        tmp_path.joinpath("second"),
        {**DEX_ANSWERS, "first-installed": "last-week", "last-update": "last-week"},
    )

    def counts(markdown: str) -> list[str]:
        return re.findall(r"at least \d+ releases? behind", markdown)

    assert counts(honest) == counts(embellished)


# --- G6: disagreement is a finding, not a tiebreak ------------------------------


def test_saying_no_dex_while_dex_s_release_record_is_present_renders_both_facts(
    tmp_path: Path,
) -> None:
    rendered = _closed_report(tmp_path, NO_DEX_ANSWERS, dex_present=True)

    assert "you told me you don't have dex" in rendered.lower()
    assert "release record" in rendered.lower()


def test_saying_yes_dex_while_no_release_record_exists_renders_both_facts(
    tmp_path: Path,
) -> None:
    rendered = _closed_report(tmp_path, DEX_ANSWERS, dex_present=False)

    assert "you told me you have dex" in rendered.lower()
    assert "couldn't find" in rendered.lower() or "could not find" in rendered.lower()


# --- G7: plain words in everything a person reads -------------------------------


def test_the_rendered_report_carries_no_insider_vocabulary(tmp_path: Path) -> None:
    for index, (answers, dex_present) in enumerate(
        ((DEX_ANSWERS, True), (NO_DEX_ANSWERS, False))
    ):
        rendered = _closed_report(
            tmp_path.joinpath(str(index)), answers, dex_present=dex_present
        )
        assert _banned_hits(rendered) == []


def test_the_intake_questions_and_options_carry_no_insider_vocabulary() -> None:
    for question_id, options in INTAKE_QUESTION_OPTIONS.items():
        assert _banned_hits(question_id) == []
        for option in options:
            assert _banned_hits(option) == []


def test_intake_refusals_carry_no_insider_vocabulary(tmp_path: Path) -> None:
    fingerprint = write_stale_install(tmp_path / "vault")
    harness = RealComparerHarness(
        tmp_path, catalogue=_eight_job_catalogue(), fingerprint=fingerprint
    )
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)

    refusals: list[str] = []
    for provoke in (
        lambda: harness.engine.advance(run_id),
        lambda: harness.engine.intake(run_id, {"dex-installed": "sort-of"}),
        lambda: harness.engine.intake(run_id, {"favourite-colour": "green"}),
        lambda: harness.engine.intake(
            run_id, {**DEX_ANSWERS, "project-link": "https://example.invalid/x"}
        ),
    ):
        with pytest.raises(DiagnosisStateError) as caught:
            provoke()
        refusals.append(str(caught.value))

    for refusal in refusals:
        assert _banned_hits(refusal) == [], refusal
