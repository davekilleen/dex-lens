"""Every verified Dex catalogue entry receives one explicit disposition."""

from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import ValidationError
from tests.catalogue.test_bridge import _catalogue

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

CATALOGUE_SHA = "a" * 64


def _human(*catalogue_ids: str) -> HumanCapability:
    return HumanCapability(
        capability_id="system-health",
        title="System health",
        job_ids=("check-system-health",),
        catalogue_ids=catalogue_ids,
        person_observation_ids=("health-check:system-doctor",),
    )


def _disposition(
    catalogue_id: str,
    disposition: Disposition = Disposition.NOT_ASSESSED,
    *,
    evidence: tuple[str, ...] = (),
    method_compared: bool = False,
) -> CatalogueDisposition:
    return CatalogueDisposition(
        catalogue_id=catalogue_id,
        disposition=disposition,
        capability_id="system-health",
        evidence_references=evidence,
        method_compared=method_compared,
        reason="Checked against the local evidence available for this job.",
    )


def test_ledger_requires_one_disposition_per_catalogue_entry() -> None:
    catalogue = _catalogue()
    first = catalogue.capabilities[0].capability_id

    with pytest.raises(ValidationError, match="catalogue identity set"):
        ComparisonLedger.for_catalogue(
            catalogue,
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=(_human(first),),
            entries=(_disposition(first),),
        )


def test_ledger_refuses_more_than_ten_recommendations() -> None:
    entries = tuple(
        _disposition(
            f"catalogue-item-{index}",
            Disposition.WORTH_BORROWING,
            evidence=(f"path-token:item-{index}",),
            method_compared=True,
        )
        for index in range(11)
    )

    with pytest.raises(ValidationError, match="at most 10"):
        ComparisonLedger(
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=(_human(*(item.catalogue_id for item in entries)),),
            entries=entries,
            reciprocal_answer="No transferable method cleared the evidence bar.",
        )


def test_ledger_preserves_the_exact_ranked_recommendation_tuple() -> None:
    entry = _disposition(
        "catalogue-item-0",
        Disposition.WORTH_BORROWING,
        evidence=("path-token:item-0",),
        method_compared=True,
    )
    ranked = rank_recommendations(
        (
            RecommendationCandidate(
                catalogue_id=entry.catalogue_id,
                capability_id=entry.capability_id,
                factors=RecommendationFactors(
                    reliability_risk=3,
                    job_relevance=2,
                    workflow_leverage=1,
                    evidence_strength=2,
                    adoption_effort=1,
                ),
                evidence_ids=("path-token:item-0",),
                reason=entry.reason,
            ),
        )
    )
    ledger = ComparisonLedger(
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=(_human(entry.catalogue_id),),
        entries=(entry,),
        ranked_recommendations=ranked,
        reciprocal_answer="No transferable method cleared the evidence bar.",
    )

    assert ledger.ranked_recommendations == ranked


def test_ranked_recommendation_accepts_matching_capability_observation_ids() -> None:
    entry = _disposition(
        "catalogue-item-0",
        Disposition.WORTH_BORROWING,
        evidence=("path-token:item-0",),
        method_compared=True,
    )
    human = _human(entry.catalogue_id)
    ranked = rank_recommendations(
        (
            RecommendationCandidate(
                catalogue_id=entry.catalogue_id,
                capability_id=entry.capability_id,
                factors=RecommendationFactors(
                    reliability_risk=3,
                    job_relevance=2,
                    workflow_leverage=1,
                    evidence_strength=2,
                    adoption_effort=1,
                ),
                evidence_ids=entry.evidence_references,
                observation_ids=human.person_observation_ids,
                reason=entry.reason,
            ),
        )
    )

    ledger = ComparisonLedger(
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=(human,),
        entries=(entry,),
        ranked_recommendations=ranked,
        reciprocal_answer="No transferable method cleared the evidence bar.",
    )

    assert ledger.ranked_recommendations[0].observation_ids == human.person_observation_ids


