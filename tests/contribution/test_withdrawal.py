"""Immediate withdrawal propagation and honest shipped-release limit."""

from __future__ import annotations

import pytest
from tests.cards.test_model import make_card

from capability_exchange.cards.disclosure import build_disclosure_manifest
from capability_exchange.contribution.consent import ConsentError, ConsentLedger, PermissionSet
from capability_exchange.contribution.lifecycle import (
    ContributionLifecycle,
    ContributionState,
    IllegalTransition,
    InMemoryStore,
)


def test_withdrawal_propagates_to_every_controlled_store() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    ledger = ConsentLedger()
    ledger.grant(
        card,
        manifest,
        PermissionSet(
            review=True,
            storage=True,
            moderation=True,
            attribution=True,
            reuse=True,
            distribution=True,
        ),
    )
    stores = [
        InMemoryStore(name) for name in ("exchange-cards", "cache", "exports", "core-release")
    ]
    lifecycle = ContributionLifecycle(stores=stores, consent=ledger)
    contribution = lifecycle.draft(card, manifest, contributor_secret=b"secret")
    lifecycle.submit(contribution)
    lifecycle.withdraw(contribution, reason="person requested withdrawal")
    assert contribution.state is ContributionState.WITHDRAWN
    assert all(
        store.withdrawn_versions == {card.version_hash}
        for store in stores
        if store.name != "core-release"
    )
    shipped = next(store for store in stores if store.name == "core-release")
    assert shipped.non_recallable_versions == {card.version_hash}
    assert "cannot be recalled" in contribution.withdrawal_disclosure.lower()


def test_failed_propagation_quarantines_store_copy() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    ledger = ConsentLedger()
    ledger.grant(
        card,
        manifest,
        PermissionSet(
            review=True,
            storage=True,
            moderation=True,
            attribution=True,
            reuse=True,
            distribution=True,
        ),
    )
    broken = InMemoryStore("cache", fail_withdraw=True)
    lifecycle = ContributionLifecycle(stores=[broken], consent=ledger)
    contribution = lifecycle.draft(card, manifest, contributor_secret=b"secret")
    lifecycle.submit(contribution)
    lifecycle.withdraw(contribution, reason="person requested withdrawal")
    assert broken.quarantined_versions == {card.version_hash}


def test_withdrawal_does_not_delete_a_shipped_core_release() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    ledger = ConsentLedger()
    ledger.grant(
        card,
        manifest,
        PermissionSet(
            review=True,
            storage=True,
            moderation=True,
            attribution=True,
            reuse=True,
            distribution=True,
        ),
    )
    shipped = InMemoryStore("core-release")
    lifecycle = ContributionLifecycle(stores=[shipped], consent=ledger)
    contribution = lifecycle.draft(card, manifest, contributor_secret=b"secret")
    lifecycle.submit(contribution)
    lifecycle.withdraw(contribution, reason="person requested withdrawal")
    assert shipped.payloads[card.version_hash] == manifest.payload_bytes
    assert shipped.non_recallable_versions == {card.version_hash}
    with pytest.raises(ConsentError):
        lifecycle.draft(card, manifest, contributor_secret=b"secret")
    with pytest.raises(IllegalTransition, match="already withdrawn"):
        lifecycle.withdraw(contribution, reason="replayed request")


def test_shipped_core_store_cannot_be_made_recallable_by_configuration() -> None:
    with pytest.raises(ValueError, match="core-release"):
        InMemoryStore("core-release", recallable=True)
