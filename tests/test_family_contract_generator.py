"""The significant-family contract draft is derived, deterministic and unsigned.

The draft is the payload the founder reviews, resolves and signs through the
Dex Core release pipeline. It is generated only from the signature-verified
source catalogue plus the approved coverage-gate plan's family definitions;
membership judgment is surfaced as explicit founder TODOs, never silently
invented. Nothing here signs anything: the committed draft must carry no
signature and must say it is unsigned.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from capability_exchange.catalogue.v2 import (
    CatalogueV2,
    default_keyring,
    verify_catalogue_envelope_for_stale_display,
)
from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GENERATOR = _REPO_ROOT / "scripts" / "generate_family_contract.py"
_DRAFT_PATH = _REPO_ROOT / "release" / "significant-family-contract.draft.json"
_REFERENCE_PATH = (
    _REPO_ROOT
    / "src"
    / "capability_exchange"
    / "skill"
    / "dex-lens"
    / "dex-capabilities.json"
)


@pytest.fixture(scope="module")
def draft() -> dict:
    assert _DRAFT_PATH.is_file(), "committed significant-family contract draft is missing"
    with _DRAFT_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def verified_source():
    reference = json.loads(_REFERENCE_PATH.read_text(encoding="utf-8"))
    raw = json.dumps(
        reference["signed_catalogue"], sort_keys=True, separators=(",", ":")
    )
    return verify_catalogue_envelope_for_stale_display(raw, keyring=default_keyring())


def test_generator_script_exists() -> None:
    assert _GENERATOR.is_file()


def test_draft_top_level_shape_is_unsigned(draft: dict) -> None:
    assert set(draft) == {
        "capability_families",
        "derivation_notes",
        "derived_from",
        "draft_contract",
        "draft_version",
        "founder_review",
        "status",
    }
    assert draft["draft_contract"] == "dex-lens-significant-family-contract-draft"
    assert draft["draft_version"] == 1
    assert "unsigned" in draft["status"]
    assert "signature" not in json.dumps(sorted(draft)).lower()


def test_draft_families_cover_exactly_the_wow_expectation_manifest(draft: dict) -> None:
    family_ids = [item["family_id"] for item in draft["capability_families"]]
    assert family_ids == list(WOW_EXPECTATIONS)


def test_draft_families_validate_against_the_verified_source_catalogue(
    draft: dict, verified_source
) -> None:
    """The exact drafted payload closes against the real signed catalogue.

    This is the same model validation the Lens verifier applies to signed
    bytes, so a payload that passes here becomes a family contract the moment
    the founder signs a catalogue carrying it — flipping
    ``family_contract_present`` on.
    """

    catalogue_payload = verified_source.catalogue.model_dump(mode="json")
    catalogue_payload["capability_families"] = draft["capability_families"]

    combined = CatalogueV2.model_validate(catalogue_payload)

    assert len(combined.capability_families) == len(WOW_EXPECTATIONS)
    assert bool(combined.capability_families) is True


def test_derived_from_pins_the_exact_source_catalogue(
    draft: dict, verified_source
) -> None:
    reference = json.loads(_REFERENCE_PATH.read_text(encoding="utf-8"))
    canonical = json.dumps(
        reference["signed_catalogue"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    derived = draft["derived_from"]
    assert derived["canonical_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert derived["catalog_version"] == verified_source.metadata.catalog_version
    assert derived["core_release"] == verified_source.metadata.core_release
    assert derived["key_id"] == verified_source.metadata.key_id


def test_draft_members_and_components_cite_only_signed_capabilities(
    draft: dict, verified_source
) -> None:
    signed_ids = {
        item.capability_id for item in verified_source.catalogue.capabilities
    }
    for family in draft["capability_families"]:
        members = family["member_capability_ids"]
        assert members, family["family_id"]
        assert set(members) <= signed_ids
        component_ids = [
            component["capability_id"] for component in family["components"]
        ]
        assert component_ids == list(members)


def test_every_family_carries_founder_review_todos(draft: dict) -> None:
    reviewed = {item["family_id"] for item in draft["founder_review"]}
    assert reviewed == set(WOW_EXPECTATIONS)
    for item in draft["founder_review"]:
        assert item["todos"], item["family_id"]
        assert all(todo.startswith("TODO(founder):") for todo in item["todos"])
        assert item["member_basis"], item["family_id"]


def test_generator_output_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    for output in (first, second):
        completed = subprocess.run(  # noqa: S603 - fixed local script and argv
            [sys.executable, str(_GENERATOR), "--output", str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() == _DRAFT_PATH.read_bytes()


def test_generator_check_passes_on_the_committed_draft() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed local script and argv
        [sys.executable, str(_GENERATOR), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_generator_check_fails_on_a_drifted_draft(tmp_path: Path) -> None:
    drifted = tmp_path / "drifted.json"
    payload = json.loads(_DRAFT_PATH.read_text(encoding="utf-8"))
    payload["capability_families"][0]["outcome"] = "An edited outcome nobody reviewed."
    drifted.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - fixed local script and argv
        [sys.executable, str(_GENERATOR), "--check", "--output", str(drifted)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert "drifted" in completed.stderr


def test_test_signed_draft_contract_turns_the_dimension_on(
    tmp_path: Path, draft: dict, verified_source
) -> None:
    """Signing the drafted payload flips the flag through the real loader.

    The signing key here is invented for this test only; the founder's real
    signing act is the one remaining step and never happens in this repo.
    """

    import base64
    from datetime import UTC, datetime

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from capability_exchange.catalogue.v2 import (
        KeyRing,
        VerifiedCatalogueStore,
        canonical_signed_payload,
        verify_catalogue_envelope,
    )
    from capability_exchange.diagnosis.defaults import CachedCatalogueLoader
    from capability_exchange.diagnosis.expectations import assess_wow_expectations
    from capability_exchange.diagnosis.observations import EvidenceFingerprint
    from capability_exchange.diagnosis.significant_families import (
        assess_significant_families,
    )

    catalogue_payload = verified_source.catalogue.model_dump(mode="json")
    catalogue_payload["capability_families"] = draft["capability_families"]
    metadata = verified_source.metadata.model_dump(mode="json")
    metadata["key_id"] = "invented-draft-test-key-1"
    metadata["catalog_version"] = int(metadata["catalog_version"]) + 1
    metadata["expires_at"] = "2036-01-01T00:00:00Z"
    envelope = {"metadata": metadata, "catalogue": catalogue_payload}
    signing_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    raw = json.dumps(
        {
            **envelope,
            "signature": base64.b64encode(
                signing_key.sign(canonical_signed_payload(envelope))
            ).decode("ascii"),
        },
        sort_keys=True,
    )
    keyring = KeyRing(
        {
            "invented-draft-test-key-1": base64.b64encode(
                signing_key.public_key().public_bytes_raw()
            ).decode("ascii")
        }
    )
    store = VerifiedCatalogueStore(tmp_path / "catalogue")
    store.save_verified(verify_catalogue_envelope(raw, keyring=keyring))

    loaded = CachedCatalogueLoader(store, keyring=keyring).load(
        run_id="run:" + "a" * 16,
        fingerprint_digest="sha256:" + "b" * 64,
    )
    assert loaded.family_contract_present is True

    combined = CatalogueV2.model_validate(catalogue_payload)
    fingerprint = EvidenceFingerprint(
        adapter_id="invented-empty-adapter",
        collected_at=datetime(2026, 9, 3, tzinfo=UTC),
        observations=(),
    )
    rows = assess_wow_expectations(
        combined, assess_significant_families(combined, fingerprint)
    )
    assert [row.family_id for row in rows] == list(WOW_EXPECTATIONS)


def test_generator_refuses_an_unverifiable_source(tmp_path: Path) -> None:
    reference = json.loads(_REFERENCE_PATH.read_text(encoding="utf-8"))
    envelope = reference["signed_catalogue"]
    envelope["metadata"]["core_release"] = "v0.0.0-tampered"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(envelope), encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - fixed local script and argv
        [
            sys.executable,
            str(_GENERATOR),
            "--input",
            str(tampered),
            "--output",
            str(tmp_path / "never-written.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert "refused" in completed.stderr
    assert not (tmp_path / "never-written.json").exists()
