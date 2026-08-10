"""Signed Capability Catalog verification and fail-closed fallback (R4)."""

from __future__ import annotations

from capability_exchange.catalog.verify import (
    CatalogEntry,
    CatalogStatus,
    CatalogVerifier,
    SignedCatalog,
    verify_catalog,
)


class Verifier:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid

    def verify(self, payload: bytes, signature: str, key_id: str) -> bool:
        return self.valid and signature == "sig" and key_id == "core-1"


def signed(*, signature: str = "sig", release_provenance: str = "core-release") -> SignedCatalog:
    return SignedCatalog.from_entries(
        entries=(
            CatalogEntry(
                card_id="weekly-review",
                version_hash="sha256:one",
                core_release="1.0.0",
                release_provenance=release_provenance,
            ),
        ),
        signature=signature,
        key_id="core-1",
    )


def test_valid_signature_is_required_before_catalog_use() -> None:
    result = verify_catalog(signed(), Verifier())
    assert result.status is CatalogStatus.VERIFIED
    assert result.catalog is not None


def test_tampered_or_unsigned_catalog_falls_back_to_last_verified_or_none() -> None:
    consumer = CatalogVerifier(Verifier())
    first = consumer.verify(signed())
    tampered = consumer.verify(signed(signature="bad"))
    assert tampered.status is CatalogStatus.LAST_VERIFIED
    assert tampered.catalog == first.catalog
    none = verify_catalog(signed(signature="bad"), Verifier())
    assert none.status is CatalogStatus.NONE
    assert none.catalog is None


def test_non_release_artifacts_are_rejected() -> None:
    result = verify_catalog(signed(release_provenance="experimental"), Verifier())
    assert result.status is CatalogStatus.NONE


def test_bypass_constructed_catalog_envelope_fails_closed_instead_of_crashing() -> None:
    malformed = SignedCatalog.model_construct(payload="{}", signature=None, key_id="core-1")
    result = verify_catalog(malformed, Verifier())
    assert result.status is CatalogStatus.NONE
    assert result.catalog is None
