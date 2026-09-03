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
from capability_exchange.concierge.collection import ApprovedSourceDescriptor, ScopeSnapshot
from capability_exchange.evidence import EvidenceState

not_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="permission fixtures are meaningless as root"
)


def snapshot_of(root: Path, **kwargs):  # type: ignore[no-untyped-def]
    return take_snapshot(CanonicalAllowlist([root]), **kwargs)


@pytest.mark.parametrize("descendant_first", (False, True))
def test_snapshot_refuses_overlapping_approved_roots_before_collection(
    tmp_path: Path,
    descendant_first: bool,
) -> None:
    ancestor = tmp_path / "scope"
    descendant = ancestor / "nested"
    descendant.mkdir(parents=True)
    roots = (descendant, ancestor) if descendant_first else (ancestor, descendant)
    descriptors = tuple(
        ApprovedSourceDescriptor(
            canonical_root=root.resolve(),
            source_id=f"scope:root-{index}",
            source_class="vault-authored" if index == 0 else "user-global",
            scope_reference="scope:sha256:" + str(index + 1) * 64,
        )
        for index, root in enumerate(roots)
    )

    with pytest.raises(ValueError, match="overlap|ancestor|descendant"):
        take_snapshot(
            CanonicalAllowlist(roots),
            source_descriptors=descriptors,
        )


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

    def test_snapshot_entry_retains_consent_approved_source(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        global_home = tmp_path / "global"
        vault.mkdir()
        global_home.mkdir()
        (vault / "SKILL.md").write_text("# vault copy\n")
        (global_home / "SKILL.md").write_text("# global copy\n")
        consent = ScopeSnapshot.capture(
            (vault, global_home),
            source_descriptors=(
                {
                    "canonical_root": vault.resolve(),
                    "source_id": "scope:vault",
                    "source_class": "vault-authored",
                    "scope_reference": "scope:sha256:" + "a" * 64,
                },
                {
                    "canonical_root": global_home.resolve(),
                    "source_id": "scope:global",
                    "source_class": "user-global",
                    "scope_reference": "scope:sha256:" + "b" * 64,
                },
            ),
        )

        snapshot = take_snapshot(
            CanonicalAllowlist((vault, global_home)),
            source_descriptors=consent.source_descriptors,
        )

        assert snapshot.entry_for(str((vault / "SKILL.md").resolve())).source.source_id == (
            "scope:vault"
        )
        assert (
            snapshot.entry_for(str((global_home / "SKILL.md").resolve())).source.source_id
            == "scope:global"
        )

    def test_snapshot_rejects_source_descriptors_for_a_different_scope(
        self, tmp_path: Path
    ) -> None:
        approved = tmp_path / "approved"
        other = tmp_path / "other"
        approved.mkdir()
        other.mkdir()
        consent = ScopeSnapshot.capture((other,))

        with pytest.raises(ValueError, match="descriptor|approved root"):
            take_snapshot(
                CanonicalAllowlist((approved,)),
                source_descriptors=consent.source_descriptors,
            )

    def test_snapshot_retains_approved_sources_even_when_one_is_empty(self, tmp_path: Path) -> None:
        populated = tmp_path / "populated"
        empty = tmp_path / "empty"
        populated.mkdir()
        empty.mkdir()
        (populated / "SKILL.md").write_text("# captured\n")
        consent = ScopeSnapshot.capture(
            (populated, empty),
            source_descriptors=(
                {
                    "canonical_root": populated.resolve(),
                    "source_id": "scope:populated",
                    "source_class": "vault-authored",
                    "scope_reference": "scope:sha256:" + "a" * 64,
                },
                {
                    "canonical_root": empty.resolve(),
                    "source_id": "scope:empty",
                    "source_class": "user-global",
                    "scope_reference": "scope:sha256:" + "b" * 64,
                },
            ),
        )

        snapshot = take_snapshot(
            CanonicalAllowlist((populated, empty)),
            source_descriptors=consent.source_descriptors,
        )

        assert [source.source_id for source in snapshot.approved_sources] == [
            "scope:populated",
            "scope:empty",
        ]
        assert all(not hasattr(source, "canonical_root") for source in snapshot.approved_sources)

    @pytest.mark.parametrize(
        "attribute,value",
        (
            ("_complete", False),
            ("_entries", {}),
            ("_approved_sources", ()),
            ("_bounds", CollectionBounds(max_file_count=1)),
        ),
    )
    def test_snapshot_state_cannot_be_reassigned_after_capture(
        self,
        claude_root: Path,
        attribute: str,
        value: object,
    ) -> None:
        snapshot = snapshot_of(claude_root)

        with pytest.raises(AttributeError, match="immutable|read-only|assign"):
            setattr(snapshot, attribute, value)

    @pytest.mark.parametrize("attribute", ("_approved_sources", "_entries"))
    def test_snapshot_state_cannot_be_deleted_after_capture(
        self,
        claude_root: Path,
        attribute: str,
    ) -> None:
        snapshot = snapshot_of(claude_root)

        with pytest.raises(AttributeError, match="immutable|read-only|delete"):
            delattr(snapshot, attribute)


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

    @not_root
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

    def test_per_server_mcp_manifest_is_prioritised_before_the_bound(self, tmp_path: Path) -> None:
        root = tmp_path / "vault"
        manifest = root / ".claude" / "mcp" / "career.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"name":"career","server":{"command":"python"}}')
        for index in range(20):
            (root / f"aaa-filler-{index:02d}.txt").write_text("x")

        snapshot = snapshot_of(root, bounds=CollectionBounds(max_file_count=1))

        assert [Path(path).name for path in snapshot.canonical_paths()] == ["career.json"]
        assert not snapshot.complete

    @pytest.mark.parametrize(
        ("relative_path", "content"),
        (
            (
                "scripts/backup-verify.sh",
                '#!/bin/sh\ntmp_dir="$(mktemp -d)"\nrclone copy remote:backup "$tmp_dir"\n',
            ),
            (
                ".claude/hooks/adapters/todoist.cjs",
                "module.exports = { toExternal, toDex, create, complete, getChanges, health };\n",
            ),
            (
                ".claude/hooks/adapters/trello.cjs",
                "module.exports = { toExternal, toDex, create, complete, getChanges, health };\n",
            ),
        ),
    )
    def test_reviewed_recovery_and_task_adapter_probes_are_prioritised_before_bound(
        self,
        tmp_path: Path,
        relative_path: str,
        content: str,
    ) -> None:
        root = tmp_path / "vault"
        target = root / relative_path
        target.parent.mkdir(parents=True)
        target.write_text(content)
        for index in range(20):
            (root / f"aaa-filler-{index:02d}.txt").write_text("x")

        snapshot = snapshot_of(root, bounds=CollectionBounds(max_file_count=1))

        assert [Path(path).name for path in snapshot.canonical_paths()] == [target.name]
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


class TestFilesThatWereNotRead:
    """A file the allowlist admitted and the capture then failed to read.

    This is the worst failure this module can have, because it is invisible
    downstream: the entry is simply not in the snapshot, and every reader —
    the presence probes, the inventory — sees a folder that has no such file
    rather than a file nobody managed to read. The rule is that any admitted
    file the capture did not read marks the capture incomplete, exactly as a
    bound does, and is named in ``unread_files`` with the reason.
    """

    def test_an_oversized_file_marks_the_capture_incomplete(self, tmp_path: Path) -> None:
        """The route that emptied a real inventory: one file over the bound.

        A folder whose only CLAUDE.md is a byte past ``max_file_bytes`` used
        to render as "none captured" with no caveat, which reads as "you
        have no instruction file".
        """
        root = tmp_path / "vault"
        root.mkdir()
        (root / "CLAUDE.md").write_bytes(b"x" * 2049)

        snapshot = snapshot_of(root, bounds=CollectionBounds(max_file_bytes=2048))

        assert snapshot.canonical_paths() == ()
        assert not snapshot.complete, "a file that was not read is not a complete capture"
        assert [(unread.reason, unread.relative_path) for unread in snapshot.unread_files] == [
            ("read-bound-exceeded", "CLAUDE.md")
        ]

    def test_a_file_that_grows_past_the_bound_mid_read_marks_incomplete(
        self, claude_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Small at fstat, oversized by the time it is read: still unread."""
        target = str((claude_root / "CLAUDE.md").resolve())
        real_read = os.read
        grown = {"done": False}

        def growing_read(fd: int, length: int) -> bytes:
            chunk = real_read(fd, length)
            if not grown["done"] and os.fstat(fd).st_ino == os.stat(target).st_ino:
                grown["done"] = True
                return b"y" * 4096
            return chunk

        monkeypatch.setattr(os, "read", growing_read)
        snapshot = snapshot_of(claude_root, bounds=CollectionBounds(max_file_bytes=1024))

        assert target not in snapshot.canonical_paths()
        assert not snapshot.complete
        assert any(
            unread.reason == "read-bound-exceeded" and unread.relative_path == "CLAUDE.md"
            for unread in snapshot.unread_files
        )

    def test_a_file_that_cannot_be_opened_marks_the_capture_incomplete(
        self, claude_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The open failure route, provoked without needing to drop privilege.

        The permission fixture below is the real-world shape of this, but it
        is meaningless as root, so this gate is kept runnable everywhere:
        a capture that could not open an admitted file is not complete.
        """
        target = str((claude_root / "CLAUDE.md").resolve())
        real_open = os.open

        def refusing_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
            if path == target:
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", refusing_open)
        snapshot = snapshot_of(claude_root)

        assert target not in snapshot.canonical_paths()
        assert not snapshot.complete, "an unopenable file is not a complete capture"
        assert any(
            unread.reason == "read-error" and unread.relative_path == "CLAUDE.md"
            for unread in snapshot.unread_files
        )

    @not_root
    def test_a_permission_denied_file_marks_the_capture_incomplete(self, claude_root: Path) -> None:
        target = claude_root / "CLAUDE.md"
        target.chmod(0o000)
        try:
            snapshot = snapshot_of(claude_root)
        finally:
            target.chmod(0o644)

        assert str(target.resolve()) not in snapshot.canonical_paths()
        assert not snapshot.complete
        assert any(unread.reason == "read-error" for unread in snapshot.unread_files)

    def test_a_bound_that_stops_collection_is_named_too(self, claude_root: Path) -> None:
        """The bounds already marked incomplete; now they say which files."""
        snapshot = snapshot_of(claude_root, bounds=CollectionBounds(max_file_count=1))

        reasons = {unread.reason for unread in snapshot.unread_files}
        assert reasons == {"file-count-bound-reached"}
        assert all(unread.relative_path for unread in snapshot.unread_files)

    def test_a_hostile_name_is_carried_as_a_token_not_a_broken_reference(
        self, tmp_path: Path
    ) -> None:
        """An unread file's name is untrusted text like any other.

        The reference keeps the safe token; the path is carried beside it so
        a renderer can decide, and a name too hostile to print is still
        counted rather than dropped.
        """
        root = tmp_path / "vault"
        root.mkdir()
        hostile = "-----BEGIN a b c d e name.md"
        (root / hostile).write_bytes(b"x" * 2049)

        snapshot = snapshot_of(root, bounds=CollectionBounds(max_file_bytes=2048))

        assert len(snapshot.unread_files) == 1
        unread = snapshot.unread_files[0]
        assert unread.relative_path == hostile
        assert unread.token.startswith("sha256:"), "the reference form stays safe"
        assert any(unread.token in item.reference for item in snapshot.exclusions)


def _build_reference_scale_vault(root: Path) -> int:
    """A synthetic vault at the documented reference scale. All content invented.

    The first real evaluation (2026-09-03) read a ~6,800-file vault and
    truncated. This reconstruction matches that scale: thousands of small
    markdown notes and skill files with a realistic size mix — mostly 2-20 KB
    notes, a tail of long-form documents, every file far under the 1 MiB
    per-file bound — totalling ~166 MiB. The mix is deterministic so two runs
    build byte-identical trees.
    """
    filler = (
        "This invented note line carries ordinary prose about a project, a "
        "habit, or a meeting, none of it real, purely synthetic fixture text.\n"
    )
    count = 0

    def write(path: Path, size: int) -> None:
        nonlocal count
        path.parent.mkdir(parents=True, exist_ok=True)
        body = (filler * (size // len(filler) + 1))[:size]
        path.write_text("# Invented note\n\n" + body)
        count += 1

    write(root / "CLAUDE.md", 4_000)
    write(root / "AGENTS.md", 3_000)
    (root / ".mcp.json").write_text('{"mcpServers": {"notes": {"command": "runner"}}}')
    count += 1
    for index in range(240):
        write(root / ".claude" / "skills" / f"skill-{index:03d}" / "SKILL.md", 2_500)

    area = 0
    while count < 6_800:
        area_dir = root / f"Areas/{area // 40:02d}/topic-{area % 40:02d}"
        for note in range(min(8, 6_800 - count)):
            cycle = (area * 8 + note) % 100
            if cycle < 55:
                size = 2_000 + cycle * 100  # short notes, 2-7.5 KB
            elif cycle < 85:
                size = 8_000 + cycle * 150  # medium notes, ~17-20 KB
            elif cycle < 97:
                size = 60_000 + cycle * 300  # long-form notes
            else:
                size = 220_000 + cycle * 500  # exported documents
            write(area_dir / f"note-{note}.md", size)
        area += 1
    return count


@pytest.fixture(scope="module")
def reference_scale_vault(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("reference-scale") / "vault"
    root.mkdir()
    total = _build_reference_scale_vault(root)
    assert total == 6_800
    return root


@pytest.fixture(scope="module")
def reference_scale_snapshot(reference_scale_vault: Path):  # type: ignore[no-untyped-def]
    """One default-bounds capture of the reference tree, shared read-only."""
    return snapshot_of(reference_scale_vault)


class TestReferenceScaleCapture:
    """The capture must fit a real vault, and stay honest when it cannot.

    RISK-BOUNDED-CAPTURE-ABSENCE history is load-bearing here: a bounded
    capture must never report absence for what it did not read. These tests
    hold both directions on one reference-scale tree — a vault of the
    documented real-evaluation scale captures *completely* under the default
    bounds, and the same tree under a bound it exceeds stays incomplete with
    every guarantee intact (diagnostic files captured first, unread files
    named, presence probes saying could-not-check instead of absent).
    """

    OLD_TOTAL_BYTES_BOUND = 64 * 1024 * 1024

    def test_reference_scale_vault_captures_completely_under_default_bounds(
        self, reference_scale_snapshot  # type: ignore[no-untyped-def]
    ) -> None:
        """The 2026-09-03 evaluation's failure mode: bytes bound too low.

        Observed on the unchanged tree before the fix: 4,023 of 6,800 files
        unread, every one ``total-bytes-bound-reached`` — the 64 MiB
        ``max_total_bytes`` bound bit while the count (6,800 < 16,384) and
        per-file (all < 1 MiB) bounds never did. A complete capture of the
        reference scale is the fix, with the bound still finite.
        """
        snapshot = reference_scale_snapshot

        assert snapshot.complete, (
            "a vault at the documented reference scale must capture completely; "
            f"unread reasons: {sorted({item.reason for item in snapshot.unread_files})}"
        )
        assert len(snapshot.canonical_paths()) == 6_800
        assert snapshot.unread_files == ()

        from capability_exchange.adapters.claude_code.discovery import discover_fingerprint

        limits = discover_fingerprint(snapshot, collected_at=snapshot.taken_at).limits
        assert not any("only partly captured" in line for line in limits)

    def test_reference_scale_vault_over_bound_capture_stays_honest(
        self, reference_scale_vault: Path
    ) -> None:
        """A genuinely over-bound capture keeps every honesty guarantee.

        The same reference tree under the previous 64 MiB byte bound is the
        still-over-bound fixture: it must say which bound bit, name the
        unread files, have spent the bound on diagnostic material first, and
        never let a presence probe claim absence for the unread remainder.
        """
        from capability_exchange.adapter.envelope import InstrumentHealth
        from capability_exchange.adapters.claude_code.collector import EvidenceCollector
        from capability_exchange.adapters.claude_code.contract import claude_code_contract
        from capability_exchange.adapters.claude_code.discovery import discover_fingerprint

        snapshot = snapshot_of(
            reference_scale_vault,
            bounds=CollectionBounds(max_total_bytes=self.OLD_TOTAL_BYTES_BOUND),
        )

        # The bound bit, honestly: incomplete, and every unread file is named
        # with the byte-bound reason (never the count or per-file bounds).
        assert not snapshot.complete
        assert snapshot.unread_files
        assert {item.reason for item in snapshot.unread_files} == {"total-bytes-bound-reached"}
        assert all(item.relative_path for item in snapshot.unread_files)

        # Diagnostic basenames were captured before the bound bit (the
        # RISK-BOUNDED-CAPTURE-ABSENCE ordering fix must not regress).
        captured_names = {Path(path).name for path in snapshot.canonical_paths()}
        assert "CLAUDE.md" in captured_names
        assert ".mcp.json" in captured_names
        assert len(snapshot.entries_named("SKILL.md")) == 240

        # Presence probes on the incomplete capture say could-not-check with
        # blocked evidence for anything not captured — never absent.
        contract = claude_code_contract([str(reference_scale_vault)])
        envelope = EvidenceCollector(contract, snapshot).collect()
        probes = {probe.probe_id: probe for probe in envelope.probes}
        settings_probe = probes["settings-present"]
        assert settings_probe.health is InstrumentHealth.COULD_NOT_CHECK
        assert "absence cannot be claimed" in settings_probe.detail
        assert all(item.state is EvidenceState.BLOCKED for item in settings_probe.evidence)
        assert probes["collection-exclusions"].health is InstrumentHealth.COULD_NOT_CHECK

        # And the discovery limits disclose the truncation to the report.
        limits = discover_fingerprint(snapshot, collected_at=snapshot.taken_at).limits
        assert any("only partly captured" in line for line in limits)

    def test_complete_reference_capture_may_claim_absence(
        self,
        reference_scale_vault: Path,
        reference_scale_snapshot,  # type: ignore[no-untyped-def]
    ) -> None:
        """Absence is claimable exactly when the whole scope was read.

        The vault genuinely holds no ``settings.json``. Under the over-bound
        capture that fact is unknowable (could-not-check above); under the
        complete capture it is provable and reported as honest absence.
        """
        from capability_exchange.adapter.envelope import InstrumentHealth
        from capability_exchange.adapters.claude_code.collector import EvidenceCollector
        from capability_exchange.adapters.claude_code.contract import claude_code_contract

        snapshot = reference_scale_snapshot
        assert snapshot.complete

        contract = claude_code_contract([str(reference_scale_vault)])
        envelope = EvidenceCollector(contract, snapshot).collect()
        settings_probe = {probe.probe_id: probe for probe in envelope.probes}["settings-present"]
        assert settings_probe.health is InstrumentHealth.HEALTHY
        assert [item.state for item in settings_probe.evidence] == [EvidenceState.ABSENT]


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
