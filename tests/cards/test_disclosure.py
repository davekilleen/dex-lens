"""Exact local disclosure manifest and canonical bytes (G2/G4)."""

from __future__ import annotations

import pytest

from capability_exchange.cards.disclosure import (
    DisclosureError,
    build_disclosure_manifest,
    canonical_card_bytes,
)

from .test_model import make_card


def test_no_fields_are_selected_by_default() -> None:
    with pytest.raises(DisclosureError):
        build_disclosure_manifest(make_card(), approved_fields=())


def test_manifest_shows_exact_fields_and_bytes() -> None:
    card = make_card()
    manifest = build_disclosure_manifest(card, approved_fields=("selected_job", "method"))
    assert manifest.approved_fields == ("selected_job", "method")
    assert manifest.payload_bytes == manifest.display_text.encode("utf-8")
    assert manifest.card_version_hash == card.version_hash
    assert manifest.byte_hash


def test_manifest_rejects_unmodelled_or_duplicate_fields() -> None:
    card = make_card()
    with pytest.raises(DisclosureError):
        build_disclosure_manifest(card, approved_fields=("method", "reviewed"))
    with pytest.raises(DisclosureError):
        build_disclosure_manifest(card, approved_fields=("method", "method"))


def test_canonical_bytes_are_stable_and_version_bound() -> None:
    first = make_card()
    same = make_card()
    changed = make_card(method="A changed recipe that remains bounded and inert.")
    assert canonical_card_bytes(first) == canonical_card_bytes(same)
    assert canonical_card_bytes(first) != canonical_card_bytes(changed)
