"""Immediate withdrawal propagation and honest shipped-release limit."""

from __future__ import annotations

from tests.cards.test_model import make_card

from capability_exchange.cards.disclosure import build_disclosure_manifest
from capability_exchange.contribution.consent import ConsentLedger, PermissionSet
from capability_exchange.contribution.lifecycle import (
    ContributionLifecycle,
    ContributionState,
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
    assert all(store.withdrawn_versions == {card.version_hash} for store in stores)
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
