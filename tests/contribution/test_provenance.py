"""Pseudonymous, version-bound provenance (G4/#356)."""

from __future__ import annotations

from capability_exchange.contribution.provenance import (
    build_provenance,
    pseudonymous_contributor_ref,
)


def test_reference_is_stable_but_version_bound() -> None:
    one = pseudonymous_contributor_ref(b"local-only-secret", "sha256:one")
    same = pseudonymous_contributor_ref(b"local-only-secret", "sha256:one")
    other_version = pseudonymous_contributor_ref(b"local-only-secret", "sha256:two")
    other_secret = pseudonymous_contributor_ref(b"other-secret", "sha256:one")
    assert one == same
    assert one != other_version
    assert one != other_secret
    assert "@" not in one and "/" not in one


def test_provenance_contains_no_identity_or_raw_material() -> None:
    provenance = build_provenance(
        local_secret=b"local-only-secret",
        card_version_hash="sha256:one",
        method_basis="person-confirmed recipe",
        evidence_basis="local dry run",
        adapter_id="guided-local",
        evidence_mode="user-confirmed",
        approved_fields=("method",),
    )
    assert provenance.contributor_ref
    assert provenance.card_version_hash == "sha256:one"
    assert "person@example.com" not in provenance.model_dump_json()
