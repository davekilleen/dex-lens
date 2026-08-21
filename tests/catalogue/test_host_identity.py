"""The identity Lens sends to the catalogue must be one the catalogue uses.

Two identifiers are easy to conflate, and conflating them is silent. The
adapter id names *this implementation* (``claude-code-local``: local,
folder-based, read-only). A catalogue entry's ``compatibility.host_adapters``
names the *host family* a capability can live in, which Dex Core publishes as
``claude-code``.

Production compared the implementation id against the host family, so every
entry in a catalogue that fully supports the person's host was reported as
"host adapter claude-code-local is not listed" — 55 times over, on a shelf
whose entire job is to say what would work for them. The unit tests missed it
because they passed the correct identity by hand, and the end-to-end test
missed it because its fixture had been edited to agree with the bug.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_exchange.adapters.claude_code.contract import (
    CLAUDE_CODE_ADAPTER_ID,
    CLAUDE_CODE_CATALOGUE_HOST_ADAPTER,
    claude_code_contract,
)
from capability_exchange.catalogue.fetch import (
    CONSENT_STATEMENT,
    DEFAULT_CATALOGUE_URL,
    CatalogueFetchConsent,
    CatalogueFetchStatus,
    ConsentedCatalogueFetcher,
)
from capability_exchange.catalogue.v2 import VerifiedCatalogueStore
from capability_exchange.concierge.journey import PermissionMetadata

live_only = pytest.mark.skipif(
    os.environ.get("DEX_LENS_LIVE_CATALOGUE") != "1",
    reason="live catalogue check is opt-in: set DEX_LENS_LIVE_CATALOGUE=1",
)


def _production_permission() -> PermissionMetadata:
    """Built the way the concierge session builds it, not by hand."""
    return PermissionMetadata.from_contract(
        claude_code_contract(("/tmp/approved-root",)),
        catalogue_host_adapter=CLAUDE_CODE_CATALOGUE_HOST_ADAPTER,
    )


def test_the_two_identifiers_are_distinct_and_both_declared() -> None:
    assert CLAUDE_CODE_CATALOGUE_HOST_ADAPTER != CLAUDE_CODE_ADAPTER_ID
    assert CLAUDE_CODE_CATALOGUE_HOST_ADAPTER == "claude-code"


def test_the_session_sends_the_host_family_not_the_adapter_id() -> None:
    """What the shelf compares must be the catalogue's vocabulary."""
    assert _production_permission().catalogue_host == CLAUDE_CODE_CATALOGUE_HOST_ADAPTER


def test_an_adapter_without_a_declared_host_family_falls_back_to_its_id() -> None:
    """The fallback stays, for an adapter whose two identities coincide."""
    permission = PermissionMetadata.from_contract(claude_code_contract(("/tmp/approved-root",)))

    assert permission.catalogue_host == CLAUDE_CODE_ADAPTER_ID


@live_only
def test_live_catalogue_lists_the_host_family_lens_sends() -> None:
    """Catch drift between this repo and the catalogue Dex Core publishes.

    Opt-in because it reaches the network. Run it when either side changes
    its host-adapter vocabulary; a rename in Core would otherwise surface
    only as every capability quietly reporting the person's host as
    unsupported.
    """
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
        capabilities = result.verified.catalogue.capabilities
        assert capabilities, "a verified catalogue with no capabilities proves nothing"

        sent = _production_permission().catalogue_host
        unlisted = [
            entry.capability_id
            for entry in capabilities
            if sent not in entry.compatibility.host_adapters
        ]
        assert not unlisted, (
            f"the live catalogue does not list {sent!r} for {len(unlisted)} of "
            f"{len(capabilities)} capabilities, so the shelf would report the "
            f"person's host as unsupported: {unlisted[:5]}"
        )
