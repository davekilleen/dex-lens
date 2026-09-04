"""Pure, leaf-driven state for signed capability families.

Families are release-owned descriptions of an outcome.  They deliberately do
not carry an availability/status field: the only source of that state is the
existing ``capability_is_active`` result for each signed member entry.  This
module is read-only and has no serialization or report-engine side effects.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.catalogue.v2 import (
    ActiveSkillCapabilityEntryV2,
    CapabilityFamilyV2,
    CatalogueCapabilityEntryV2,
    LegacySkillCapabilityEntryV2,
    McpServerCapabilityEntryV2,
    ScheduledAutomationCapabilityEntryV2,
    SystemEngineCapabilityEntryV2,
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

_VALID_ENTRY_TYPES = (
    LegacySkillCapabilityEntryV2,
    ActiveSkillCapabilityEntryV2,
    McpServerCapabilityEntryV2,
    ScheduledAutomationCapabilityEntryV2,
    SystemEngineCapabilityEntryV2,
)


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


class FamilyDelta(InventoriedModel):
    """Exact signed member changes after one inspected Dex release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    family_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,119}$")
    title: str = Field(min_length=1, max_length=160)
    outcome: str = Field(min_length=1, max_length=800)
    current_version: str = Field(
        pattern=r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
    )
    inspected_version: str = Field(
        pattern=r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
    )
    availability: FamilyAvailability
    introduced_member_ids: tuple[str, ...]
    changed_member_ids: tuple[str, ...]
    available_member_ids: tuple[str, ...]
    unavailable_member_ids: tuple[str, ...]
    recommendable_member_ids: tuple[str, ...]

    @field_validator(
        "introduced_member_ids",
        "changed_member_ids",
        "available_member_ids",
        "unavailable_member_ids",
        "recommendable_member_ids",
    )
    @classmethod
    def _member_ids_are_bounded_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("family release member IDs must be unique")
        if any(re.fullmatch(r"^[a-z0-9][a-z0-9-]{0,119}$", value) is None for value in values):
            raise ValueError("family release member ID is invalid")
        return values

    @model_validator(mode="after")
    def _release_change_is_derived(self) -> Self:
        changed = set(self.introduced_member_ids) | set(self.changed_member_ids)
        members = set(self.available_member_ids) | set(self.unavailable_member_ids)
        if not changed:
            raise ValueError("family release change must contain signed lineage evidence")
        if set(self.introduced_member_ids) & set(self.changed_member_ids):
            raise ValueError("introduced and changed family members must not overlap")
        if not changed <= members:
            raise ValueError("family release changes must reference family members")
        expected_availability = (
            FamilyAvailability.AVAILABLE
            if not self.unavailable_member_ids
            else FamilyAvailability.UNAVAILABLE
            if not self.available_member_ids
            else FamilyAvailability.PARTIAL
        )
        if self.availability is not expected_availability:
            raise ValueError("family release availability must derive from member state")
        if self.recommendable_member_ids != self.available_member_ids:
            raise ValueError("only available family members may be recommended")
        return self


def _ordered_member_entries(
    family: CapabilityFamilyV2,
    entries: Iterable[CatalogueCapabilityEntryV2],
) -> tuple[CatalogueCapabilityEntryV2, ...]:
    by_id: dict[str, CatalogueCapabilityEntryV2] = {}
    for entry in entries:
        if not isinstance(entry, _VALID_ENTRY_TYPES):
            raise TypeError(
                "family entries must be validated CatalogueCapabilityEntryV2 model instances"
            )
        capability_id = entry.capability_id
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


def _entry_is_active(entry: CatalogueCapabilityEntryV2) -> bool:
    """Apply the catalogue's one canonical leaf-availability rule."""
    return capability_is_active(entry)


def summarise_family(
    family: CapabilityFamilyV2,
    entries: Iterable[CatalogueCapabilityEntryV2],
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
        if _entry_is_active(entry)
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
    entries: Iterable[CatalogueCapabilityEntryV2],
) -> CapabilityFamilySummary:
    """US-spelling alias for :func:`summarise_family`."""

    return summarise_family(family, entries)


def _semver_key(value: str) -> tuple[tuple[int, int, int], tuple[tuple[int, object], ...]]:
    """Return a comparison key for the bounded SemVer forms Lens accepts."""

    clean = value.removeprefix("v").split("+", maxsplit=1)[0]
    release, separator, prerelease = clean.partition("-")
    release_key = tuple(int(part) for part in release.split("."))
    if len(release_key) != 3:
        raise ValueError(f"{value!r} is not a semantic version")
    if not separator:
        # A final release sorts after every prerelease of the same version.
        return release_key, ((2, ""),)
    prerelease_key: list[tuple[int, object]] = []
    for part in prerelease.split("."):
        prerelease_key.append((0, int(part)) if part.isdigit() else (1, part))
    return release_key, tuple(prerelease_key)


def _release_changed_after(
    release: str,
    *,
    inspected_version: str,
    current_version: str,
) -> bool:
    release_key = _semver_key(release)
    return _semver_key(inspected_version) < release_key <= _semver_key(current_version)


def build_family_delta(
    *,
    current_version: str,
    inspected_version: str,
    family: CapabilityFamilyV2,
    entries: Iterable[CatalogueCapabilityEntryV2],
) -> FamilyDelta | None:
    """Build a delta only from signed skill lineage; otherwise return Unknown."""

    ordered = _ordered_member_entries(family, entries)
    summary = summarise_family(family, ordered)
    introduced = tuple(
        entry.capability_id
        for entry in ordered
        if isinstance(entry, (LegacySkillCapabilityEntryV2, ActiveSkillCapabilityEntryV2))
        and _release_changed_after(
            entry.since_release,
            inspected_version=inspected_version,
            current_version=current_version,
        )
    )
    introduced_set = set(introduced)
    changed = tuple(
        entry.capability_id
        for entry in ordered
        if isinstance(entry, (LegacySkillCapabilityEntryV2, ActiveSkillCapabilityEntryV2))
        and entry.capability_id not in introduced_set
        and any(
            _release_changed_after(
                release,
                inspected_version=inspected_version,
                current_version=current_version,
            )
            for release in entry.changed_in
        )
    )
    if not introduced and not changed:
        return None
    return FamilyDelta(
        family_id=summary.family_id,
        title=summary.title,
        outcome=summary.outcome,
        current_version=current_version,
        inspected_version=inspected_version,
        availability=summary.availability,
        introduced_member_ids=introduced,
        changed_member_ids=changed,
        available_member_ids=summary.available_member_ids,
        unavailable_member_ids=summary.unavailable_member_ids,
        recommendable_member_ids=summary.recommendable_member_ids,
    )
