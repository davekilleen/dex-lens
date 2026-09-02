"""Explainable, deterministic ranking for available Lens recommendations."""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import Field, field_validator

from capability_exchange.diagnosis.run import _ValidatedInventoried

__all__ = [
    "MAX_EVIDENCE_IDS",
    "MAX_RECOMMENDATIONS",
    "MAX_REASON_LENGTH",
    "RecommendationCandidate",
    "RecommendationFactors",
    "RankedRecommendation",
    "rank_recommendations",
]

MAX_EVIDENCE_IDS = 8
MAX_REASON_LENGTH = 600
MAX_RECOMMENDATIONS = 10

_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _unique_tokens(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if not value.strip():
            raise ValueError(f"{label} must be non-empty")
    return values


def _unique_identities(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    for value in values:
        if _ID.fullmatch(value) is None:
            raise ValueError(f"{label} must be bounded identities")
    return values


class RecommendationFactors(_ValidatedInventoried):
    """Closed, human-explainable factors used to order one recommendation."""

    reliability_risk: int = Field(ge=0, le=3)
    job_relevance: int = Field(ge=0, le=3)
    workflow_leverage: int = Field(ge=0, le=3)
    evidence_strength: int = Field(ge=1, le=3)
    adoption_effort: int = Field(ge=1, le=3)


class RecommendationCandidate(_ValidatedInventoried):
    """One available, evidence-bound recommendation before ranking."""

    catalogue_id: str = Field(pattern=_ID.pattern)
    capability_id: str = Field(pattern=_ID.pattern)
    factors: RecommendationFactors
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_IDS)
    observation_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(_unique_tokens(values, "recommendation evidence tokens")))

    @field_validator("observation_ids")
    @classmethod
    def _observation_ids_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(_unique_identities(values, "recommendation observation identities")))

    @field_validator("reason")
    @classmethod
    def _reason_is_one_safe_line(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a recommendation reason must be non-empty")
        if _CONTROL.search(value):
            raise ValueError("a recommendation reason must be one bounded line")
        return value


class RankedRecommendation(RecommendationCandidate):
    """A recommendation candidate with its deterministic one-based rank."""

    rank: int = Field(ge=1, le=MAX_RECOMMENDATIONS)


def rank_recommendations(
    candidates: Iterable[RecommendationCandidate],
) -> tuple[RankedRecommendation, ...]:
    """Return candidates in the canonical explainable order, ranked from one."""

    ordered = sorted(
        candidates,
        key=lambda item: (
            -item.factors.reliability_risk,
            -item.factors.job_relevance,
            -item.factors.workflow_leverage,
            -item.factors.evidence_strength,
            item.factors.adoption_effort,
            item.catalogue_id,
        ),
    )
    if len({item.catalogue_id for item in ordered}) != len(ordered):
        raise ValueError("recommendation candidates must have unique catalogue identities")
    if len(ordered) > MAX_RECOMMENDATIONS:
        raise ValueError(
            f"a diagnosis may recommend at most {MAX_RECOMMENDATIONS} Dex additions"
        )
    ranked: list[RankedRecommendation] = []
    for index, item in enumerate(ordered, start=1):
        values = item.model_dump()
        values.pop("rank", None)
        ranked.append(RankedRecommendation(**values, rank=index))
    return tuple(ranked)
