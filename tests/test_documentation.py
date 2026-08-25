"""Source-of-truth documentation assertions for the M3 handoff state.

The second half of this file guards a different kind of staleness. SKILL.md is
executed, not read: an assistant following it types the commands in its fenced
blocks verbatim. A worked example that names a job to be done Dex no longer
publishes is not a typo in prose, it is an exit 1 in the middle of somebody's
diagnosis. That is exactly what happened — the Phase 4 example narrowed the
catalogue to ``remember-what-matters`` and ``prepare-for-meetings``, neither of
which the catalogue has ever listed, and the command correctly refused.

The catalogue is published by Dex Core, not by this repository, so the only
honest check reaches for it. That makes the check opt-in, the same way
``tests/catalogue/test_host_identity.py`` gates its live check: CI must not
depend on the network, and a rename in Core must not look like a green build
here. The offline test below keeps the live one from passing vacuously if
someone deletes the examples it reads.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
D0_HASH = "de01cfb1794790a90e34010198063a8449631e32ec450b8f4368cc21ab7bf6f5"
SKILL_MD = REPO_ROOT / "src" / "capability_exchange" / "skill" / "dex-lens" / "SKILL.md"

live_only = pytest.mark.skipif(
    os.environ.get("DEX_LENS_LIVE_CATALOGUE") != "1",
    reason="live catalogue check is opt-in: set DEX_LENS_LIVE_CATALOGUE=1",
)

# A real id, not the ``<ids>`` and ``<id>,<id>`` placeholders alongside them:
# those are shown to the reader, never typed by the assistant.
_REAL_ID_LIST = r"([a-z0-9]+(?:-[a-z0-9]+)*(?:,[a-z0-9]+(?:-[a-z0-9]+)*)*)"


def _ids_after(flag: str) -> set[str]:
    """Every id SKILL.md tells the assistant to pass to ``flag``."""
    pattern = re.compile(rf"{re.escape(flag)}\s+{_REAL_ID_LIST}")
    found: set[str] = set()
    for match in pattern.finditer(SKILL_MD.read_text(encoding="utf-8")):
        found.update(match.group(1).split(","))
    return found


def test_handoff_records_d0_authorization_and_pr4_merge_state() -> None:
    handoff = (REPO_ROOT / "docs" / "handoff" / "HANDOFF.md").read_text()
    status = (REPO_ROOT / "docs" / "STATUS.md").read_text()

    assert D0_HASH in handoff
    assert "D0 recorded" in handoff
    assert "G1–G6" in handoff and "R1–R7" in handoff
    assert "raw personal material" in handoff
    assert "strict majority" in handoff
    assert "merged in PR #4" in status
    assert "draft PR #4" not in status
    assert "No product code exists yet" not in handoff


def test_the_skill_still_carries_a_worked_narrowing_example() -> None:
    """Without this, the live check below would pass by having nothing to check."""
    assert _ids_after("--jobs"), (
        "SKILL.md no longer shows the assistant how to narrow the catalogue by "
        "job to be done, so the live check has nothing to hold against Dex's "
        "published list"
    )


@live_only
def test_every_id_the_skill_types_is_one_the_catalogue_publishes() -> None:
    """A worked example naming an id Dex does not publish exits 1 mid-diagnosis.

    Opt-in because it reaches the network. Run it whenever SKILL.md's examples
    change, and whenever Dex Core changes what it publishes: a job renamed
    there turns this repository's Phase 4 into a dead end, and nothing else
    here would notice.
    """
    from capability_exchange.catalogue.fetch import (
        CONSENT_STATEMENT,
        DEFAULT_CATALOGUE_URL,
        CatalogueFetchConsent,
        CatalogueFetchStatus,
        ConsentedCatalogueFetcher,
    )
    from capability_exchange.catalogue.v2 import VerifiedCatalogueStore

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ConsentedCatalogueFetcher(store=VerifiedCatalogueStore(Path(tmp)))
        result = fetcher.fetch(
            CatalogueFetchConsent(
                catalogue_url=DEFAULT_CATALOGUE_URL,
                requested_at=datetime.now(UTC),
                statement=CONSENT_STATEMENT,
            )
        )

        if result.status is not CatalogueFetchStatus.VERIFIED:
            pytest.skip(f"live catalogue unavailable: {result.message}")

        assert result.verified is not None
        catalogue = result.verified.catalogue

    published_jobs = {job.job_id for job in catalogue.jobs_taxonomy}
    published_capabilities = {entry.capability_id for entry in catalogue.capabilities}
    assert published_jobs and published_capabilities

    unknown_jobs = sorted(_ids_after("--jobs") - published_jobs)
    assert not unknown_jobs, (
        f"SKILL.md tells the assistant to run `dex-lens catalogue --jobs` with "
        f"{unknown_jobs}, which the catalogue does not publish, so the command "
        f"refuses and the diagnosis stops. Published: {sorted(published_jobs)}"
    )

    unknown_capabilities = sorted(_ids_after("--only") - published_capabilities)
    assert not unknown_capabilities, (
        f"SKILL.md tells the assistant to run `dex-lens catalogue --only` with "
        f"{unknown_capabilities}, which the catalogue does not publish, so the "
        f"command refuses and the diagnosis stops"
    )
