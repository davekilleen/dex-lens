"""``dex-lens inventory``: the shape of a personal system, honestly.

The inventory is the first thing the Dex Lens skill runs and the basis of
everything it says afterwards, so its failures are not local. An inventory
that quietly drops files produces confident claims about a system nobody
looked at, and an inventory too large to read produces no analysis at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capability_exchange.adapters.claude_code.inventory_cli import inventory_main


def _skill(root: Path, relative: str, *, name: str, description: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nBody.\n",
        encoding="utf-8",
    )


def tree_state(root: Path) -> dict[str, tuple[bytes, int]]:
    """Content and modification time of every file, for a zero-write proof."""
    state: dict[str, tuple[bytes, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            state[str(path)] = (path.read_bytes(), path.stat().st_mtime_ns)
    return state


@pytest.fixture
def system(tmp_path: Path) -> Path:
    root = tmp_path / "system"
    root.mkdir()
    (root / "CLAUDE.md").write_text("# House rules\n\nBe brief.\n", encoding="utf-8")
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    _skill(
        root,
        ".claude/skills/week-review/SKILL.md",
        name="week-review",
        description="Review the week in finished work.",
    )
    # The same authored skill, copied into two worktrees, as every real
    # system eventually does.
    for worktree in ("wt-a", "wt-b"):
        _skill(
            root,
            f".worktrees/{worktree}/.claude/skills/week-review/SKILL.md",
            name="week-review",
            description="Review the week in finished work.",
        )
    return root


class TestInventory:
    def test_it_writes_nothing_to_the_system_it_reads(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The one promise the whole skill rests on."""
        before = tree_state(system)

        assert inventory_main([str(system)]) == 0

        assert tree_state(system) == before
        capsys.readouterr()

    def test_copies_are_folded_and_counted_not_hidden(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Duplication is a finding, so fold it — never drop it.

        One authored skill copied across worktrees can appear dozens of times.
        Listing every copy buries the system's real shape; omitting them
        misreports its size. The fold shows one line with a count.
        """
        inventory_main([str(system)])

        out = capsys.readouterr().out
        assert "week-review" in out
        assert "×3" in out, "three copies of one skill must be counted"
        assert "3 files" in out
        assert "distinct" in out

    def test_a_bounded_capture_says_so(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Everything downstream depends on knowing the list is partial."""
        inventory_main([str(system), "--max-files", "1"])

        out = capsys.readouterr().out
        assert "Incomplete" in out
        assert "Do not describe anything as absent" in out

    def test_a_complete_capture_makes_no_such_claim(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        inventory_main([str(system)])

        assert "Incomplete" not in capsys.readouterr().out

    def test_unreadable_content_produces_no_description_not_mojibake(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A binary file named CLAUDE.md is real; the reference vault has one.

        Decoded as text it yields replacement characters, and a line of those
        in the inventory is worse than a blank: the assistant reading it will
        try to interpret it.
        """
        binary = system / "snapshots"
        binary.mkdir()
        (binary / "CLAUDE.md").write_bytes(b"\x00\x81\xfe\xff\x00binary\x00\xfe")

        inventory_main([str(system)])

        out = capsys.readouterr().out
        assert "�" not in out
        assert "no description declared" in out

    def test_a_missing_folder_is_refused_before_any_read(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert inventory_main([str(tmp_path / "nope")]) == 2
        assert "not a folder" in capsys.readouterr().err

    def test_it_writes_the_report_where_asked(
        self, system: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The only file it may create, and never inside the system it read."""
        out_path = tmp_path / "reports" / "inventory.md"

        inventory_main([str(system), "--out", str(out_path)])

        assert out_path.read_text(encoding="utf-8") == capsys.readouterr().out
