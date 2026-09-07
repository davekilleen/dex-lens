"""Tests for the Wow Gate expectation manifest."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.diagnosis.test_significant_family_assessment import (
    _catalogue,
    _family,
    _fingerprint,
    _observation,
)

from capability_exchange.diagnosis.expectations import (
    WOW_EXPECTATIONS,
    ExpectationState,
    assess_wow_expectations,
)
from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.diagnosis.significant_families import assess_significant_families

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def _all_families_catalogue():
    families = tuple(
        _family(
            family_id,
            profile="filesystem",
            members=["workflow-skill"],
            components=[{"component_type": "capability", "capability_id": "workflow-skill"}],
        )
        for family_id in WOW_EXPECTATIONS
    )
    return _catalogue(*families)


def test_wow_manifest_names_every_agreed_family_once() -> None:
    assert WOW_EXPECTATIONS == (
        "meeting-follow-through",
        "living-people-company-context",
        "durable-task-continuity",
        "external-task-interoperability",
        "connected-work-context",
        "pipedrive-pipeline-continuity",
        "daily-weekly-operating-rhythm",
        "durable-work-memory",
        "proactive-health-and-recovery",
        "backup-and-restore-confidence",
        "safe-change-and-rewind",
        "capability-discovery-and-adoption",
        "privacy-safe-feedback-loop",
        "career-growth-evidence",
    )


def test_assess_wow_expectations_requires_every_manifest_row() -> None:
    catalogue = _all_families_catalogue()
    fingerprint = _fingerprint(_observation(ObservationKind.SKILL, "weekly-plan"))
    assessments = assess_significant_families(catalogue, fingerprint)
    rows = assess_wow_expectations(catalogue, assessments)
    assert tuple(item.family_id for item in rows) == WOW_EXPECTATIONS
    assert all(isinstance(item.state, ExpectationState) for item in rows)


def test_duplicate_family_assessment_fails_closed() -> None:
    catalogue = _all_families_catalogue()
    fingerprint = _fingerprint(_observation(ObservationKind.SKILL, "weekly-plan"))
    assessments = assess_significant_families(catalogue, fingerprint)
    with pytest.raises(ValueError, match="duplicate"):
        assess_wow_expectations(catalogue, (*assessments, assessments[0]))


def test_family_free_catalogue_yields_fourteen_loud_not_gated_rows() -> None:
    """The silent hole: a family-free catalogue must never return an empty manifest.

    The first real run had no release-gap story and no sentence saying why,
    because ``assess_wow_expectations`` silently returned ``()`` when the
    catalogue carried no signed capability families.  Observed failing on the
    unchanged tree: the rows tuple was empty.
    """

    catalogue = _catalogue()  # no signed capability families
    rows = assess_wow_expectations(catalogue, ())

    assert [item.family_id for item in rows] == list(WOW_EXPECTATIONS)
    assert all(item.state.value == "not-gated" for item in rows)
    assert all(item.evidence_ids == () for item in rows)
    reasons = {item.reason for item in rows}
    assert len(reasons) == 1
    assert "no signed capability-family contract" in next(iter(reasons)).lower()


def test_partially_signed_catalogue_is_also_loud_never_silent() -> None:
    """A catalogue signing some but not all manifest families is the same hole."""

    catalogue = _all_families_catalogue()
    partial = catalogue.model_copy(
        update={"capability_families": catalogue.capability_families[:3]}
    )
    rows = assess_wow_expectations(partial, ())

    assert [item.family_id for item in rows] == list(WOW_EXPECTATIONS)
    assert all(item.state.value == "not-gated" for item in rows)
