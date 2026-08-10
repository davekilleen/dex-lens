"""Per-version, per-permission consent (G4)."""

from __future__ import annotations

import pytest
from tests.cards.test_model import make_card

from capability_exchange.cards.disclosure import build_disclosure_manifest
from capability_exchange.contribution.consent import (
    ConsentError,
    ConsentLedger,
    Permission,
    PermissionSet,
)


def test_six_permissions_are_separately_grantable() -> None:
    permissions = PermissionSet(
        review=True,
        storage=False,
        moderation=True,
        attribution=False,
        reuse=False,
        distribution=False,
    )
    assert permissions.granted == frozenset({Permission.REVIEW, Permission.MODERATION})
    assert not permissions.all_granted


def test_consent_binds_to_one_immutable_version_and_manifest() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("method",))
    ledger = ConsentLedger()
    record = ledger.grant(
        card,
        manifest,
        PermissionSet(
            review=True,
            storage=True,
            moderation=True,
            attribution=False,
            reuse=False,
            distribution=False,
        ),
    )
    assert record.card_version_hash == card.version_hash
    assert ledger.is_current(card, manifest)
    changed = make_card(method="A different method with the same job boundary.")
    assert not ledger.is_current(changed, manifest)
    with pytest.raises(ConsentError):
        ledger.require(changed, manifest)


def test_manifest_selection_change_requires_fresh_consent() -> None:
    card = make_card()
    first = build_disclosure_manifest(card, approved_fields=("method",))
    second = build_disclosure_manifest(card, approved_fields=("method", "limitations"))
    ledger = ConsentLedger()
    ledger.grant(
        card,
        first,
        PermissionSet(
            review=True,
            storage=True,
            moderation=True,
            attribution=False,
            reuse=False,
            distribution=False,
        ),
    )
    assert not ledger.is_current(card, second)


def test_unresolvable_permission_state_is_withdrawn() -> None:
    permissions = PermissionSet(
        review=None, storage=True, moderation=True, attribution=True, reuse=True, distribution=True
    )
    assert permissions.is_unresolvable
    assert permissions.fully_withdrawn
