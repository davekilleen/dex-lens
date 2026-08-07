"""G1 / #348 conformance-basic hostile fixtures: oversized, malformed,
partial, and changing systems.

None of these may crash the inspection into a useless state, silently drop
data, extrapolate incomplete collection to complete, or leak content —
every refusal is an honest, machine-readable exclusion record.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.fixtures.hostile.catalog import (
    build_benign_system,
    build_changing_system,
    build_malformed_system,
    build_oversized_system,
    build_partial_system,
)
from tests.fixtures.hostile.pipeline import collect_from, serialized, snapshot_of

from capability_exchange.adapter import InstrumentHealth
from capability_exchange.adapters.claude_code.collector import EvidenceCollector
from capability_exchange.adapters.claude_code.snapshot import (
    CollectionBounds,
    reference_token,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

SMALL_BOUNDS = CollectionBounds(max_file_bytes=4096, max_total_bytes=64 * 1024)

not_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="permission fixtures are meaningless as root"
)


class TestOversized:
    def test_g1_oversized_file_excluded_with_honest_record(self, tmp_path: Path) -> None:
        root = build_oversized_system(tmp_path, file_bytes=SMALL_BOUNDS.max_file_bytes)
        envelope = collect_from(root, bounds=SMALL_BOUNDS)
        exclusions = {p.probe_id: p for p in envelope.probes}["collection-exclusions"]
        references = [item.reference for item in exclusions.evidence]
        assert any(
            "read-bound-exceeded" in ref and "huge-transcript.md" in ref
            for ref in references
        )
        assert "A" * 64 not in serialized(envelope)

    def test_g1_file_count_bound_reports_incomplete_never_extrapolates(
        self, tmp_path: Path
    ) -> None:
        root = build_benign_system(tmp_path)
        envelope = collect_from(root, bounds=CollectionBounds(max_file_count=1))
        exclusions = {p.probe_id: p for p in envelope.probes}["collection-exclusions"]
        assert exclusions.health is InstrumentHealth.COULD_NOT_CHECK
        assert "incomplete" in exclusions.detail
        assert "never extrapolated" in exclusions.detail


class TestMalformed:
    def test_g1_malformed_content_never_crashes_or_leaks(self, tmp_path: Path) -> None:
        root = build_malformed_system(tmp_path)
        envelope = collect_from(root)
        payload = serialized(envelope)
        assert "invalid utf-8" not in payload
        assert "not json at all" not in payload
        # The malformed system still yields a valid, complete envelope.
        assert {p.probe_id for p in envelope.probes} == {
            "collection-exclusions",
            "installation-shape",
            "instructions-present",
            "settings-present",
            "skills-present",
        }

    def test_g1_control_character_names_cannot_break_the_envelope(
        self, tmp_path: Path
    ) -> None:
        # A directory and a file with a newline in the name: hostile names
        # must not be able to abort diagnosis by poisoning references.
        root = build_malformed_system(tmp_path)
        envelope = collect_from(root)
        payload = serialized(envelope)
        assert "\\nfile" not in payload and "evil\\ndir" not in payload, (
            "raw control-character file names leaked into references"
        )
        instructions = {p.probe_id: p for p in envelope.probes}["instructions-present"]
        # Both CLAUDE.md files (root and the control-char directory) are
        # evidenced; the hostile-named one via a hashed reference token.
        assert len(instructions.evidence) == 2

    def test_g1_control_character_oversized_name_excluded_honestly(
        self, tmp_path: Path
    ) -> None:
        root = build_benign_system(tmp_path)
        (root / "big\nname.bin").write_bytes(b"B" * (SMALL_BOUNDS.max_file_bytes + 1))
        envelope = collect_from(root, bounds=SMALL_BOUNDS)
        exclusions = {p.probe_id: p for p in envelope.probes}["collection-exclusions"]
        assert any(
            "read-bound-exceeded" in item.reference for item in exclusions.evidence
        )

    @pytest.mark.parametrize(
        "name",
        [
            "-----BEGIN",
            "-----BEGIN RSA PRIVATE KEY-----",
            "notes-----BEGIN-key.md",
        ],
    )
    def test_g1_key_marker_file_name_cannot_abort_the_inspection(self, name: str) -> None:
        """Adversarial M1 finding: a file *name* carrying a key-block marker
        must not be able to poison its own exclusion record.

        `reference_token` guards length, spaces and control characters, but
        not the `-----BEGIN` marker that `EvidenceItem` independently
        rejects — so a file named `-----BEGIN` produced a token that failed
        reference validation, raising mid-collection and aborting the whole
        inspection. Same availability weapon as the dangling symlink: one
        oddly-named file disables the deep adapter. Found by the property
        test below; pinned here deterministically.
        """
        token = reference_token(name)
        item = EvidenceItem(
            state=EvidenceState.BLOCKED,
            captured_at=datetime.now(UTC),
            reference=f"excluded:hostile-name:{token}",
        )
        assert item.reference.startswith("excluded:hostile-name:")

    @settings(max_examples=500, deadline=None)
    @given(name=st.text(min_size=1, max_size=255))
    def test_g1_any_relative_path_yields_a_valid_reference_token(
        self, name: str
    ) -> None:
        # Property: reference_token output is always embeddable in an R2
        # non-raw reference — whatever bytes a hostile file name carries.
        token = reference_token(name)
        item = EvidenceItem(
            state=EvidenceState.BLOCKED,
            captured_at=datetime.now(UTC),
            reference=f"excluded:hostile-name:{token}",
        )
        assert item.reference.startswith("excluded:hostile-name:")


class TestPartial:
    @not_root
    def test_g1_unreadable_directory_recorded_not_silent(self, tmp_path: Path) -> None:
        root, unreadable_dir, _unreadable_file = build_partial_system(tmp_path)
        unreadable_dir.chmod(0o000)
        try:
            envelope = collect_from(root)
        finally:
            unreadable_dir.chmod(0o755)
        exclusions = {p.probe_id: p for p in envelope.probes}["collection-exclusions"]
        references = [item.reference for item in exclusions.evidence]
        assert any("walk-error" in ref or "read-error" in ref for ref in references)
        assert "locked directory content" not in serialized(envelope)

    @not_root
    def test_g1_unreadable_file_recorded_not_silent(self, tmp_path: Path) -> None:
        root, _unreadable_dir, unreadable_file = build_partial_system(tmp_path)
        unreadable_file.chmod(0o000)
        try:
            envelope = collect_from(root)
        finally:
            unreadable_file.chmod(0o644)
        exclusions = {p.probe_id: p for p in envelope.probes}["collection-exclusions"]
        assert any(
            "read-error" in item.reference and "locked-file.md" in item.reference
            for item in exclusions.evidence
        )
        assert "locked file content" not in serialized(envelope)


class TestChangingSystem:
    def test_g1_files_added_after_consent_are_not_collected(self, tmp_path: Path) -> None:
        root, _target = build_changing_system(tmp_path)
        contract, snapshot = snapshot_of(root)
        (root / "appeared-later.md").write_text("appeared after consent\n")
        (root / "late-CLAUDE-dir").mkdir()
        (root / "late-CLAUDE-dir" / "CLAUDE.md").write_text("late instructions\n")
        envelope = EvidenceCollector(contract, snapshot).collect()
        payload = serialized(envelope)
        assert "appeared-later" not in payload
        assert "late-CLAUDE-dir" not in payload

    def test_g1_file_deleted_after_consent_degrades_to_conflicting(
        self, tmp_path: Path
    ) -> None:
        root, target = build_changing_system(tmp_path)
        contract, snapshot = snapshot_of(root)
        (root / "CLAUDE.md").unlink()
        envelope = EvidenceCollector(contract, snapshot).collect()
        instructions = {p.probe_id: p for p in envelope.probes}["instructions-present"]
        assert [item.state for item in instructions.evidence] == [
            EvidenceState.CONFLICTING
        ]
