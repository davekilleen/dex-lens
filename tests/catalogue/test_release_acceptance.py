from __future__ import annotations

import base64
import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import NOW, sign_envelope, unsigned_envelope

from capability_exchange.catalogue.release_acceptance import (
    CatalogueReleaseExpectation,
    CatalogueReleaseMismatch,
    assert_catalogue_release,
    load_catalogue_release_expectation,
)
from capability_exchange.catalogue.v2 import KeyRing, verify_catalogue_envelope


def _release(
    capability_ids: tuple[str, ...] = ("dex-durable-memory-provenance",),
) -> tuple[bytes, object, CatalogueReleaseExpectation]:
    signing_key = Ed25519PrivateKey.from_private_bytes(
        b"dex-lens-catalogue-v2-test-key!!"
    )
    public_key = signing_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    envelope = unsigned_envelope()
    template = envelope["catalogue"]["capabilities"][0]
    envelope["catalogue"]["capabilities"] = []
    for capability_id in capability_ids:
        capability = copy.deepcopy(template)
        capability["capability_id"] = capability_id
        capability["title"] = capability_id.replace("-", " ").title()
        envelope["catalogue"]["capabilities"].append(capability)
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
        capability_count=len(capability_ids),
        job_count=1,
        capability_ids=capability_ids,
    )


def test_exact_release_expectation_accepts_the_matching_signed_bytes() -> None:
    raw, verified, expected = _release()

    observed = assert_catalogue_release(raw, verified, expected)

    assert observed.raw_sha256 == expected.raw_sha256
    assert observed.core_release == expected.core_release
    assert observed.catalog_version == expected.catalog_version
    assert observed.capability_ids == expected.capability_ids
    assert observed.job_count == expected.job_count


def test_release_acceptance_preserves_complete_capability_order() -> None:
    raw, verified, expected = _release(
        ("dex-durable-memory-provenance", "second-capability")
    )

    assert assert_catalogue_release(raw, verified, expected).capability_ids == (
        "dex-durable-memory-provenance",
        "second-capability",
    )
    with pytest.raises(CatalogueReleaseMismatch, match="capability ids"):
        assert_catalogue_release(
            raw,
            verified,
            replace(expected, capability_ids=tuple(reversed(expected.capability_ids))),
        )


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


def test_checked_in_live_release_manifest_is_the_exact_complete_catalogue_identity() -> None:
    expected = load_catalogue_release_expectation(
        Path("docs/pilot/live-catalogue-release.json")
    )

    assert expected.core_release == "v1.97.1"
    assert expected.key_id == "dex-core-lens-1"
    assert expected.raw_sha256 == (
        "d2eb120fc4909c6a85fa24f11b24abdaa1d4ad2b364a9d396a261794ab3cbb82"
    )
    assert expected.catalog_version == 5
    assert expected.capability_count == 114
    assert expected.job_count == 8
    assert len(expected.capability_ids) == expected.capability_count


def test_release_manifest_refuses_unknown_or_missing_contract_fields(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "release.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "core_release": "v1.0.0",
                "key_id": "release-key",
                "raw_sha256": "0" * 64,
                "catalog_version": 1,
                "capability_count": 1,
                "job_count": 1,
                "capability_ids": ["one-capability"],
                "unexpected": "field",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest fields"):
        load_catalogue_release_expectation(manifest)


def test_release_manifest_refuses_duplicate_json_keys(tmp_path: Path) -> None:
    manifest = tmp_path / "release.json"
    source = Path("docs/pilot/live-catalogue-release.json").read_text(encoding="utf-8")
    manifest.write_text(
        source.replace(
            '"schema_version": 1,',
            '"schema_version": 1,\n  "schema_version": 1,',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate.*schema_version"):
        load_catalogue_release_expectation(manifest)


def test_release_manifest_refuses_boolean_schema_version(tmp_path: Path) -> None:
    manifest = tmp_path / "release.json"
    value = json.loads(
        Path("docs/pilot/live-catalogue-release.json").read_text(encoding="utf-8")
    )
    value["schema_version"] = True
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        load_catalogue_release_expectation(manifest)
