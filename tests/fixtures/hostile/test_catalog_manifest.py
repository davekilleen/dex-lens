"""The catalog is a versioned, machine-checkable corpus (R7 artifact).

Every declared fixture id has a builder; the version is semver; the leak
assertion is self-testing (it must actually catch canaries, substrings,
and sha256 derivations — an assertion that cannot fail proves nothing).
"""

from __future__ import annotations

import hashlib
import re

import pytest
from tests.fixtures.hostile import catalog

BUILDER_BY_FIXTURE_ID = {
    "symlink-and-hardlink-escapes": catalog.build_symlink_escape_system,
    "gitignored-planted-secret": catalog.build_gitignored_secret_system,
    "realistic-planted-credentials": catalog.build_credentialed_system,
    "prompt-injection-pair": catalog.build_injection_pair,
    "mutation-during-inspection": catalog.build_mutation_system,
    "oversized-system": catalog.build_oversized_system,
    "malformed-system": catalog.build_malformed_system,
    "partial-system": catalog.build_partial_system,
    "changing-system": catalog.build_changing_system,
    "external-model-request": catalog.build_model_request_system,
}


def test_g1_catalog_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", catalog.CATALOG_VERSION)


def test_g1_every_declared_fixture_has_a_builder() -> None:
    assert set(catalog.FIXTURE_IDS) == set(BUILDER_BY_FIXTURE_ID)
    for fixture_id in catalog.FIXTURE_IDS:
        assert callable(BUILDER_BY_FIXTURE_ID[fixture_id])


def test_g1_canaries_are_unique_and_distinctive() -> None:
    assert len(set(catalog.ALL_CANARIES)) == len(catalog.ALL_CANARIES)
    for canary in catalog.ALL_CANARIES:
        assert len(canary) >= 20, "short canaries produce weak leak assertions"


def test_g2_leak_assertion_catches_the_canary_itself() -> None:
    with pytest.raises(AssertionError, match="canary"):
        catalog.assert_no_canary_leak(f"prefix {catalog.CANARY_API_TOKEN} suffix")


def test_g2_leak_assertion_catches_a_substring() -> None:
    fragment = catalog.CANARY_AWS_SECRET[5:25]
    with pytest.raises(AssertionError, match="substring|derivation"):
        catalog.assert_no_canary_leak(f"partial leak: {fragment}")


def test_g2_leak_assertion_catches_sha256_derivations() -> None:
    digest = hashlib.sha256(catalog.CANARY_PERSONAL_STRING.encode()).hexdigest()
    with pytest.raises(AssertionError, match="derivation"):
        catalog.assert_no_canary_leak(f"hash on the wire: {digest}")
    with pytest.raises(AssertionError, match="derivation"):
        catalog.assert_no_canary_leak(f"truncated hash: {digest[:16]}")


def test_g2_leak_assertion_accepts_clean_output() -> None:
    catalog.assert_no_canary_leak('{"probe": "instructions-present", "state": "observed"}')
