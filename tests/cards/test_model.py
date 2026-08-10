"""Closed, inert Capability Card schema (M5/G4/R4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from capability_exchange.cards.model import (
    CapabilityCard,
    CardDependencies,
    CardPermissions,
    CardProvenance,
    CardRights,
    CardTestStatus,
)


def make_card(**overrides: object) -> CapabilityCard:
    payload: dict[str, object] = {
        "card_id": "weekly-review",
        "version": 1,
        "selected_job": "Prepare a weekly review from my approved notes",
        "method": "Collect the agreed inputs, compare them with the checklist, and draft a review.",
        "conditions": ("Inputs are already approved by the person",),
        "desired_outcome": "A concise review draft ready for the person to edit",
        "boundaries": ("Never send or publish the draft",),
        "evidence_claim": "The method produced a review draft in a local dry run",
        "permissions": CardPermissions(
            review=True,
            storage=True,
            moderation=True,
            attribution=False,
            reuse=False,
            distribution=False,
        ),
        "dependencies": CardDependencies(items=("approved-notes",)),
        "provenance": CardProvenance(
            method_basis="person-confirmed recipe",
            evidence_basis="local dry run",
            adapter_id="guided-local",
            evidence_mode="user-confirmed",
        ),
        "rights": CardRights(license_status="contributor-owned", rights_attested=True),
        "test_status": CardTestStatus(status="tested", summary="Local dry run passed"),
        "limitations": ("Does not verify external facts",),
    }
    payload.update(overrides)
    return CapabilityCard(**payload)


def test_card_is_closed_and_inert() -> None:
    card = make_card()
    assert card.card_id == "weekly-review"
    assert card.model_config["frozen"] is True
    assert "reviewed" not in type(card).model_fields
    assert "trust" not in type(card).model_fields
    assert "attachment" not in type(card).model_fields
    assert "raw_attachment" not in type(card).model_fields


def test_card_is_immutable() -> None:
    card = make_card()
    with pytest.raises(ValidationError):
        card.method = "changed"  # type: ignore[misc]


def test_unknown_self_trust_or_attachment_fields_are_rejected() -> None:
    for field in ("reviewed", "trust", "attachment", "raw_attachment"):
        with pytest.raises(ValidationError):
            make_card(**{field: True})


@pytest.mark.parametrize(
    "missing",
    [
        "permissions",
        "dependencies",
        "provenance",
        "rights",
        "test_status",
        "limitations",
    ],
)
def test_required_declarations_cannot_be_omitted(missing: str) -> None:
    payload = make_card().model_dump()
    payload.pop(missing)
    with pytest.raises(ValidationError):
        CapabilityCard(**payload)


def test_version_hash_changes_for_material_edit() -> None:
    first = make_card()
    changed = make_card(method="Use the approved checklist and draft a review.")
    assert first.version_hash != changed.version_hash
    assert first.version_hash == make_card().version_hash