def test_ranked_recommendation_rejects_observation_outside_matching_capability() -> None:
    entry = _disposition(
        "catalogue-item-0",
        Disposition.WORTH_BORROWING,
        evidence=("path-token:item-0",),
        method_compared=True,
    )
    ranked = rank_recommendations(
        (
            RecommendationCandidate(
                catalogue_id=entry.catalogue_id,
                capability_id=entry.capability_id,
                factors=RecommendationFactors(
                    reliability_risk=3,
                    job_relevance=2,
                    workflow_leverage=1,
                    evidence_strength=2,
                    adoption_effort=1,
                ),
                evidence_ids=entry.evidence_references,
                observation_ids=("arbitrary-observation",),
                reason=entry.reason,
            ),
        )
    )

    with pytest.raises(ValidationError, match="observation IDs"):
        ComparisonLedger(
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=(_human(entry.catalogue_id),),
            entries=(entry,),
            ranked_recommendations=ranked,
            reciprocal_answer="No transferable method cleared the evidence bar.",
        )


def test_ranked_recommendation_accepts_unsorted_catalogue_evidence_references() -> None:
    entry = _disposition(
        "catalogue-item-0",
        Disposition.WORTH_BORROWING,
        evidence=("path-token:z", "path-token:a"),
        method_compared=True,
    )
    ranked = rank_recommendations(
        (
            RecommendationCandidate(
                catalogue_id=entry.catalogue_id,
                capability_id=entry.capability_id,
                factors=RecommendationFactors(
                    reliability_risk=3,
                    job_relevance=2,
                    workflow_leverage=1,
                    evidence_strength=2,
                    adoption_effort=1,
                ),
                evidence_ids=entry.evidence_references,
                reason=entry.reason,
            ),
        )
    )

    ledger = ComparisonLedger(
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=(_human(entry.catalogue_id),),
        entries=(entry,),
        ranked_recommendations=ranked,
        reciprocal_answer="No transferable method cleared the evidence bar.",
    )

    assert ledger.ranked_recommendations[0].evidence_ids == (
        "path-token:a",
        "path-token:z",
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("evidence_ids", ("path-token:other",), "evidence"),
        ("reason", "A different reason.", "reason"),
        ("observation_ids", ("arbitrary-observation",), "observation"),
    ),
)
def test_ranked_recommendation_is_bound_to_ledger_evidence_and_reason(
    field: str,
    value: object,
    message: str,
) -> None:
    entry = _disposition(
        "catalogue-item-0",
        Disposition.WORTH_BORROWING,
        evidence=("path-token:item-0",),
        method_compared=True,
    )
    candidate_values: dict[str, object] = {
        "catalogue_id": entry.catalogue_id,
        "capability_id": entry.capability_id,
        "factors": RecommendationFactors(
            reliability_risk=3,
            job_relevance=2,
            workflow_leverage=1,
            evidence_strength=2,
            adoption_effort=1,
        ),
        "evidence_ids": ("path-token:item-0",),
        "reason": entry.reason,
    }
    candidate_values[field] = value
    ranked = rank_recommendations((RecommendationCandidate(**candidate_values),))

    with pytest.raises(ValidationError, match=message):
        ComparisonLedger(
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=(_human(entry.catalogue_id),),
            entries=(entry,),
            ranked_recommendations=ranked,
            reciprocal_answer="No transferable method cleared the evidence bar.",
        )


def test_ledger_ranked_recommendations_reject_validation_bypasses() -> None:
    entry = _disposition(
        "catalogue-item-0",
        Disposition.WORTH_BORROWING,
        evidence=("path-token:item-0",),
        method_compared=True,
    )
    ranked = rank_recommendations(
        (
            RecommendationCandidate(
                catalogue_id=entry.catalogue_id,
                capability_id=entry.capability_id,
                factors=RecommendationFactors(
                    reliability_risk=3,
                    job_relevance=2,
                    workflow_leverage=1,
                    evidence_strength=2,
                    adoption_effort=1,
                ),
                evidence_ids=entry.evidence_references,
                reason=entry.reason,
            ),
        )
    )
    values = {
        "catalogue_version": 5,
        "catalogue_sha256": CATALOGUE_SHA,
        "capabilities": (_human(entry.catalogue_id),),
        "entries": (entry,),
        "ranked_recommendations": (
            {
                **ranked[0].model_dump(),
                "rank": 11,
            },
        ),
        "reciprocal_answer": "No transferable method cleared the evidence bar.",
    }

    ledger = ComparisonLedger(
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=(_human(entry.catalogue_id),),
        entries=(entry,),
        ranked_recommendations=ranked,
        reciprocal_answer="No transferable method cleared the evidence bar.",
    )
    with pytest.raises(ValidationError):
        ledger.model_copy(update={"ranked_recommendations": values["ranked_recommendations"]})
    with pytest.raises(ValidationError):
        ComparisonLedger.model_construct(**values)


