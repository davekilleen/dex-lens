"""Whether Dex is installed is a question about Dex, not about name overlap.

A person who never installed Dex is the population Lens most needs to
convince, and the report reached them by the wrong route. The job-axis block
that serves them well fires only when *zero* observations match a signed
identity, and 85 of the catalogue's 117 capability ids carry no namespace
prefix — `journal`, `review`, `daily-plan`, `create-skill`. One coincidental
collision routed them onto the lineage path, where the release-gap block asked
them to approve a folder holding a Dex release file that cannot exist.

These tests pin the three populations apart on evidence of Dex's *presence*:
no Dex, Dex present with its version unreadable, and Dex present with a known
version. Every fixture is invented.
"""

from __future__ import annotations

from pathlib import Path

from tests.diagnosis.test_stale_install_coverage import (
    PRE_INSTALL_SINCE_RELEASE,
    _catalogue_with_member_since,
)
from tests.evals.stale_install_fixture import (
    RETIRED_STOCK_SKILLS,
    write_stale_install,
)

from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.diagnosis.origin import signed_identity_keys_for
from capability_exchange.diagnosis.significant_families import (
    is_non_lineage,
    observed_release_lineage,
)


def _catalogue() -> object:
    return _catalogue_with_member_since(PRE_INSTALL_SINCE_RELEASE)


def _keys() -> frozenset[str]:
    return signed_identity_keys_for(_catalogue())


def test_the_fixture_really_does_collide_with_a_signed_capability_name() -> None:
    """Guard the guard: without the collision the next test proves nothing."""

    assert "vault-doctor" in RETIRED_STOCK_SKILLS
    assert any(
        key.endswith("vault-doctor") for key in _keys()
    ), "the catalogue fixture must name the colliding capability"


def test_a_system_without_dex_is_classified_as_such_despite_a_name_collision(
    tmp_path: Path,
) -> None:
    """F8: a coincidence must not be read as evidence that Dex is installed."""

    fingerprint = write_stale_install(tmp_path / "vault", dex_present=False)

    assert is_non_lineage(fingerprint), (
        "a system carrying none of Dex's own artefacts is not a Dex install, "
        "however many of its capability names happen to coincide"
    )


def test_dex_present_with_an_unreadable_version_is_not_classified_as_absent(
    tmp_path: Path,
) -> None:
    """The middle population: Dex is here, its release just cannot be read.

    Pushing the unreleased section past the detector's read window is exactly
    how a real install hides its own version, so this is the honest way to
    produce the state rather than deleting a file no real vault lacks.

    Honest note: this assertion also holds before the presence fix, but for
    the wrong reason — the colliding capability name defeats the old
    match-based threshold. After the fix it holds because Dex's own artefacts
    are present, and it fails if presence detection regresses.
    """

    fingerprint = write_stale_install(
        tmp_path / "vault", unreleased_notes=400, dex_present=True
    )
    inspected, _evidence = observed_release_lineage(fingerprint)

    assert inspected is None, "this fixture is meant to hide its own version"
    assert not is_non_lineage(fingerprint), (
        "Dex's own artefacts are present, so this is a Dex install whose "
        "version is unreadable — not a system without Dex"
    )


def test_dex_present_and_readable_still_establishes_lineage(tmp_path: Path) -> None:
    """The positive control for the ordinary stale install."""

    fingerprint = write_stale_install(tmp_path / "vault")
    inspected, evidence = observed_release_lineage(fingerprint)

    assert inspected is not None
    assert evidence
    assert not is_non_lineage(fingerprint)


def test_a_dex_install_mints_exactly_one_core_release_observation(
    tmp_path: Path,
) -> None:
    """Presence is carried by one observation, whatever the version says."""

    fingerprint = write_stale_install(tmp_path / "vault", unreleased_notes=400)
    presence = [
        item
        for item in fingerprint.observations
        if item.kind is ObservationKind.RELEASE and item.identity == "dex-core"
    ]

    assert len(presence) == 1
    assert not any(
        attribute.key == "release-id" for attribute in presence[0].attributes
    ), "an unreadable version must not be reported as a release identifier"
