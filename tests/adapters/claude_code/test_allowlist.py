"""Canonicalized real-path allowlist (G1 items b, d): resolve before read,
refuse escapes, explicit mount/ignored policy, honest records."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from capability_exchange.adapters.claude_code import allowlist as allowlist_module
from capability_exchange.adapters.claude_code.allowlist import (
    AllowlistError,
    CanonicalAllowlist,
    PathVerdict,
    read_mount_points,
)

not_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="permission fixtures are meaningless as root"
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

class TestMountTopology:
    """Mount handling (G1 item d).

    The real proof that a **bind mount** inside an approved root is refused
    is the hostile fixture in
    ``tests/fixtures/hostile/test_g1_bind_mount_escape.py``, which creates an
    actual mount inside a user namespace. It is the only thing that can prove
    it, because a bind mount is the one case that cannot be simulated without
    making one: same ``st_dev``, own inode, ``realpath`` unchanged.

    What is testable unprivileged, and tested here, is the layer that reads
    the kernel's answer: the mountinfo parser against the live table, and the
    allowlist's behaviour when the kernel reports a mount at a real,
    same-device directory inside a real approved root. Only the *source* of
    the mount table is redirected — the paths, devices and inodes involved
    are entirely real, and the device comparison genuinely passes.
    """

    def test_mountinfo_parser_reads_the_live_kernel_table(self) -> None:
        if sys.platform != "linux":
            pytest.skip("/proc/self/mountinfo is a Linux facility")
        points = read_mount_points()
        assert "/" in points, "a parser that cannot find the root mount is broken"
        assert "/proc" in points
        assert all(point.startswith("/") for point in points)

    def test_mountinfo_parser_unescapes_paths(self, tmp_path: Path) -> None:
        table = tmp_path / "mountinfo"
        table.write_text(
            "23 28 0:22 / /a\\040space rw,relatime shared:2 - tmpfs tmpfs rw\n"
            "24 28 0:23 / /tab\\011here rw - tmpfs tmpfs rw\n"
        )
        assert read_mount_points(str(table)) == {"/a space", "/tab\there"}

    def test_mountinfo_parser_accepts_pseudo_filesystem_roots(self, tmp_path: Path) -> None:
        # Real kernel output: nsfs (and friends) put a non-path in the root
        # field. A parser strict enough to reject it would turn every
        # inspection on a host running containers into a refusal.
        table = tmp_path / "mountinfo"
        table.write_text(
            "923 29 0:4 net:[4026532534] /run/docker/netns/c5d9 rw shared:601 - nsfs nsfs rw\n"
        )
        assert read_mount_points(str(table)) == {"/run/docker/netns/c5d9"}

    def test_unparseable_mount_table_refuses_rather_than_reads_empty(
        self, tmp_path: Path
    ) -> None:
        table = tmp_path / "mountinfo"
        table.write_text("this line is not mountinfo\n")
        with pytest.raises(AllowlistError, match="unparseable mount table line"):
            read_mount_points(str(table))

    def test_unreadable_mount_table_refuses_to_build_an_allowlist(
        self, claude_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Fail closed: with no mount table, a bind mount inside the approved
        # root cannot be ruled out, so no allowlist exists and no read happens.
        if sys.platform != "linux":
            pytest.skip("the mount table is only required on Linux")
        monkeypatch.setattr(allowlist_module, "MOUNTINFO_PATH", str(tmp_path / "absent"))
        with pytest.raises(AllowlistError, match="cannot be read"):
            CanonicalAllowlist([claude_root])

    #: The three tests below exercise the mount-*table* layer, which
    #: `_refresh_mount_topology` deliberately does not consult off Linux
    #: (darwin has no unprivileged bind mount to defend against; the
    #: dirent-inode cross-check in `survey` is the OS-independent backstop).
    #: Redirecting MOUNTINFO_PATH is therefore a no-op on darwin, and these
    #: assertions would fail not because the defence regressed but because
    #: the mechanism under test does not exist there.
    linux_mount_table = pytest.mark.skipif(
        sys.platform != "linux",
        reason="the mountinfo layer is a Linux facility; darwin never reads it",
    )

    @staticmethod
    def _kernel_reports_mount_at(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mount_point: Path
    ) -> None:
        """Point the mount-table reader at a real-format table naming a real,
        same-device directory. The only fiction is the kernel's answer — the
        very thing an unprivileged process cannot arrange for itself."""
        table = tmp_path / "mountinfo"
        escaped = str(mount_point).replace("\\", "\\134").replace(" ", "\\040")
        table.write_text(
            "23 28 0:22 / / rw,relatime shared:1 - ext4 /dev/root rw\n"
            f"99 23 0:22 /home/someone/.ssh {escaped} ro,relatime - ext4 /dev/root ro\n"
        )
        monkeypatch.setattr(allowlist_module, "MOUNTINFO_PATH", str(table))

    @linux_mount_table
    def test_mount_inside_scope_blocked_although_device_matches(
        self, claude_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        grafted = claude_root / "vendor-cache"
        grafted.mkdir()
        (grafted / "id_ed25519").write_text("key bytes")
        # The hole, stated as an assertion: nothing about this directory is
        # distinguishable from an ordinary one by device or by ismount.
        assert grafted.stat().st_dev == claude_root.stat().st_dev
        assert not os.path.ismount(grafted)

        self._kernel_reports_mount_at(monkeypatch, tmp_path, grafted)
        allowlist = CanonicalAllowlist([claude_root])
        assert allowlist.mount_points_inside_scope == (str(grafted),)

        directory = allowlist.evaluate(grafted)
        assert directory.verdict is PathVerdict.BLOCKED
        assert directory.reason == "mount-point-crossing"

        behind = allowlist.evaluate(grafted / "id_ed25519")
        assert behind.verdict is PathVerdict.BLOCKED
        assert behind.reason == "mount-point-crossing"
        assert behind.canonical_path is None

    @linux_mount_table
    def test_survey_prunes_a_mount_inside_scope_and_records_it(
        self, claude_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        grafted = claude_root / "vendor-cache"
        grafted.mkdir()
        (grafted / "id_ed25519").write_text("key bytes")
        self._kernel_reports_mount_at(monkeypatch, tmp_path, grafted)
        outcome = CanonicalAllowlist([claude_root]).survey()
        assert all(
            "vendor-cache" not in (d.relative_path or "") for d in outcome.admitted_files
        )
        assert ("vendor-cache", "mount-point-crossing") in {
            (d.relative_path, d.reason) for d in outcome.excluded
        }

    @linux_mount_table
    def test_approved_root_that_is_itself_a_mount_point_still_readable(
        self, claude_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The root is the scope the person named at consent time, and it is
        # what every device comparison is anchored to. Refusing it would make
        # any project on its own volume uninspectable.
        self._kernel_reports_mount_at(monkeypatch, tmp_path, claude_root)
        allowlist = CanonicalAllowlist([claude_root])
        assert allowlist.mount_points_inside_scope == ()
        assert allowlist.evaluate(claude_root / "CLAUDE.md").is_admitted

    def test_foreign_device_under_root_blocked(
        self, claude_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """White-box unit test of the ``st_dev`` branch only.

        A genuinely foreign device under an approved root also requires a
        mount to create, so the device is stubbed. This proves the branch
        exists and fires; it proves **nothing** about bind mounts, which keep
        the device identical — that is the hostile fixture's job. Kept
        because the branch is load-bearing on macOS, where there is no mount
        table to read.

        Patching ``os.stat`` demands care: the patched function must never
        call back into pathlib (``Path.resolve``, ``str(Path)``), because
        those call ``os.stat`` themselves and the shim would re-enter itself
        unboundedly. Every path value it needs is therefore resolved to a
        plain ``str`` *before* the patch is installed, and the shim compares
        strings only. It also returns a genuine ``os.stat_result`` rather
        than an attribute-proxy object, so callers that hand the result back
        to pathlib behave normally.
        """
        allowlist = CanonicalAllowlist([claude_root])
        target = claude_root / "CLAUDE.md"
        # Resolve BEFORE patching: no pathlib work may happen inside the shim.
        target_real = str(target.resolve())
        real_stat = os.stat

        def with_foreign_device(result: os.stat_result) -> os.stat_result:
            fields = list(result)  # the 10 canonical stat fields; st_dev is [2]
            fields[2] = result.st_dev + 1
            return os.stat_result(
                fields,
                {
                    "st_atime_ns": result.st_atime_ns,
                    "st_mtime_ns": result.st_mtime_ns,
                    "st_ctime_ns": result.st_ctime_ns,
                },
            )

        def foreign_device(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            result = real_stat(path, *args, **kwargs)
            # os.fspath on a str is the identity; the allowlist stats real
            # paths as str, so no pathlib conversion is triggered here.
            if isinstance(path, str) and path == target_real:
                return with_foreign_device(result)
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

    def test_vendored_plugin_marketplace_is_pruned_by_position(
        self, claude_root: Path
    ) -> None:
        # The exact tree one real machine read 83,088 files from: installed
        # third-party plugins under plugins/marketplaces, including a plugin's
        # own test fixture named "disabled-skill". None of it is the person's
        # system, and a bare-name prune cannot tell it apart.
        fixture = (
            claude_root
            / "plugins"
            / "marketplaces"
            / "compound-engineering-plugin"
            / "tests"
            / "fixtures"
            / "sample-plugin"
            / "skills"
            / "disabled-skill"
        )
        fixture.mkdir(parents=True)
        (fixture / "SKILL.md").write_text(
            "---\nname: disabled-skill\ndescription: model invocation disabled\n---\n",
            encoding="utf-8",
        )
        outcome = CanonicalAllowlist([claude_root]).survey()
        assert all(
            "marketplaces" not in (d.relative_path or "") for d in outcome.admitted_files
        )
        reasons = {(d.relative_path, d.reason) for d in outcome.excluded}
        assert ("plugins/marketplaces", "vendored-subtree") in reasons

    def test_a_person_named_marketplaces_folder_is_not_pruned(
        self, claude_root: Path
    ) -> None:
        # Only the position under plugins/ is vendored. A person's own folder
        # that happens to be called "marketplaces" is theirs, and stays.
        mine = claude_root / "notes" / "marketplaces"
        mine.mkdir(parents=True)
        (mine / "CLAUDE.md").write_text("# my market research\n", encoding="utf-8")
        outcome = CanonicalAllowlist([claude_root]).survey()
        assert "notes/marketplaces/CLAUDE.md" in {
            d.relative_path for d in outcome.admitted_files
        }

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

    @not_root
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
