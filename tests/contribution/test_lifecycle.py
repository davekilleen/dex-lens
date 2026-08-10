"""Contribution lifecycle and synthetic-store boundary (G4)."""

from __future__ import annotations

import pytest
from tests.cards.test_model import make_card

from capability_exchange.cards.disclosure import build_disclosure_manifest
from capability_exchange.contribution.consent import ConsentLedger, PermissionSet
from capability_exchange.contribution.lifecycle import (
    ContributionLifecycle,
    ContributionState,
    IllegalTransition,
    InMemoryStore,
)


def _setup() -> tuple[ContributionLifecycle, object]:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method", "selected_job"))
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
    return ContributionLifecycle(stores=stores, consent=ledger), (card, manifest)


def test_draft_submit_and_review_states_are_explicit() -> None:
    lifecycle, (card, manifest) = _setup()
    contribution = lifecycle.draft(card, manifest, contributor_secret=b"secret")
    assert contribution.state is ContributionState.DRAFT
    lifecycle.submit(contribution)
    assert contribution.state is ContributionState.SUBMITTED
    lifecycle.mark_reviewed(contribution)
    assert contribution.state is ContributionState.REVIEWED


def test_illegal_transition_is_rejected() -> None:
    lifecycle, (card, manifest) = _setup()
    contribution = lifecycle.draft(card, manifest, contributor_secret=b"secret")
    with pytest.raises(IllegalTransition):
        lifecycle.mark_reviewed(contribution)


def test_submission_with_unresolvable_permissions_withdraws() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    ledger = ConsentLedger()
    ledger.grant(
        card,
        manifest,
        PermissionSet(
            review=None,
            storage=True,
            moderation=True,
            attribution=True,
            reuse=True,
            distribution=True,
        ),
    )
    lifecycle = ContributionLifecycle(stores=[InMemoryStore("cache")], consent=ledger)
    contribution = lifecycle.draft(card, manifest, contributor_secret=b"secret")
    lifecycle.submit(contribution)
    assert contribution.state is ContributionState.WITHDRAWN
