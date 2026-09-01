"""Pure, leaf-driven state for signed capability families.

Families are release-owned descriptions of an outcome.  They deliberately do
not carry an availability/status field: the only source of that state is the
existing ``capability_is_active`` result for each signed member entry.  This
module is read-only and has no serialization or report-engine side effects.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from capability_exchange.catalogue.v2 import (
    CapabilityFamilyV2,
    CatalogueCapabilityEntryV2,
    capability_is_active,
)

__all__ = [
    "CapabilityFamilySummary",
    "FamilyAvailability",
    "FamilyDelta",
    "build_family_delta",
    "summarise_family",
    "summarize_family",
]


class FamilyAvailability(StrEnum):
    """Availability derived from family members, never signed separately."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CapabilityFamilySummary:
    """The deterministic state of one signed family."""

    family_id: str
    title: str
    outcome: str
    availability: FamilyAvailability
    member_capability_ids: tuple[str, ...]
    available_member_ids: tuple[str, ...]
    unavailable_member_ids: tuple[str, ...]
    recommendable_member_ids: tuple[str, ...]


@dataclass(frozen=True)
class FamilyDelta:
    """A plain-language family state suitable for a version-distance view."""

    family_id: str
    title: str
    outcome: str
    current_version: str
    inspected_version: str
    availability: FamilyAvailability
    plain_language_state: str
    available_member_ids: tuple[str, ...]
    unavailable_member_ids: tuple[str, ...]
    recommendable_member_ids: tuple[str, ...]


def _ordered_member_entries(
    family: CapabilityFamilyV2,
    entries: Iterable[CatalogueCapabilityEntryV2 | object],
) -> tuple[object, ...]:
    by_id: dict[str, object] = {}
    for entry in entries:
        capability_id = getattr(entry, "capability_id", None)
        if not isinstance(capability_id, str):
            raise ValueError("family member entry has no capability_id")
        if capability_id in by_id:
            raise ValueError(f"duplicate family member entry {capability_id!r}")
        by_id[capability_id] = entry

    member_ids = tuple(family.member_capability_ids)
    missing = tuple(member_id for member_id in member_ids if member_id not in by_id)
    if missing:
        raise ValueError(
            "missing family member entry(s): " + ", ".join(missing)
        )
    extra = tuple(capability_id for capability_id in by_id if capability_id not in member_ids)
    if extra:
        raise ValueError(
            "family state received non-member entry(s): " + ", ".join(sorted(extra))
        )
    return tuple(by_id[member_id] for member_id in member_ids)


def summarise_family(
    family: CapabilityFamilyV2,
    entries: Iterable[CatalogueCapabilityEntryV2 | object],
) -> CapabilityFamilySummary:
    """Derive family availability solely from the supplied member entries.

    ``entries`` must contain exactly the family members.  This strict shape
    keeps a missing leaf from looking like an unavailable one and prevents a
    caller from accidentally deriving state from a different family.
    """

    ordered = _ordered_member_entries(family, entries)
    member_ids = tuple(family.member_capability_ids)
    available = tuple(
        capability_id
        for capability_id, entry in zip(member_ids, ordered, strict=True)
        if capability_is_active(entry)  # type: ignore[arg-type]
    )
    unavailable = tuple(member_id for member_id in member_ids if member_id not in available)
    if not unavailable:
        state = FamilyAvailability.AVAILABLE
    elif available:
        state = FamilyAvailability.PARTIAL
    else:
        state = FamilyAvailability.UNAVAILABLE
    return CapabilityFamilySummary(
        family_id=family.family_id,
        title=family.title,
        outcome=family.outcome,
        availability=state,
        member_capability_ids=member_ids,
        available_member_ids=available,
        unavailable_member_ids=unavailable,
        # Dormant/parked entries are absent by construction; no second family
        # status may make them recommendation candidates.
        recommendable_member_ids=available,
    )


def summarize_family(
    family: CapabilityFamilyV2,
    entries: Iterable[CatalogueCapabilityEntryV2 | object],
) -> CapabilityFamilySummary:
    """US-spelling alias for :func:`summarise_family`."""

    return summarise_family(family, entries)


def build_family_delta(
    *,
    current_version: str,
    inspected_version: str,
    family: CapabilityFamilyV2,
    entries: Iterable[CatalogueCapabilityEntryV2 | object],
) -> FamilyDelta:
    """Build a deterministic family explanation for a version-distance view."""

    summary = summarise_family(family, entries)
    if summary.availability is FamilyAvailability.AVAILABLE:
        state = "currently available"
    elif summary.availability is FamilyAvailability.PARTIAL:
        state = (
            "partly available; some members are not currently available"
        )
    else:
        state = "not currently available"
    return FamilyDelta(
        family_id=summary.family_id,
        title=summary.title,
        outcome=summary.outcome,
        current_version=current_version,
        inspected_version=inspected_version,
        availability=summary.availability,
        plain_language_state=state,
        available_member_ids=summary.available_member_ids,
        unavailable_member_ids=summary.unavailable_member_ids,
        recommendable_member_ids=summary.recommendable_member_ids,
    )
