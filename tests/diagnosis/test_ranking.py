"""Explainable, deterministic recommendation ranking."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from capability_exchange.diagnosis.ranking import (
    MAX_RECOMMENDATIONS,
    RankedRecommendation,
    RecommendationCandidate,
    RecommendationFactors,
    rank_recommendations,
)


def candidate(
    catalogue_id: str,
    *,
    risk: int = 0,
    relevance: int = 0,
    leverage: int = 0,
    evidence: int = 1,
    effort: int = 1,
) -> RecommendationCandidate:
    return RecommendationCandidate(
        catalogue_id=catalogue_id,
        capability_id=f"capability-{catalogue_id}",
        factors=RecommendationFactors(
            reliability_risk=risk,
            job_relevance=relevance,
            workflow_leverage=leverage,
            evidence_strength=evidence,
            adoption_effort=effort,
        ),
        evidence_ids=(f"evidence:{catalogue_id}",),
        reason="This available capability addresses a grounded gap.",
    )


def test_ten_recommendations_are_allowed_but_eleven_are_refused() -> None:
    assert MAX_RECOMMENDATIONS == 10
    ten = tuple(candidate(f"cap-{index}") for index in range(10))
    ranked = rank_recommendations(ten)

    assert len(ranked) == 10
    assert [item.rank for item in ranked] == list(range(1, 11))

    with pytest.raises(ValueError, match="at most 10"):
        rank_recommendations((*ten, candidate("cap-10")))


def test_recommendations_have_one_stable_explainable_order() -> None:
    candidates = (
        candidate("high-effort", relevance=3, leverage=3, evidence=3, effort=3),
        candidate("low-effort", relevance=3, leverage=3, evidence=3, effort=1),
        candidate("urgent", risk=3, relevance=1, leverage=1, evidence=2, effort=3),
    )

    ranked = rank_recommendations(candidates)

    assert [(item.rank, item.catalogue_id) for item in ranked] == [
        (1, "urgent"),
        (2, "low-effort"),
        (3, "high-effort"),
    ]
    assert ranked[0].factors.reliability_risk == 3
    assert not any("percent" in field_name for field_name in RankedRecommendation.model_fields)


def test_recommendation_factors_and_candidates_are_bounded() -> None:
    with pytest.raises(ValidationError):
        RecommendationFactors(
            reliability_risk=4,
            job_relevance=0,
            workflow_leverage=0,
            evidence_strength=1,
            adoption_effort=1,
        )
    with pytest.raises(ValidationError):
        RecommendationFactors(
            reliability_risk=0,
            job_relevance=0,
            workflow_leverage=0,
            evidence_strength=0,
            adoption_effort=1,
        )
    with pytest.raises(ValidationError):
        RecommendationCandidate(
            catalogue_id="too-many-evidence",
            capability_id="capability-too-many-evidence",
            factors=RecommendationFactors(
                reliability_risk=0,
                job_relevance=0,
                workflow_leverage=0,
                evidence_strength=1,
                adoption_effort=1,
            ),
            evidence_ids=tuple(f"evidence:{index}" for index in range(9)),
            reason="This available capability addresses a grounded gap.",
        )


def test_ranking_models_reject_copy_and_construct_bypasses() -> None:
    item = candidate("bounded")

    with pytest.raises(TypeError, match="validated model_copy"):
        item.copy()
    with pytest.raises(TypeError, match="validated model_copy"):
        item.factors.copy()
    with pytest.raises(ValidationError):
        RecommendationCandidate.model_construct(
            **{
                **item.model_dump(),
                "evidence_ids": tuple(f"evidence:{index}" for index in range(9)),
            }
        )
