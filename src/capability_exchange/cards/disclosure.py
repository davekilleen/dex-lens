"""Exact local disclosure manifests for Capability Card versions (G2/G4)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, final

from pydantic import ConfigDict

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.cards.model import CapabilityCard

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
        if self.card_version_hash != card.version_hash:
            return False
        if self.byte_hash != _sha256(self.payload_bytes):
            return False
        try:
            expected = build_disclosure_manifest(card, approved_fields=self.approved_fields)
        except DisclosureError:
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
