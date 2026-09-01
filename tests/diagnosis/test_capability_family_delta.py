"""Pure family availability derivation tests.

The family state is a view over signed leaf entries.  It is intentionally not
stored on the catalogue family object itself, so a dormant or parked member
can never be upgraded by family metadata.
"""

from __future__ import annotations

import pytest
from tests.catalogue.test_enriched_contract import legacy_skill

from capability_exchange.catalogue.v2 import (
    CapabilityFamilyV2,
    LegacySkillCapabilityEntryV2,
    SystemEngineCapabilityEntryV2,
)
from capability_exchange.diagnosis.families import (
    FamilyAvailability,
    build_family_delta,
    summarise_family,
)


def _family(member_ids: tuple[str, ...]) -> CapabilityFamilyV2:
    return CapabilityFamilyV2.model_validate(
        {
            "family_id": "task-continuity",
            "title": "Task continuity",
            "outcome": "Tasks stay connected from capture through completion.",
            "jobs": ["plan-my-work"],
            "aliases": ["tasks-that-stick"],
            "member_capability_ids": list(member_ids),
            "components": [
                {"component_type": "source-component", "component_id": "task-continuity"}
            ],
            "assessment": {"mode": "manual-only", "reason": "requires a local review"},
        }
    )


def _entry(capability_id: str, availability: str) -> object:
    return SystemEngineCapabilityEntryV2.model_validate(
        {
            "capability_id": capability_id,
            "capability_class": "system-engine",
            "impact_tier": "high",
            "availability": availability,
            "title": "Test engine",
            "summary": "A test engine.",
            "value": "A test outcome.",
            "jobs": ["plan-my-work"],
            "prerequisites": ["a running Dex install"],
            "trade_offs": ["test only"],
            "evidence": [
                {
                    "level": "supported",
                    "source": "test",
                    "summary": "release evidence",
                    "limitations": "local state is not inspected",
                }
            ],
            "release_provenance": "core-release",
            "source_paths": ["core/engines/test.py"],
            "component_count": 1,
            "example_components": ["core/engines/test.py"],
        }
    )


def test_family_state_is_derived_from_active_member_entries() -> None:
    summary = summarise_family(
        family=_family(("active-entry", "parked-entry")),
        entries=(_entry("active-entry", "active"), _entry("parked-entry", "parked")),
    )
    assert summary.availability is FamilyAvailability.PARTIAL
    assert summary.available_member_ids == ("active-entry",)
    assert summary.unavailable_member_ids == ("parked-entry",)
    assert summary.recommendable_member_ids == ("active-entry",)


def test_all_parked_members_are_unavailable_and_never_recommendable() -> None:
    summary = summarise_family(
        family=_family(("parked-entry",)),
        entries=(_entry("parked-entry", "parked"),),
    )
    assert summary.availability is FamilyAvailability.UNAVAILABLE
    assert summary.recommendable_member_ids == ()


def test_all_active_members_are_available() -> None:
    summary = summarise_family(
        family=_family(("active-a", "active-b")),
        entries=(_entry("active-a", "active"), _entry("active-b", "active")),
    )
    assert summary.availability is FamilyAvailability.AVAILABLE
    assert summary.available_member_ids == ("active-a", "active-b")


def test_missing_member_entry_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing.*member"):
        summarise_family(
            family=_family(("active-entry", "missing-entry")),
            entries=(_entry("active-entry", "active"),),
        )


def test_plain_objects_are_not_accepted_as_family_entries() -> None:
    with pytest.raises(TypeError, match="validated CatalogueCapabilityEntryV2"):
        summarise_family(
            family=_family(("active-entry",)),
            entries=(object(),),
        )


def test_legacy_entry_without_availability_never_upgrades_family_to_active() -> None:
    legacy = LegacySkillCapabilityEntryV2.model_validate(
        legacy_skill("legacy-entry", "Legacy Entry")
    )
    summary = summarise_family(
        family=_family(("legacy-entry",)),
        entries=(legacy,),
    )
    assert summary.availability is FamilyAvailability.UNAVAILABLE
    assert summary.recommendable_member_ids == ()


def test_family_delta_explains_unavailable_members_without_recommending_them() -> None:
    delta = build_family_delta(
        current_version="1.97.2",
        inspected_version="1.18.1",
        family=_family(("parked-entry",)),
        entries=(_entry("parked-entry", "parked"),),
    )
    assert "not currently available" in delta.plain_language_state
    assert delta.recommendable_member_ids == ()