def test_same_name_without_method_evidence_cannot_be_shared() -> None:
    with pytest.raises(ValidationError, match="method evidence"):
        _disposition(
            "system-doctor",
            Disposition.SHARED,
            evidence=("path-token:doctor",),
        )


def test_dex_should_learn_requires_compared_method_evidence() -> None:
    with pytest.raises(ValidationError, match="Dex-should-learn requires method evidence"):
        _disposition(
            "system-doctor",
            Disposition.DEX_SHOULD_LEARN,
            evidence=("path-token:doctor",),
        )


def test_scored_disposition_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="requires evidence"):
        _disposition("backup-proof", Disposition.STRONG_HERE)


def test_complete_catalogue_identity_set_is_accepted() -> None:
    catalogue = _catalogue()
    catalogue_ids = tuple(item.capability_id for item in catalogue.capabilities)
    ledger = ComparisonLedger.for_catalogue(
        catalogue,
        catalogue_version=5,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=(_human(*catalogue_ids),),
        entries=tuple(_disposition(item) for item in catalogue_ids),
    )

    assert {entry.catalogue_id for entry in ledger.entries} == set(catalogue_ids)
    assert ledger.reciprocal_answer == "No transferable method cleared the evidence bar."


def test_human_capability_cannot_point_at_an_unknown_catalogue_entry() -> None:
    catalogue = _catalogue()
    catalogue_ids = tuple(item.capability_id for item in catalogue.capabilities)

    with pytest.raises(ValidationError, match="unknown catalogue IDs"):
        ComparisonLedger.for_catalogue(
            catalogue,
            catalogue_version=5,
            catalogue_sha256=CATALOGUE_SHA,
            capabilities=(_human(*catalogue_ids, "not-in-catalogue"),),
            entries=tuple(_disposition(item) for item in catalogue_ids),
        )


