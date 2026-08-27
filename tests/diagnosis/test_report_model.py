"""Derived ledger summaries and exact report fact-block reconciliation."""

from __future__ import annotations

from collections import Counter

import pytest
from tests.diagnosis.test_run import NOW, RUN_ID
from tests.evals.real_session_fixture import (
    EXPECTED_COUNTS,
    real_session_fingerprint,
    real_session_ledger,
    real_session_report,
)
from tests.evals.test_real_session_replay import expected_contract

from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.report import (
    LedgerSummary,
    ReportModel,
    canonical_fact_block,
    canonical_ledger_digest,
)
from capability_exchange.diagnosis.run import ENGINE_VERSION, INPUT_SCHEMA_VERSION, RunIdentity
from capability_exchange.evaluation.diagnosis import evaluate_diagnosis

FALSE_COVERAGE_CLAIM = "93 capabilities are already covered"


def run_identity() -> RunIdentity:
    return RunIdentity(
        run_id=RUN_ID,
        engine_version=ENGINE_VERSION,
        input_schema_version=INPUT_SCHEMA_VERSION,
        created_at=NOW,
    )


def test_summary_is_derived_from_entries() -> None:
    ledger = real_session_ledger()
    summary = LedgerSummary.from_ledger(ledger)

    assert summary.total == 115
    assert summary.unknown == 80
    assert summary.assessed == 35
    assert summary.by_disposition[Disposition.SHARED] == 8
    assert summary.by_disposition == {
        disposition: EXPECTED_COUNTS[disposition] for disposition in Disposition
    }
    assert Counter(item.disposition for item in ledger.entries) == EXPECTED_COUNTS


def test_summary_cannot_be_constructed_from_independent_numbers() -> None:
    counts = {disposition: EXPECTED_COUNTS[disposition] for disposition in Disposition}
    ledger = real_session_ledger()
    summary = LedgerSummary.from_ledger(ledger)

    assert ledger.derived_summary() == summary

    with pytest.raises(TypeError, match="from_ledger"):
        LedgerSummary(
            total=115,
            by_disposition=counts,
            assessed=35,
            unknown=80,
        )
    with pytest.raises(TypeError, match="from_ledger"):
        LedgerSummary.model_construct(
            total=115,
            by_disposition=counts,
            assessed=35,
            unknown=80,
        )
    with pytest.raises(TypeError, match="from_ledger"):
        summary.copy()
    with pytest.raises(TypeError, match="from_ledger"):
        summary.model_copy(update={"total": 1})


def test_canonical_ledger_digest_is_stable_and_content_bound() -> None:
    ledger = real_session_ledger()
    digest = canonical_ledger_digest(ledger)

    assert digest == canonical_ledger_digest(real_session_ledger())
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64

    first = ledger.entries[0]
    drifted = ledger.model_copy(
        update={
            "entries": (
                first.model_copy(
                    update={
                        "disposition": Disposition.NOT_RELEVANT,
                        "reason": "Invented digest-drift reason.",
                    }
                ),
                *ledger.entries[1:],
            )
        }
    )

    assert canonical_ledger_digest(drifted) != digest


def test_canonical_fact_block_is_exact_ledger_projection() -> None:
    ledger = real_session_ledger()
    block = canonical_fact_block(ledger)
    summary = LedgerSummary.from_ledger(ledger)

    assert block == (
        f"- Ledger digest: {canonical_ledger_digest(ledger)}\n"
        + summary.canonical_markdown()
    )
    assert block.splitlines()[1] == (
        "- Catalogue accounting: 115 entries; 35 assessed; 80 remain Unknown."
    )
    assert block.splitlines()[2] == (
        "- Dispositions: "
        + ", ".join(f"{item.value}={summary.by_disposition[item]}" for item in Disposition)
        + "."
    )


def test_report_without_canonical_fact_block_fails_reconciliation() -> None:
    ledger = real_session_ledger()
    result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=real_session_report().replace(canonical_fact_block(ledger), "", 1),
        expected=expected_contract().evaluator_mapping(),
    )

    assert not result.passed
    assert any("ledger-derived facts" in item for item in result.report_errors)


def test_altered_fact_block_fails_reconciliation() -> None:
    ledger = real_session_ledger()
    altered = real_session_report().replace("115 entries", "114 entries", 1)
    expected = expected_contract().without_literal_blacklist()

    result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=altered,
        expected=expected.evaluator_mapping(),
    )

    assert not result.passed
    assert any("ledger-derived facts" in item for item in result.report_errors)


def test_conflicting_coverage_sentence_fails_even_with_exact_fact_block() -> None:
    ledger = real_session_ledger()
    contradictory = real_session_report().replace(
        "80 capabilities remain Unknown",
        FALSE_COVERAGE_CLAIM,
    )
    expected = expected_contract().without_literal_blacklist()

    result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=contradictory,
        expected=expected.evaluator_mapping(),
    )

    assert not result.passed
    assert any("ledger-derived facts" in item for item in result.report_errors)


def test_report_model_rejects_unrelated_ledger_digest() -> None:
    with pytest.raises(ValueError, match="exact comparison ledger"):
        ReportModel.from_result(
            run_identity=run_identity(),
            ledger=real_session_ledger(),
            ledger_sha256="0" * 64,
            findings=(),
        )


def test_report_model_renders_the_canonical_fact_block() -> None:
    ledger = real_session_ledger()
    report = ReportModel.from_result(
        run_identity=run_identity(),
        ledger=ledger,
        ledger_sha256=canonical_ledger_digest(ledger),
        findings=(),
        limits=("Every identity in this replay is invented.",),
    )

    rendered = report.render_markdown(ledger)
    assert canonical_fact_block(ledger) in rendered
    assert report.ledger_summary.unknown == 80
    with pytest.raises(TypeError, match="from_result"):
        ReportModel.model_construct(
            run_identity=run_identity(),
            ledger_summary=LedgerSummary.from_ledger(ledger),
            ledger_sha256=canonical_ledger_digest(ledger),
        )
