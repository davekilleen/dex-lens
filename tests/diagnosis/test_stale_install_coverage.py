"""On a stale install, a name is not a capability.

A real run against an install eighty-four releases behind reported the
proactive-health area as partially covered. The install had no health
subsystem at all; it had a *file named* `dex-doctor`, and the capability Dex
means by that name shipped sixty-seven releases later. Identity overlap was
read as coverage, the family state is what a reader's eye lands on, and the
release delta that contradicted it sat beside it in smaller print.

These tests pin the rule: a signed family member whose ``since_release``
post-dates the install's own release cannot have been present at that
install, so a local artifact sharing its name is not evidence of it. Every
fixture is invented; the install release comes from the stale-install
fixture's own changelog.
"""

from __future__ import annotations

from pathlib import Path

from tests.diagnosis.test_significant_family_assessment import (
    _family,
    _job,
    _skill,
)
from tests.evals.stale_install_fixture import write_stale_install

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS, build_family_map
from capability_exchange.diagnosis.run import ExpectationState

CATALOGUE_SHA = "0" * 64

#: Newer than the stale-install fixture's own release, and by a wide margin —
#: the situation the real vault was in.
MEMBER_SINCE_RELEASE = "1.80.0"

#: Older than the fixture's release, so the install genuinely could carry it.
PRE_INSTALL_SINCE_RELEASE = "1.1.0"


#: The area whose real-world failure this file exists for. Its member is a
#: skill the stale-install fixture ships, so the name matches locally and the
#: only question left is whether the lineage is honoured.
HEALTH_FAMILY = "proactive-health-and-recovery"
HEALTH_MEMBER = "vault-doctor"


def _catalogue_with_member_since(since_release: str) -> CatalogueV2:
    """A catalogue signing all fourteen areas, one with a chosen lineage.

    Every expectation has to be signed or the map yields fourteen loud
    not-gated rows and says nothing about coverage at all. Only the health
    family's member is present in the fixture; the other thirteen carry
    members no local artifact names, so they stay absent and silent.
    """

    capabilities = [_skill(HEALTH_MEMBER)]
    capabilities[0]["since_release"] = since_release
    families = [
        _family(
            HEALTH_FAMILY,
            profile="catalogue",
            members=[HEALTH_MEMBER],
            components=[
                {"component_type": "capability", "capability_id": HEALTH_MEMBER}
            ],
        )
    ]
    for family_id in WOW_EXPECTATIONS:
        if family_id == HEALTH_FAMILY:
            continue
        member = f"{family_id}-absent-member"
        entry = _skill(member)
        entry["since_release"] = PRE_INSTALL_SINCE_RELEASE
        capabilities.append(entry)
        families.append(
            _family(
                family_id,
                profile="catalogue",
                members=[member],
                components=[
                    {"component_type": "capability", "capability_id": member}
                ],
            )
        )
    return CatalogueV2.model_validate(
        {
            "jobs_taxonomy": [_job()],
            "capabilities": capabilities,
            "capability_aliases": [],
            "capability_families": families,
            "portable_brief": {
                "format": "markdown",
                "audience": "the person's own AI system",
                "safety_boundary": "guidance only; it changes nothing",
            },
        }
    )


def _row_for(tmp_path: Path, *, since_release: str) -> object:
    fingerprint = write_stale_install(tmp_path / "vault")
    family_map = build_family_map(
        _catalogue_with_member_since(since_release),
        fingerprint,
        catalogue_version=6,
        catalogue_sha256=CATALOGUE_SHA,
        core_release="v1.97.0",
    )
    return next(item for item in family_map.rows if item.family_id == HEALTH_FAMILY)


def test_a_member_newer_than_the_install_is_not_counted_as_coverage(
    tmp_path: Path,
) -> None:
    """The `dex-doctor` case: same name, capability shipped long afterwards."""

    row = _row_for(tmp_path, since_release=MEMBER_SINCE_RELEASE)

    # Observed in sequence while building this: `present` before the lineage
    # rule existed, then `unknown` once name matches were disqualified but the
    # fold still called it an absence of evidence, and only then `absent` —
    # which is the useful and the honest answer, because the signed lineage
    # proves the capability could not have been there.
    assert row.state is ExpectationState.ABSENT
    assert "after your install's own release" in row.reason


def test_the_absence_is_evidenced_rather_than_merely_unresolved(
    tmp_path: Path,
) -> None:
    """A wall of Unknown is what this replaced; it must not come back."""

    row = _row_for(tmp_path, since_release=MEMBER_SINCE_RELEASE)

    assert row.state is not ExpectationState.UNKNOWN
    assert "unresolved, not proof" not in row.reason


def test_a_member_predating_the_install_still_counts_as_coverage(
    tmp_path: Path,
) -> None:
    """The positive control: the rule must not silence honest coverage."""

    row = _row_for(tmp_path, since_release=PRE_INSTALL_SINCE_RELEASE)

    assert row.state is ExpectationState.PRESENT
