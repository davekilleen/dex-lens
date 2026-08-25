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


class TestHousekeeping:
    """The findings about the system itself, which the fold used to bury.

    The first real vault this ran on held 22 leftover worktrees carrying 97%
    of every file count, and the inventory reported them only as a "×32"
    multiplier. Accurate, and useless: the person's actual question was "how
    can I have 6,417 skills?", and the answer deserved to be a named finding.
    """

    def test_leftover_working_copies_are_named_with_their_share(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        inventory_main([str(system)])

        out = capsys.readouterr().out
        assert "### Leftover working copies" in out
        assert "`.worktrees`" in out, "the container is named, not folded away"
        assert "check before removing" in out, "worktrees may hold unmerged work"

    def test_identical_copies_are_not_reported_as_drift(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The fixture's three copies are byte-identical: no drift to report."""
        inventory_main([str(system)])

        assert "Copies that no longer match" not in capsys.readouterr().out

    def test_copies_with_different_content_are_reported_as_versions(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Same name, different bytes is the drift that erodes a system.

        A worktree copy edited independently of the original is two versions
        of one skill with nothing recording which is canonical.
        """
        drifted = system / ".worktrees" / "wt-a" / ".claude" / "skills" / "week-review"
        (drifted / "SKILL.md").write_text(
            "---\nname: week-review\ndescription: Review the week in finished work.\n---\n"
            "\n# week-review\n\nEdited only here.\n",
            encoding="utf-8",
        )

        inventory_main([str(system)])

        out = capsys.readouterr().out
        assert "### Copies that no longer match" in out
        assert "3 copies in 2 versions" in out
        assert "(2 versions)" in out, "the listing itself carries the version count"

    def test_disabled_names_surface_as_unmet_intent(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _skill(
            system,
            ".claude/skills/_disabled_commitment-scan/SKILL.md",
            name="_disabled_commitment-scan",
            description="Scan for uncommitted promises.",
        )

        inventory_main([str(system)])

        out = capsys.readouterr().out
        assert "### Switched off by name" in out
        assert "_disabled_commitment-scan" in out

    def test_a_clean_system_gets_no_empty_housekeeping_subsections(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Findings sections must exist only when there is a finding."""
        root = tmp_path / "tidy"
        root.mkdir()
        _skill(root, ".claude/skills/one/SKILL.md", name="one", description="One thing.")

        inventory_main([str(root)])

        out = capsys.readouterr().out
        assert "Leftover working copies" not in out
        assert "Copies that no longer match" not in out
        assert "Switched off by name" not in out


def test_the_inventory_says_how_the_diagnosis_has_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The two rules are easiest to drop exactly when this file is read.

    An assistant partway through a long run has the material in front of it
    and the report format thousands of tokens behind it. Repeating the rules
    here is the last cheap place to say them.
    """
    root = tmp_path / "vault"
    root.mkdir()
    _skill(root, ".claude/skills/one/SKILL.md", name="one", description="One thing.")

    assert inventory_main([str(root)]) == 0

    out = capsys.readouterr().out
    assert "## How this ends" in out
    assert "dex-lens reports save" in out
    assert "No quote means the finding is Unknown" in out


class TestNarrowingByName:
    """A second look usually wants three items, not two hundred and sixty.

    The rule the narrowing must not break: it hides rows, never facts. The
    counts and the housekeeping findings are about the whole folder, and stay
    about the whole folder.
    """

    def test_it_lists_only_matching_items(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "vault"
        root.mkdir()
        _skill(
            root, ".claude/skills/daily-plan/SKILL.md", name="daily-plan", description="Plan."
        )
        _skill(
            root,
            ".claude/skills/week-review/SKILL.md",
            name="week-review",
            description="Look back.",
        )

        assert inventory_main([str(root), "--names", "daily"]) == 0

        out = capsys.readouterr().out
        assert "daily-plan" in out
        assert "week-review" not in out

    def test_the_counts_still_describe_the_whole_folder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Otherwise a narrowed look quietly reports a smaller system."""
        root = tmp_path / "vault"
        root.mkdir()
        _skill(
            root, ".claude/skills/daily-plan/SKILL.md", name="daily-plan", description="Plan."
        )
        _skill(
            root,
            ".claude/skills/week-review/SKILL.md",
            name="week-review",
            description="Look back.",
        )

        inventory_main([str(root), "--names", "daily"])

        out = capsys.readouterr().out
        assert "2 distinct" in out
        assert "showing 1 that match" in out
        assert "**Narrowed.**" in out

    def test_a_name_nobody_has_is_refused_rather_than_answered_with_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An empty listing would read as "you have nothing called that"."""
        root = tmp_path / "vault"
        root.mkdir()
        _skill(
            root, ".claude/skills/daily-plan/SKILL.md", name="daily-plan", description="Plan."
        )

        assert inventory_main([str(root), "--names", "sailing"]) == 1

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "reading an empty list as an absence" in captured.err


class TestOtherAssistantsInstructions:
    def test_agents_md_is_inventoried_alongside_claude_md(
        self, system: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A real system is rarely one-harness, and drift hides in the half
        the inventory cannot see.

        The same setup often carries Claude Code instructions AND the
        AGENTS.md that Codex and Cursor read, frequently as paired copies of
        one intent. On the reference vault, Claude/Codex skill variants
        drifting apart was among the largest genuine findings — invisible to
        an inventory that only knows one assistant's file names.
        """
        (system / "AGENTS.md").write_text(
            "# House rules, for Codex\n\nBe brief.\n", encoding="utf-8"
        )

        inventory_main([str(system)])

        out = capsys.readouterr().out
        assert "## AGENTS.md (1 distinct, 1 files)" in out
        assert "House rules, for Codex" in out
