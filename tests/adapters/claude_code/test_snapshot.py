"""Immutable inspection snapshot (G1 item c): snapshot reads only, digest
change detection, bounded collection, ambiguity aborts and discards."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.adapters.claude_code.fixture_helpers import (
    PLANTED_AWS_KEY_ID,
    PLANTED_SECRET_VALUE,
)

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.snapshot import (
    CollectionBounds,
    InspectionAbortedError,
    SnapshotMissError,
    take_snapshot,
)
from capability_exchange.evidence import EvidenceState


def snapshot_of(root: Path, **kwargs):  # type: ignore[no-untyped-def]
    return take_snapshot(CanonicalAllowlist([root]), **kwargs)


class TestSnapshotReads:
    def test_reads_come_from_snapshot_not_live_disk(self, claude_root: Path) -> None:
        snapshot = snapshot_of(claude_root)
        canonical = str((claude_root / "CLAUDE.md").resolve())
        original = snapshot.content_of(canonical)
        (claude_root / "CLAUDE.md").write_text("MUTATED AFTER SNAPSHOT\n")
        assert snapshot.content_of(canonical) == original
        assert b"MUTATED" not in snapshot.content_of(canonical)

    def test_deleted_file_still_readable_from_snapshot(self, claude_root: Path) -> None:
        snapshot = snapshot_of(claude_root)
        canonical = str((claude_root / "notes.md").resolve())
        (claude_root / "notes.md").unlink()
        assert snapshot.content_of(canonical) == b"Weekly review notes.\n"

    def test_unsnapshotted_path_refused_never_disk_fallback(self, claude_root: Path) -> None:
        snapshot = snapshot_of(claude_root)
        (claude_root / "late-arrival.md").write_text("added after snapshot")
        with pytest.raises(SnapshotMissError, match="never|snapshot"):
            snapshot.content_of(str((claude_root / "late-arrival.md").resolve()))

    def test_snapshot_paths_are_canonical_and_sorted(self, claude_root: Path) -> None:
        snapshot = snapshot_of(claude_root)
        paths = snapshot.canonical_paths()
        assert paths == tuple(sorted(paths))
        assert all(os.path.isabs(path) for path in paths)


class TestSecretHandlingAtCollection:
    def test_raw_secret_bytes_never_stored(self, secret_bearing_root: Path) -> None:
        snapshot = snapshot_of(secret_bearing_root)
        for canonical in snapshot.canonical_paths():
            entry = snapshot.entry_for(canonical)
            assert PLANTED_AWS_KEY_ID.encode() not in entry.content
            assert PLANTED_SECRET_VALUE.encode() not in entry.content
            assert b"PRIVATE KEY" not in entry.content

    def test_redaction_reference_survives(self, secret_bearing_root: Path) -> None:
        snapshot = snapshot_of(secret_bearing_root)
        canonical = str((secret_bearing_root / ".claude" / "secrets.env").resolve())
        entry = snapshot.entry_for(canonical)
        assert entry.redaction_count >= 3
        assert entry.content.count(b"[REDACTED-SECRET]") == entry.redaction_count


class TestChangeDetection:
    def test_unchanged_tree_reports_no_changes(self, claude_root: Path) -> None:
        assert snapshot_of(claude_root).changed_paths_since_capture() == frozenset()

    def test_mid_inspection_edit_detected_by_digest(self, claude_root: Path) -> None:
        snapshot = snapshot_of(claude_root)
        target = claude_root / "CLAUDE.md"
        target.write_text("changed mid-inspection\n")
        changed = snapshot.changed_paths_since_capture()
        assert str(target.resolve()) in changed

    def test_mid_inspection_deletion_detected(self, claude_root: Path) -> None:
        snapshot = snapshot_of(claude_root)
        target = claude_root / "notes.md"
        target.unlink()
        assert str(target.resolve()) in snapshot.changed_paths_since_capture()

    def test_recheck_ambiguity_aborts_and_discards(self, claude_root: Path) -> None:
        snapshot = snapshot_of(claude_root)
        target = claude_root / "notes.md"
        target.chmod(0o000)
        try:
            with pytest.raises(InspectionAbortedError, match="discards partials"):
                snapshot.changed_paths_since_capture()
        finally:
            target.chmod(0o644)


class TestBoundedCollection:
    def test_oversized_file_excluded_with_honest_record(self, claude_root: Path) -> None:
        (claude_root / "big.bin").write_bytes(b"x" * 4096)
        snapshot = snapshot_of(claude_root, bounds=CollectionBounds(max_file_bytes=1024))
        assert str((claude_root / "big.bin").resolve()) not in snapshot.canonical_paths()
        references = [item.reference for item in snapshot.exclusions]
        assert any("read-bound-exceeded" in ref and "big.bin" in ref for ref in references)
        assert all(
            item.state in (EvidenceState.BLOCKED, EvidenceState.ABSENT)
            for item in snapshot.exclusions
        )

    def test_file_count_bound_marks_incomplete(self, claude_root: Path) -> None:
        snapshot = snapshot_of(claude_root, bounds=CollectionBounds(max_file_count=2))
        assert not snapshot.complete
        assert len(snapshot.canonical_paths()) == 2
        assert any("file-count-bound-reached" in item.reference for item in snapshot.exclusions)

    def test_declared_artifacts_are_captured_before_the_bound_bites(self, tmp_path: Path) -> None:
        """The bound must spend itself on files no probe reads.

        An approved root is usually a whole working folder, so the admitted
        set dwarfs what the diagnosis needs. Left in walk order the bound was
        exhausted on unrelated files and the presence probes then described
        an arbitrary fraction of the scope — on one real vault, under a third
        of the files the probes declare an interest in.
        """
        root = tmp_path / "vault"
        (root / "zzz-last").mkdir(parents=True)
        # Filler that sorts before the declared artifact in any plain walk.
        for index in range(20):
            (root / f"aaa-filler-{index:02d}.txt").write_text("x")
        (root / "zzz-last" / "SKILL.md").write_text("# a skill\n")

        snapshot = snapshot_of(root, bounds=CollectionBounds(max_file_count=1))

        captured = [Path(path).name for path in snapshot.canonical_paths()]
        assert captured == ["SKILL.md"]
        assert not snapshot.complete

    def test_capture_order_is_stable_across_runs(self, claude_root: Path) -> None:
        """Two runs over an unchanged tree must capture the same files."""
        bounds = CollectionBounds(max_file_count=3)

        first = snapshot_of(claude_root, bounds=bounds).canonical_paths()
        second = snapshot_of(claude_root, bounds=bounds).canonical_paths()

        assert first == second

    def test_total_bytes_bound_marks_incomplete(self, claude_root: Path) -> None:
        (claude_root / "a.bin").write_bytes(b"a" * 900)
        (claude_root / "b.bin").write_bytes(b"b" * 900)
        snapshot = snapshot_of(claude_root, bounds=CollectionBounds(max_total_bytes=1000))
        assert not snapshot.complete
        assert any("total-bytes-bound-reached" in item.reference for item in snapshot.exclusions)

    def test_within_bounds_is_complete(self, claude_root: Path) -> None:
        assert snapshot_of(claude_root).complete


class TestFailClosed:
    def test_ambiguous_survey_decision_aborts_capture(
        self, claude_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from capability_exchange.adapters.claude_code import allowlist as allowlist_module

        allowlist = CanonicalAllowlist([claude_root])
        ambiguous = allowlist_module.PathDecision(
            verdict=allowlist_module.PathVerdict.BLOCKED,
            given_path=str(claude_root / "racy"),
            canonical_path=None,
            relative_path=None,
            reason="resolution-ambiguous:OSError",
            ambiguous=True,
        )
        real_survey = allowlist.survey

        def with_ambiguity() -> allowlist_module.SurveyOutcome:
            outcome = real_survey()
            return allowlist_module.SurveyOutcome(
                admitted_files=outcome.admitted_files,
                excluded=(*outcome.excluded, ambiguous),
            )

        monkeypatch.setattr(allowlist, "survey", with_ambiguity)
        with pytest.raises(InspectionAbortedError, match="discarded"):
            take_snapshot(allowlist)

    def test_symlink_escape_recorded_as_blocked_exclusion(
        self, claude_root: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside-secret"
        outside.write_text("private")
        (claude_root / "leak-link").symlink_to(outside)
        snapshot = snapshot_of(claude_root)
        blocked = [
            item
            for item in snapshot.exclusions
            if item.state is EvidenceState.BLOCKED and "symlink-escape" in item.reference
        ]
        assert blocked
        # the exclusion record never exposes the escape target
        assert all("outside-secret" not in item.reference for item in blocked)
