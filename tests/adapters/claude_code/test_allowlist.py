"""Canonicalized real-path allowlist (G1 items b, d): resolve before read,
refuse escapes, explicit mount/ignored policy, honest records."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from capability_exchange.adapters.claude_code.allowlist import (
    AllowlistError,
    CanonicalAllowlist,
    PathVerdict,
)


class TestConstruction:
    def test_nonexistent_root_refused(self, tmp_path: Path) -> None:
        with pytest.raises(AllowlistError, match="fail closed"):
            CanonicalAllowlist([tmp_path / "missing"])

    def test_file_root_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "a-file"
        target.write_text("x")
        with pytest.raises(AllowlistError, match="not a directory"):
            CanonicalAllowlist([target])

    def test_filesystem_root_refused(self) -> None:
        with pytest.raises(AllowlistError, match="never an approved scope"):
            CanonicalAllowlist(["/"])

    def test_whole_home_refused(self) -> None:
        with pytest.raises(AllowlistError, match="never an approved scope"):
            CanonicalAllowlist(["~"])

    def test_empty_allowlist_refused(self) -> None:
        with pytest.raises(AllowlistError, match="empty allowlist"):
            CanonicalAllowlist([])

    def test_roots_are_canonicalized_real_paths(self, tmp_path: Path) -> None:
        real = tmp_path / "real-root"
        real.mkdir()
        link = tmp_path / "link-root"
        link.symlink_to(real)
        allowlist = CanonicalAllowlist([link])
        assert allowlist.approved_roots == (str(real.resolve()),)


class TestEvaluate:
    def test_file_inside_scope_admitted(self, claude_root: Path) -> None:
        decision = CanonicalAllowlist([claude_root]).evaluate(claude_root / "CLAUDE.md")
        assert decision.is_admitted
        assert decision.canonical_path == str((claude_root / "CLAUDE.md").resolve())
        assert decision.relative_path == "CLAUDE.md"

    def test_missing_path_is_absent(self, claude_root: Path) -> None:
        decision = CanonicalAllowlist([claude_root]).evaluate(claude_root / "nope.md")
        assert decision.verdict is PathVerdict.ABSENT
        assert decision.reason == "not-found"

    def test_path_outside_scope_blocked(self, claude_root: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("x")
        decision = CanonicalAllowlist([claude_root]).evaluate(outside)
        assert decision.verdict is PathVerdict.BLOCKED
        assert decision.reason == "outside-allowlist"

    def test_symlink_escaping_allowlist_blocked(self, claude_root: Path, tmp_path: Path) -> None:
        target = tmp_path / "outside-secret"
        target.write_text("private")
        link = claude_root / "innocent-looking.md"
        link.symlink_to(target)
        decision = CanonicalAllowlist([claude_root]).evaluate(link)
        assert decision.verdict is PathVerdict.BLOCKED
        assert decision.reason == "symlink-escape"
        assert decision.canonical_path is None  # the escape target is never exposed

    def test_symlink_to_home_ssh_shape_blocked(self, claude_root: Path, tmp_path: Path) -> None:
        fake_ssh = tmp_path / ".ssh"
        fake_ssh.mkdir()
        (fake_ssh / "id_ed25519").write_text("key")
        link = claude_root / "ssh-link"
        link.symlink_to(fake_ssh / "id_ed25519")
        decision = CanonicalAllowlist([claude_root]).evaluate(link)
        assert decision.verdict is PathVerdict.BLOCKED
        assert decision.reason == "symlink-escape"

    def test_symlink_within_scope_resolves_to_target(self, claude_root: Path) -> None:
        link = claude_root / "alias.md"
        link.symlink_to(claude_root / "CLAUDE.md")
        decision = CanonicalAllowlist([claude_root]).evaluate(link)
        assert decision.is_admitted
        assert decision.canonical_path == str((claude_root / "CLAUDE.md").resolve())

    def test_dangling_symlink_is_absent_not_ambiguous(
        self, claude_root: Path, tmp_path: Path
    ) -> None:
        """Adversarial M1 finding: a broken symlink must be an honest
        `absent` exclusion, not runtime ambiguity.

        `realpath(strict=True)` raises FileNotFoundError for a dangling
        link, which was classified as ambiguous — and ambiguity aborts the
        whole inspection. Broken symlinks are ordinary in real systems and
        trivial for a hostile one to plant, so that classification hands any
        inspected system a one-file kill switch for the deep adapter. ENOENT
        is unambiguous: the target verifiably is not there.
        """
        link = claude_root / "dangling.md"
        link.symlink_to(tmp_path / "never-existed")
        decision = CanonicalAllowlist([claude_root]).evaluate(link)
        assert decision.verdict is PathVerdict.ABSENT
        assert not decision.ambiguous
        assert decision.reason == "dangling-symlink"
        assert decision.canonical_path is None

    def test_symlink_loop_is_blocked_not_ambiguous(self, claude_root: Path) -> None:
        """A self-referential symlink resolves to ELOOP — unambiguously
        unresolvable, so an honest `blocked` exclusion rather than an
        inspection-wide abort."""
        link = claude_root / "loop.md"
        link.symlink_to(link)
        decision = CanonicalAllowlist([claude_root]).evaluate(link)
        assert decision.verdict is PathVerdict.BLOCKED
        assert not decision.ambiguous
        assert decision.reason == "symlink-loop"
        assert decision.canonical_path is None

    def test_hard_link_to_outside_bytes_blocked(self, claude_root: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside-data"
        outside.write_text("shared bytes")
        hard = claude_root / "hardlinked.md"
        os.link(outside, hard)
        decision = CanonicalAllowlist([claude_root]).evaluate(hard)
        assert decision.verdict is PathVerdict.BLOCKED
        assert decision.reason == "hardlink-ambiguous"

    def test_denied_path_blocked_even_inside_scope(self, claude_root: Path) -> None:
        credentials = claude_root / ".claude" / ".credentials.json"
        credentials.write_text('{"oauth": "token"}')
        allowlist = CanonicalAllowlist([claude_root], denied_paths=[credentials])
        decision = allowlist.evaluate(credentials)
        assert decision.verdict is PathVerdict.BLOCKED
        assert decision.reason == "denied-path"

    def test_traversal_input_is_canonicalized_first(self, claude_root: Path) -> None:
        crooked = claude_root / ".claude" / ".." / "CLAUDE.md"
        decision = CanonicalAllowlist([claude_root]).evaluate(crooked)
        assert decision.is_admitted
        assert decision.canonical_path == str((claude_root / "CLAUDE.md").resolve())

    def test_traversal_escaping_scope_blocked(self, claude_root: Path, tmp_path: Path) -> None:
        (tmp_path / "escape.txt").write_text("x")
        crooked = claude_root / ".." / "escape.txt"
        decision = CanonicalAllowlist([claude_root]).evaluate(crooked)
        assert decision.verdict is PathVerdict.BLOCKED

    def test_special_file_blocked(self, claude_root: Path) -> None:
        fifo = claude_root / "pipe"
        os.mkfifo(fifo)
        decision = CanonicalAllowlist([claude_root]).evaluate(fifo)
        assert decision.verdict is PathVerdict.BLOCKED
        assert decision.reason == "special-file"

    def test_mount_point_crossing_blocked(
        self, claude_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowlist = CanonicalAllowlist([claude_root])
        target = claude_root / "CLAUDE.md"
        real_stat = os.stat

        class _ForeignDevice:
            def __init__(self, inner: os.stat_result) -> None:
                self._inner = inner

            def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
                if name == "st_dev":
                    return self._inner.st_dev + 1
                return getattr(self._inner, name)

        def foreign_device(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            result = real_stat(path, *args, **kwargs)
            if str(path) == str(target.resolve()):
                return _ForeignDevice(result)
            return result

        monkeypatch.setattr(os, "stat", foreign_device)
        decision = allowlist.evaluate(target)
        assert decision.verdict is PathVerdict.BLOCKED
        assert decision.reason == "mount-point-crossing"


class TestSurvey:
    def test_survey_is_deterministic_and_complete(self, claude_root: Path) -> None:
        allowlist = CanonicalAllowlist([claude_root])
        first = allowlist.survey()
        second = allowlist.survey()
        assert [d.canonical_path for d in first.admitted_files] == [
            d.canonical_path for d in second.admitted_files
        ]
        relative = {d.relative_path for d in first.admitted_files}
        assert "CLAUDE.md" in relative
        assert ".claude/settings.json" in relative

    def test_ignored_directories_pruned_and_recorded(self, claude_root: Path) -> None:
        node_modules = claude_root / "node_modules" / "pkg"
        node_modules.mkdir(parents=True)
        (node_modules / "index.js").write_text("code")
        outcome = CanonicalAllowlist([claude_root]).survey()
        assert all("node_modules" not in (d.relative_path or "") for d in outcome.admitted_files)
        reasons = {(d.relative_path, d.reason) for d in outcome.excluded}
        assert ("node_modules", "ignored-directory") in reasons

    def test_gitignored_file_still_inspected(self, claude_root: Path) -> None:
        # Ignored-file policy: .gitignore'd files are NOT skipped — skipping
        # them would miss planted secrets (G1 hostile fixture 3).
        (claude_root / ".gitignore").write_text("secrets.env\n")
        (claude_root / "secrets.env").write_text("API_KEY=verysecretvalue1\n")
        outcome = CanonicalAllowlist([claude_root]).survey()
        assert "secrets.env" in {d.relative_path for d in outcome.admitted_files}

    def test_symlinked_directory_not_descended_and_recorded(
        self, claude_root: Path, tmp_path: Path
    ) -> None:
        outside_dir = tmp_path / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "leak.txt").write_text("private")
        (claude_root / "linked-dir").symlink_to(outside_dir)
        outcome = CanonicalAllowlist([claude_root]).survey()
        assert all("leak.txt" not in (d.relative_path or "") for d in outcome.admitted_files)
        assert any(d.reason == "symlink-escape" for d in outcome.excluded)

    def test_unlistable_directory_recorded_not_silent(self, claude_root: Path) -> None:
        sealed = claude_root / "sealed"
        sealed.mkdir()
        (sealed / "hidden.md").write_text("x")
        sealed.chmod(0o000)
        try:
            outcome = CanonicalAllowlist([claude_root]).survey()
        finally:
            sealed.chmod(0o755)
        assert any(d.reason.startswith("walk-error:") for d in outcome.excluded)
