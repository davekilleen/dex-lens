"""Derived ledger summaries and exact report fact-block reconciliation."""

from __future__ import annotations

import re
from collections import Counter

import pytest
from tests.diagnosis.test_receipts import RESPONSE_DIGEST, SESSION, decision_receipt
from tests.diagnosis.test_run import NOW, RUN_ID
from tests.evals.real_session_fixture import (
    EXPECTED_COUNTS,
    real_session_fingerprint,
    real_session_ledger,
    real_session_report,
)
from tests.evals.test_real_session_replay import expected_contract

from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    HumanCapability,
)
from capability_exchange.diagnosis.ranking import (
    RecommendationCandidate,
    RecommendationFactors,
    rank_recommendations,
)
from capability_exchange.diagnosis.receipts import (
    DecisionState,
    DestinationClass,
    RecommendationDecision,
    ShareReceipt,
    ShareState,
)
from capability_exchange.diagnosis.report import (
    LedgerSummary,
    ReportModel,
    canonical_fact_block,
    canonical_ledger_digest,
)
from capability_exchange.diagnosis.run import ENGINE_VERSION, INPUT_SCHEMA_VERSION, RunIdentity
from capability_exchange.evaluation.diagnosis import evaluate_diagnosis

FALSE_COVERAGE_CLAIM = "93 capabilities are already covered"


def ranked_ledger() -> ComparisonLedger:
    entries = tuple(
        CatalogueDisposition(
            catalogue_id=f"recommendation-{index}",
            capability_id=f"capability-{index}",
            disposition=Disposition.WORTH_BORROWING,
            evidence_references=(f"evidence:{index}",),
            method_compared=True,
            reason=f"Reason {index}.",
        )
        for index in range(2)
    )
    candidates = tuple(
        RecommendationCandidate(
            catalogue_id=entry.catalogue_id,
            capability_id=entry.capability_id,
            factors=RecommendationFactors(
                reliability_risk=2 - index,
                job_relevance=2,
                workflow_leverage=2,
                evidence_strength=2,
                adoption_effort=1,
            ),
            evidence_ids=entry.evidence_references,
            reason=entry.reason,
        )
        for index, entry in enumerate(entries)
    )
    return ComparisonLedger(
        catalogue_version=1,
        catalogue_sha256="a" * 64,
        capabilities=tuple(
            HumanCapability(
                capability_id=f"capability-{index}",
                title=f"Capability {index}",
                job_ids=(),
                catalogue_ids=(f"recommendation-{index}",),
                person_observation_ids=(),
            )
            for index in range(2)
        ),
        entries=entries,
        ranked_recommendations=rank_recommendations(candidates),
        reciprocal_answer="No transferable method cleared the evidence bar.",
    )


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


@pytest.mark.parametrize("change", ("rank", "factors", "evidence_ids", "reason"))
def test_canonical_ledger_digest_binds_ranked_recommendation_details(change: str) -> None:
    ledger = ranked_ledger()
    digest = canonical_ledger_digest(ledger)
    first = ledger.ranked_recommendations[0]
    if change == "rank":
        updated = first.model_copy(update={"rank": 2})
    elif change == "factors":
        updated = first.model_copy(
            update={
                "factors": RecommendationFactors(
                    reliability_risk=1,
                    job_relevance=2,
                    workflow_leverage=2,
                    evidence_strength=2,
                    adoption_effort=1,
                )
            }
        )
    elif change == "evidence_ids":
        updated = first.model_copy(update={"evidence_ids": ("evidence:changed",)})
    else:
        updated = first.model_copy(update={"reason": "Changed ranked reason."})
    changed = ledger.model_copy()
    # Simulate bytes tampered after validation: the digest must still bind the
    # ranked payload even when a hostile caller bypasses model validation.
    object.__setattr__(
        changed,
        "ranked_recommendations",
        (updated, *ledger.ranked_recommendations[1:]),
    )

    assert canonical_ledger_digest(changed) != digest