def test_comparison_ledger_resolves_without_importing_work_first() -> None:
    """The ledger must resolve on its own, not by luck of collection order.

    ``work`` supplies the deferred ``WorkAudit`` annotation, so any suite that
    happens to import ``work`` first hides a missing rebuild. Only a fresh
    interpreter importing this module alone proves it, which is why this runs
    in a subprocess.
    """

    probe = (
        "from capability_exchange.diagnosis.comparison import ComparisonLedger\n"
        "assert ComparisonLedger.__pydantic_complete__, 'ledger is not fully defined'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Signed MCP tool inventories: complete must be reachable, sampled must stay
# honest.  The first real evaluation reported "0 complete MCP inventories;
# 11 sampled" because the live v6 catalogue predates the complete-tools
# channel and publishes at most five example tools per server — and Lens
# additionally marked a server "sampled" even when its signed examples
# provably were its whole inventory (examples == declared tool_count).
# ---------------------------------------------------------------------------


def _mcp_catalogue(mcp_entry: dict[str, object]) -> object:
    from tests.catalogue.test_significant_contract import _catalogue as _significant_catalogue

    from capability_exchange.catalogue.v2 import CatalogueV2

    return CatalogueV2.model_validate(_significant_catalogue(capabilities=[mcp_entry]))


def _sampled_shape_mcp(*, declared: int, examples: list[str]) -> dict[str, object]:
    """An mcp-server entry in the live v6 shape: count + examples only."""
    from tests.catalogue.test_significant_contract import _mcp as _significant_mcp

    entry = _significant_mcp()
    entry.pop("tools")
    entry.pop("tool_inventory")
    entry["tool_count"] = declared
    entry["example_tools"] = examples
    return entry


def _inventory_ledger(catalogue) -> ComparisonLedger:  # type: ignore[no-untyped-def]
    return ComparisonLedger.for_catalogue(
        catalogue,
        catalogue_version=6,
        catalogue_sha256=CATALOGUE_SHA,
        capabilities=tuple(
            HumanCapability(
                capability_id=item.capability_id,
                title=item.title,
                job_ids=tuple(item.jobs),
                catalogue_ids=(item.capability_id,),
                person_observation_ids=(),
            )
            for item in catalogue.capabilities
        ),
        entries=tuple(
            CatalogueDisposition(
                catalogue_id=item.capability_id,
                disposition=Disposition.NOT_ASSESSED,
                capability_id=item.capability_id,
                reason="Not assessed.",
            )
            for item in catalogue.capabilities
        ),
    )


def test_exhaustive_signed_sample_is_a_complete_inventory() -> None:
    """Examples that equal the declared count ARE the whole inventory.

    The live catalogue's ``dex-analytics`` declares 4 tools and publishes 4
    distinct examples; reporting it "sampled" understates signed truth. The
    derivation uses signed fields only, so it cannot overreach: a smaller
    sample stays sampled (next test).
    """
    from capability_exchange.diagnosis.report import canonical_fact_block

    catalogue = _mcp_catalogue(
        _sampled_shape_mcp(
            declared=4,
            examples=["list_tasks", "add_note", "close_task", "reopen_task"],
        )
    )
    ledger = _inventory_ledger(catalogue)

    (inventory,) = ledger.mcp_tools_by_server
    assert inventory.inventory_status == "complete"
    assert inventory.declared_tool_count == 4
    assert set(inventory.tools) == {"list_tasks", "add_note", "close_task", "reopen_task"}

    facts = canonical_fact_block(ledger)
    assert "1 complete inventory; 0 sampled inventories" in facts
    assert "remaining tool identities Unknown" not in facts


def test_partial_signed_sample_stays_honestly_sampled() -> None:
    """A sample below the declared count must never be promoted to complete."""
    from capability_exchange.diagnosis.report import canonical_fact_block

    catalogue = _mcp_catalogue(
        _sampled_shape_mcp(
            declared=15,
            examples=["list_tasks", "add_note", "close_task", "reopen_task", "plan_day"],
        )
    )
    ledger = _inventory_ledger(catalogue)

    (inventory,) = ledger.mcp_tools_by_server
    assert inventory.inventory_status == "sampled"
    assert inventory.declared_tool_count == 15
    assert len(inventory.tools) == 5

    facts = canonical_fact_block(ledger)
    assert "0 complete inventories; 1 sampled inventory" in facts
    assert "5 published examples; remaining tool identities Unknown" in facts


def test_ordinary_thirteen_tool_server_inventories_completely() -> None:
    """An ordinary real server (13 declared tools) reaches ``complete``.

    Five examples can never cover it, so the signed ``tools`` channel — the
    contract bounds it at 500 tools per server, more than ten times the
    largest real Dex server's 47 — is what carries the full inventory
    end-to-end into the ledger and the report fact block.
    """
    from tests.catalogue.test_significant_contract import _mcp as _significant_mcp

    from capability_exchange.diagnosis.report import canonical_fact_block

    tools = [f"tool_{index}" for index in range(13)]
    entry = _significant_mcp(tools=tools, examples=tools[:5])
    catalogue = _mcp_catalogue(entry)
    ledger = _inventory_ledger(catalogue)

    (inventory,) = ledger.mcp_tools_by_server
    assert inventory.inventory_status == "complete"
    assert inventory.declared_tool_count == 13
    assert tuple(inventory.tools) == tuple(tools)

    facts = canonical_fact_block(ledger)
    assert "13 declared tools across 1 server; 1 complete inventory" in facts
    assert "remaining tool identities Unknown" not in facts
