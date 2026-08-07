"""G1 hostile fixtures 3–4 (gates.md): planted secrets and credentials.

A ``.gitignore``\\ d planted secret must still be inspected (skipping it
would miss it) and redacted at collection; realistic credentials must
surface only as redacted references — raw secret bytes never enter the
snapshot, the envelope, or any exclusion record.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fixtures.hostile.catalog import (
    CANARY_API_TOKEN,
    CANARY_AWS_KEY_ID,
    CANARY_AWS_SECRET,
    CANARY_GITIGNORED_SECRET,
    CANARY_PRIVATE_KEY_BODY,
    assert_no_canary_leak,
    build_credentialed_system,
    build_gitignored_secret_system,
)
from tests.fixtures.hostile.pipeline import collect_from, serialized, snapshot_of

from capability_exchange.adapters.claude_code.secrets import REDACTION_MARK
from capability_exchange.evidence import EvidenceState


class TestGitignoredSecret:
    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        return build_gitignored_secret_system(tmp_path)

    def test_g1_gitignored_file_is_still_inspected(self, root: Path) -> None:
        _contract, snapshot = snapshot_of(root)
        captured = snapshot.canonical_paths()
        assert any(path.endswith("secrets.env") for path in captured), (
            "gitignored files are inspected under the same allowlist — "
            "skipping them would miss planted secrets"
        )

    def test_g1_gitignored_secret_redacted_at_collection(self, root: Path) -> None:
        _contract, snapshot = snapshot_of(root)
        entry_path = next(
            path for path in snapshot.canonical_paths() if path.endswith("secrets.env")
        )
        content = snapshot.content_of(entry_path)
        assert REDACTION_MARK in content
        assert_no_canary_leak(
            content, [CANARY_GITIGNORED_SECRET], context="snapshot content"
        )

    def test_g1_gitignored_secret_never_in_envelope(self, root: Path) -> None:
        assert_no_canary_leak(
            serialized(collect_from(root)),
            [CANARY_GITIGNORED_SECRET],
            context="serialized envelope",
        )


class TestRealisticCredentials:
    CREDENTIAL_CANARIES = (
        CANARY_AWS_KEY_ID,
        CANARY_AWS_SECRET,
        CANARY_API_TOKEN,
        CANARY_PRIVATE_KEY_BODY,
    )

    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        return build_credentialed_system(tmp_path)

    def test_g1_credentials_surface_only_as_redacted_references(self, root: Path) -> None:
        envelope = collect_from(root)
        payload = serialized(envelope)
        assert_no_canary_leak(
            payload, self.CREDENTIAL_CANARIES, context="serialized envelope"
        )
        # The credential-bearing CLAUDE.md is still evidenced — as a
        # non-raw reference, not as content.
        instructions = {p.probe_id: p for p in envelope.probes}["instructions-present"]
        assert instructions.evidence[0].state is EvidenceState.OBSERVED
        assert instructions.evidence[0].reference.startswith("file:CLAUDE.md")

    def test_g1_raw_credential_bytes_never_enter_the_snapshot(self, root: Path) -> None:
        _contract, snapshot = snapshot_of(root)
        for path in snapshot.canonical_paths():
            assert_no_canary_leak(
                snapshot.content_of(path),
                self.CREDENTIAL_CANARIES,
                context=f"snapshot content ({Path(path).name})",
            )

    def test_g1_credential_files_carry_redaction_marks(self, root: Path) -> None:
        _contract, snapshot = snapshot_of(root)
        deploy = next(
            path for path in snapshot.canonical_paths() if path.endswith("deploy.env")
        )
        instructions = next(
            path for path in snapshot.canonical_paths() if path.endswith("CLAUDE.md")
        )
        assert snapshot.content_of(deploy).count(REDACTION_MARK) >= 3
        assert REDACTION_MARK in snapshot.content_of(instructions)
