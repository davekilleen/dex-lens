from __future__ import annotations

import base64
import hashlib
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import NOW, sign_envelope, unsigned_envelope

from capability_exchange.catalogue.release_acceptance import (
    CatalogueReleaseExpectation,
    CatalogueReleaseMismatch,
    assert_catalogue_release,
)
from capability_exchange.catalogue.v2 import KeyRing, verify_catalogue_envelope


def _release() -> tuple[bytes, object, CatalogueReleaseExpectation]:
    signing_key = Ed25519PrivateKey.from_private_bytes(
        b"dex-lens-catalogue-v2-test-key!!"
    )
    public_key = signing_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    envelope = unsigned_envelope()
    raw = sign_envelope(envelope, signing_key).encode("utf-8")
    verified = verify_catalogue_envelope(
        raw.decode("utf-8"),
        keyring=KeyRing(
            {
                "dex-core-2026-08-test": base64.b64encode(public_key).decode(
                    "ascii"
                )
            }
        ),
        now=NOW,
    )
    return raw, verified, CatalogueReleaseExpectation(
        core_release="v1.94.0",
        key_id="dex-core-2026-08-test",
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        catalog_version=7,
        capability_count=1,
        job_count=1,
        capability_ids=("dex-durable-memory-provenance",),
    )


def test_exact_release_expectation_accepts_the_matching_signed_bytes() -> None:
    raw, verified, expected = _release()

    observed = assert_catalogue_release(raw, verified, expected)

    assert observed.raw_sha256 == expected.raw_sha256
    assert observed.core_release == expected.core_release
    assert observed.catalog_version == expected.catalog_version
    assert observed.capability_ids == expected.capability_ids
    assert observed.job_count == expected.job_count


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"raw_sha256": "0" * 64}, "sha256"),
        ({"core_release": "v9.9.9"}, "core release"),
        ({"key_id": "unexpected-key"}, "key id"),
        ({"catalog_version": 8}, "catalog version"),
        (
            {
                "capability_count": 2,
                "capability_ids": (
                    "dex-durable-memory-provenance",
                    "missing-capability",
                ),
            },
            "capability count",
        ),
        ({"job_count": 2}, "job count"),
        ({"capability_ids": ("different-capability",)}, "capability ids"),
    ),
)
def test_every_release_identity_mismatch_is_refused(
    change: dict[str, object],
    message: str,
) -> None:
    raw, verified, expected = _release()

    with pytest.raises(CatalogueReleaseMismatch, match=message):
        assert_catalogue_release(raw, verified, replace(expected, **change))


def test_expected_capability_count_must_describe_the_complete_id_set() -> None:
    _, _, expected = _release()

    with pytest.raises(ValueError, match="capability_count"):
        replace(expected, capability_count=2)


@pytest.mark.parametrize(
    "capability_ids",
    ((), ("duplicate-id", "duplicate-id")),
)
def test_expected_capability_ids_must_be_non_empty_and_unique(
    capability_ids: tuple[str, ...],
) -> None:
    _, _, expected = _release()

    with pytest.raises(ValueError, match="capability_ids"):
        replace(
            expected,
            capability_count=len(capability_ids),
            capability_ids=capability_ids,
        )
