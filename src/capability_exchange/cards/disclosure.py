"""Exact local disclosure manifests for Capability Card versions (G2/G4)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, final

from pydantic import ConfigDict, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.cards.model import CapabilityCard
from capability_exchange.cards.validation import (
    CardValidationError,
    require_valid_card,
    scan_text,
)

__all__ = [
    "DisclosureError",
    "DisclosureManifest",
    "build_disclosure_manifest",
    "canonical_card_bytes",
]


class DisclosureError(ValueError):
    """The exact outbound disclosure cannot be constructed safely."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def canonical_card_bytes(card: CapabilityCard) -> bytes:
    """Canonical bytes for a complete immutable Card version."""

    require_valid_card(card)
    return _canonical_json(card.model_dump(mode="json"))


@final
class DisclosureManifest(InventoriedModel):
    """The exact fields and bytes a person approved for one Card version.

    ``display_text`` is the UTF-8 representation of the bytes that leave via
    the contribution port.  The property ``payload_bytes`` deliberately is
    not an independent persisted field, avoiding two representations that
    could drift.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_version_hash: str
    approved_fields: tuple[str, ...]
    byte_hash: str
    display_text: str

    @field_validator("approved_fields")
    @classmethod
    def _validate_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        fields = tuple(value)
        if not fields:
            raise ValueError("disclosure must select at least one Card field")
        if len(set(fields)) != len(fields):
            raise ValueError("approved disclosure fields must be unique")
        unknown = set(fields) - set(CapabilityCard.model_fields)
        if unknown:
            raise ValueError("approved disclosure contains an unknown Card field")
        return fields

    @model_validator(mode="after")
    def _validate_payload(self) -> DisclosureManifest:
        try:
            parsed = json.loads(self.display_text)
        except (TypeError, ValueError) as exc:
            raise ValueError("disclosure payload must be canonical JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("disclosure payload must be a JSON object")
        issues = scan_text(parsed, path="disclosure")
        if issues:
            reasons = ", ".join(dict.fromkeys(issue.reason.value for issue in issues))
            raise ValueError(f"disclosure payload rejected: {reasons}")
        if self.byte_hash != _sha256(self.payload_bytes):
            raise ValueError("disclosure bytes do not match their manifest hash")
        return self

    @property
    def payload_bytes(self) -> bytes:
        return self.display_text.encode("utf-8")

    @property
    def fields(self) -> tuple[str, ...]:
        return self.approved_fields

    @property
    def bytes(self) -> bytes:
        return self.payload_bytes

    @property
    def approved_bytes(self) -> bytes:
        return self.payload_bytes

    def outbound_bytes(self, *, consented: bool) -> bytes:
        """Return bytes only after the caller proves fresh explicit consent."""

        if not consented:
            raise DisclosureError("outbound bytes require explicit version-bound consent")
        if self.byte_hash != _sha256(self.payload_bytes):
            raise DisclosureError("disclosure bytes no longer match their manifest hash")
        return self.payload_bytes

    def verify_card(self, card: CapabilityCard) -> bool:
        try:
            require_valid_card(card)
            if self.card_version_hash != card.version_hash:
                return False
            if self.byte_hash != _sha256(self.payload_bytes):
                return False
            expected = build_disclosure_manifest(card, approved_fields=self.approved_fields)
        except (CardValidationError, DisclosureError):
            return False
        return expected.display_text == self.display_text and expected.byte_hash == self.byte_hash


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def build_disclosure_manifest(
    card: CapabilityCard, *, approved_fields: tuple[str, ...] | list[str]
) -> DisclosureManifest:
    """Build an exact manifest after explicit field selection.

    No fields are selected implicitly.  The manifest payload is a canonical
    JSON object containing only the selected top-level Card fields.
    """

    try:
        require_valid_card(card)
    except CardValidationError as exc:
        raise DisclosureError(f"Card validation failed: {', '.join(exc.reason_codes)}") from exc

    fields = tuple(approved_fields)
    if not fields:
        raise DisclosureError("no fields selected; contribution disclosure is opt-in per field")
    if len(set(fields)) != len(fields):
        raise DisclosureError("approved disclosure fields must be unique")
    unknown = set(fields) - set(card.declared_fields)
    if unknown:
        raise DisclosureError("approved disclosure contains fields not declared by the Card schema")
    payload = card.model_dump(mode="json")
    selected = {field: payload[field] for field in fields}
    display_text = _canonical_json(selected).decode("utf-8")
    return DisclosureManifest(
        card_version_hash=card.version_hash,
        approved_fields=fields,
        byte_hash=_sha256(display_text.encode("utf-8")),
        display_text=display_text,
    )
