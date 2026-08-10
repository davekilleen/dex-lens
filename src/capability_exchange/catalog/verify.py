"""Signed Capability Catalog verification with fail-closed fallback (R4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, final

from pydantic import ConfigDict, Field, ValidationError

from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "CapabilityCatalog",
    "CatalogEntry",
    "CatalogResult",
    "CatalogStatus",
    "SignedCatalog",
    "verify_catalog",
    "CatalogVerifier",
]


class SignatureVerifier(Protocol):
    def verify(self, payload: bytes, signature: str, key_id: str) -> bool: ...


class CatalogStatus(StrEnum):
    VERIFIED = "verified"
    LAST_VERIFIED = "last-verified"
    NONE = "none"


@final
class CatalogEntry(InventoriedModel):
    """One entry sourced from an actual released Core artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str
    version_hash: str
    core_release: str
    release_provenance: str


@final
class CapabilityCatalog(InventoriedModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[CatalogEntry, ...] = Field(default_factory=tuple)


@final
class SignedCatalog(InventoriedModel):
    """Opaque signed payload; consumers must verify before parsing/using it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload: str
    signature: str
    key_id: str

    @property
    def payload_bytes(self) -> bytes:
        return self.payload.encode("utf-8")

    @classmethod
    def from_entries(
        cls, *, entries: tuple[CatalogEntry, ...], signature: str, key_id: str
    ) -> SignedCatalog:
        values = [entry.model_dump(mode="json") for entry in entries]
        payload = json.dumps(
            {"entries": values}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return cls(payload=payload, signature=signature, key_id=key_id)


@dataclass(frozen=True, slots=True)
class CatalogResult:
    status: CatalogStatus
    catalog: CapabilityCatalog | None
    message: str


def _none_or_last(last_verified: CapabilityCatalog | None, reason: str) -> CatalogResult:
    if last_verified is not None:
        return CatalogResult(
            status=CatalogStatus.LAST_VERIFIED,
            catalog=last_verified,
            message=f"catalog rejected ({reason}); using last verified catalog",
        )
    return CatalogResult(
        status=CatalogStatus.NONE,
        catalog=None,
        message=f"catalog rejected ({reason}); no verified catalog is available",
    )


def verify_catalog(
    signed: SignedCatalog,
    verifier: SignatureVerifier,
    *,
    last_verified: CapabilityCatalog | None = None,
) -> CatalogResult:
    """Verify signature and release provenance before catalog use.

    Unsigned/tampered/experimental payloads are rejected as a whole.  The
    product uses a previously verified catalog when supplied, otherwise runs
    explicitly with ``none``; no unverified entry is exposed.
    """

    if not signed.signature.strip():
        return _none_or_last(last_verified, "unsigned payload")
    try:
        if callable(verifier):
            valid = bool(verifier(signed.payload_bytes, signed.signature, signed.key_id))
        else:
            valid = bool(verifier.verify(signed.payload_bytes, signed.signature, signed.key_id))
    except Exception:  # noqa: BLE001 - verifier failures are signature failures
        valid = False
    if not valid:
        return _none_or_last(last_verified, "signature verification failed")
    try:
        raw = json.loads(signed.payload)
        entries_raw = raw["entries"]
        if not isinstance(entries_raw, list):
            raise ValueError("entries must be a list")
        entries = tuple(CatalogEntry.model_validate(entry) for entry in entries_raw)
        if any(entry.release_provenance != "core-release" for entry in entries):
            raise ValueError("catalog contains a non-release artifact")
        catalog = CapabilityCatalog(entries=entries)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, ValidationError) as exc:
        return _none_or_last(last_verified, f"catalog payload invalid: {type(exc).__name__}")
    return CatalogResult(
        status=CatalogStatus.VERIFIED,
        catalog=catalog,
        message="signature verified; catalog contains released Core artifacts only",
    )


class CatalogVerifier:
    """Stateful local consumer retaining only the last verified catalog."""

    def __init__(self, verifier: SignatureVerifier) -> None:
        self.verifier = verifier
        self.last_verified: CapabilityCatalog | None = None

    def verify(self, signed: SignedCatalog) -> CatalogResult:
        result = verify_catalog(
            signed,
            self.verifier,
            last_verified=self.last_verified,
        )
        if result.status is CatalogStatus.VERIFIED:
            self.last_verified = result.catalog
        return result