def test_canonical_fact_block_is_exact_ledger_projection() -> None:
    ledger = real_session_ledger()
    block = canonical_fact_block(ledger)
    summary = LedgerSummary.from_ledger(ledger)

    assert block == (
        f"- Ledger digest: {canonical_ledger_digest(ledger)}\n"
        + summary.canonical_markdown()
        + "- Local observations: 0 captured; 0 mapped; 0 remain not assessed.\n"
        + "- Signed MCP inventory: 0 declared tools across 0 servers; 0 complete "
        + "inventories; 0 sampled inventories.\n"
        + "- Significant-family components: 0 exact matches; 0 remain Unknown.\n"
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
    assert report.share_state is ShareState.NOT_OFFERED
    assert report.share_receipt is None
    assert report.decisions == ()
    with pytest.raises(TypeError, match="from_result"):
        ReportModel.model_construct(
            run_identity=run_identity(),
            ledger_summary=LedgerSummary.from_ledger(ledger),
            ledger_sha256=canonical_ledger_digest(ledger),
        )


def _after_coverage(markdown: str) -> str:
    marker = "## What you decided"
    return markdown[markdown.index(marker) :]


def _report(
    *,
    decisions: tuple[RecommendationDecision, ...] = (),
    share_state: ShareState = ShareState.NOT_OFFERED,
    share_receipt: ShareReceipt | None = None,
) -> tuple[object, ReportModel]:
    ledger = real_session_ledger()
    report = ReportModel.from_result(
        run_identity=run_identity(),
        ledger=ledger,
        ledger_sha256=canonical_ledger_digest(ledger),
        findings=(),
        limits=("Every identity in this replay is invented.",),
        decisions=decisions,
        share_state=share_state,
        share_receipt=share_receipt,
    )
    return ledger, report


def test_report_has_no_pre_rendered_decision_or_share_prose_field() -> None:
    assert not any("prose" in name for name in ReportModel.model_fields)


def test_report_derives_decisions_only_from_receipts() -> None:
    ledger, report = _report(
        decisions=(
            RecommendationDecision(
                catalogue_id="invented-capability-001",
                state=DecisionState.OFFERED,
            ),
            RecommendationDecision(
                catalogue_id="invented-capability-002",
                state=DecisionState.CHOSEN,
                receipt=decision_receipt(catalogue_id="invented-capability-002"),
            ),
            RecommendationDecision(
                catalogue_id="invented-capability-003",
                state=DecisionState.COMPLETED,
                receipt=decision_receipt(
                    catalogue_id="invented-capability-003",
                    state=DecisionState.COMPLETED,
                ),
            ),
        )
    )

    rendered = report.render_markdown(ledger)
    decided = _after_coverage(rendered)
    assert canonical_fact_block(ledger) in rendered
    assert rendered.index("## Coverage and limits") < rendered.index("## What you decided")
    assert rendered.index(canonical_fact_block(ledger)) < rendered.index("## What you decided")
    assert "- invented-capability-001 — offered" in decided
    assert "- invented-capability-002 — taken" in decided
    assert "- invented-capability-003 — taken" in decided
    offered_line = next(
        line for line in decided.splitlines() if "invented-capability-001" in line
    )
    assert "taken" not in offered_line


def test_empty_decisions_use_the_honest_empty_answer() -> None:
    ledger, report = _report()
    decided = _after_coverage(report.render_markdown(ledger))

    assert "No decisions were on the table this time." in decided
    assert "taken" not in decided


def test_preview_share_never_renders_as_shared() -> None:
    preview = ShareReceipt.preview(
        disclosure_sha256="a" * 64,
        created_at=NOW,
        run_id=RUN_ID,
        session_receipt_id=SESSION,
    )
    ledger, report = _report(share_state=ShareState.PREVIEWED, share_receipt=preview)
    close = _after_coverage(report.render_markdown(ledger))

    assert report.share_state is ShareState.PREVIEWED
    assert not preview.was_sent
    assert re.search(r"\bshared\b", close, flags=re.IGNORECASE) is None
    assert "preview" in close.lower()
    assert "nothing was sent" in close.lower()


def test_sent_share_renders_only_from_a_confirmed_receipt() -> None:
    sent = ShareReceipt.sent(
        disclosure_sha256="a" * 64,
        created_at=NOW,
        destination_class=DestinationClass.CONTRIBUTION_INTAKE,
        response_receipt_digest=RESPONSE_DIGEST,
        run_id=RUN_ID,
        session_receipt_id=SESSION,
    )
    ledger, report = _report(share_state=ShareState.SENT, share_receipt=sent)
    close = _after_coverage(report.render_markdown(ledger))

    assert sent.was_sent
    assert re.search(r"\bshared\b", close, flags=re.IGNORECASE)
    assert "contribution-intake" in close
    assert "a" * 64 in close
    assert RESPONSE_DIGEST in close


def test_sent_share_state_requires_a_sent_receipt() -> None:
    preview = ShareReceipt.preview(
        disclosure_sha256="a" * 64,
        created_at=NOW,
        run_id=RUN_ID,
        session_receipt_id=SESSION,
    )
    with pytest.raises(ValueError, match="share receipt"):
        _report(share_state=ShareState.SENT)
    with pytest.raises(ValueError, match="share"):
        _report(share_state=ShareState.SENT, share_receipt=preview)


def test_close_is_generated_from_the_report_model() -> None:
    ledger, report = _report()
    rendered = report.render_markdown(ledger)
    close = _after_coverage(rendered)

    assert "No grounded strength cleared the evidence bar." in close
    assert "See 2 evidence-reviewed patterns above." in close
    assert (
        "No single first move has stronger evidence than the other options above."
        in close
    )
    assert "will be saved before the run closes" in close.lower()
    assert RUN_ID in close
    assert "Sharing was not offered." in close
    assert "Future-watch is a separate choice from sharing." in close
    assert "taken" not in close
    assert re.search(r"\bshared\b", close, flags=re.IGNORECASE) is None
