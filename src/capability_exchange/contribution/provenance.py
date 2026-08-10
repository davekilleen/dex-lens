"""Version-bound pseudonymous provenance (#356/G4)."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import final

from pydantic import ConfigDict, field_validator

from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "ContributorReference",
    "VersionProvenance",
    "build_provenance",
    "pseudonymous_contributor_ref",
]

_HASH_RE = re.compile(r"^sha256:[A-Za-z0-9:_-]{1,256}$")


def pseudonymous_contributor_ref(local_secret: bytes, card_version_hash: str) -> str:
    """Derive a stable, version-bound reference without storing identity.

    ``local_secret`` is supplied by an account-free local adapter and is never
    included in the resulting reference or in a Card/provenance payload.
    """

    if not isinstance(local_secret, bytes) or not local_secret:
        raise ValueError("local_secret must be non-empty bytes held by the local adapter")
    if not _HASH_RE.match(card_version_hash):
        raise ValueError("card_version_hash must be a sha256 digest")
    digest = hmac.new(local_secret, card_version_hash.encode("ascii"), hashlib.sha256).hexdigest()
    return f"contributor-v1-{digest}"


@final
class VersionProvenance(InventoriedModel):
    """Non-raw provenance attached to one immutable Card version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contributor_ref: str
    card_version_hash: str
    method_basis: str
    evidence_basis: str
    adapter_id: str
    evidence_mode: str
    approved_fields: tuple[str, ...]

    @field_validator(
        "contributor_ref",
        "card_version_hash",
        "method_basis",
        "evidence_basis",
        "adapter_id",
        "evidence_mode",
    )
    @classmethod
    def _bounded_nonempty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise ValueError("provenance text must be bounded and non-empty")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("provenance text cannot contain control characters")
        return value

    @field_validator("approved_fields")
    @classmethod
    def _fields_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        result = tuple(value)
        if len(set(result)) != len(result):
            raise ValueError("approved_fields must be unique")
        return result


def build_provenance(
    *,
    local_secret: bytes,
    card_version_hash: str,
    method_basis: str,
    evidence_basis: str,
    adapter_id: str,
    evidence_mode: str,
    approved_fields: tuple[str, ...],
) -> VersionProvenance:
    return VersionProvenance(
        contributor_ref=pseudonymous_contributor_ref(local_secret, card_version_hash),
        card_version_hash=card_version_hash,
        method_basis=method_basis,
        evidence_basis=evidence_basis,
        adapter_id=adapter_id,
        evidence_mode=evidence_mode,
        approved_fields=approved_fields,
    )


ContributorReference = pseudonymous_contributor_ref
