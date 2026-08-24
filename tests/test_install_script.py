"""The one action between nothing installed and the first insight.

Everything else in this repository is reachable only after `install.sh` has
run, which makes it the highest-consequence file here and the one nothing else
tests. It is checked three ways: it parses, it can be asked what it would do
without doing any of it, and the destructive lines in it name a computed
destination rather than a bare path.

No test here reaches the network or installs anything. A real run clones,
builds an environment and copies a skill into the person's own Claude Code
folder; proving that belongs on a clean machine, not in a unit test that would
have to write into the developer's live system to do it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "install.sh"
INSTALL_COMMAND = (
    "curl -fsSL https://raw.githubusercontent.com/davekilleen/dex-lens/main/install.sh | bash"
)


@pytest.fixture(scope="module")
def script() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_the_installer_is_executable_and_parses(script: str) -> None:
    assert INSTALLER.stat().st_mode & 0o111, "a curl | bash installer must also run directly"
    assert script.startswith("#!/usr/bin/env bash")

    subprocess.run(["bash", "-n", str(INSTALLER)], check=True, capture_output=True)


def test_it_stops_at_the_first_failure_rather_than_carrying_on(script: str) -> None:
    """Half an install that reports success is the worst outcome available."""
    assert "set -euo pipefail" in script


def test_every_recursive_delete_names_a_computed_destination(script: str) -> None:
    """`rm -rf` in an installer is where the catastrophes live.

    Each one must target a quoted variable the script itself built, never a
    literal path and never an unquoted expansion that an empty value could
    turn into the parent directory.
    """
    deletes = re.findall(r"^\s*rm -rf (.*)$", script, flags=re.MULTILINE)

    assert deletes, "the skill copy is replaced, so there is something to check"
    for target in deletes:
        assert re.fullmatch(r'"\$[A-Z_]+"', target.strip()), target


class TestDryRun:
    @pytest.fixture
    def dry_run(self, tmp_path: Path) -> subprocess.CompletedProcess[str]:
        home = tmp_path / "home"
        home.mkdir()
        return subprocess.run(
            ["bash", str(INSTALLER), "--dry-run"],
            check=False,
            capture_output=True,
            text=True,
            env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"},
        )

    def test_it_succeeds_and_names_all_four_things_it_would_do(
        self, dry_run: subprocess.CompletedProcess[str]
    ) -> None:
        assert dry_run.returncode == 0, dry_run.stderr
        for expected in ("source", "venv", "/.local/bin", "/.claude/skills/dex-lens"):
            assert expected in dry_run.stdout, expected

    def test_it_changes_nothing(self, tmp_path: Path) -> None:
        """`--dry-run` is the honesty check on everything the script claims."""
        home = tmp_path / "home"
        home.mkdir()

        subprocess.run(
            ["bash", str(INSTALLER), "--dry-run"],
            check=True,
            capture_output=True,
            text=True,
            env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"},
        )

        assert list(home.iterdir()) == []

    def test_it_says_it_will_not_touch_the_system_being_diagnosed(
        self, dry_run: subprocess.CompletedProcess[str]
    ) -> None:
        assert "not read, change, or send anything" in dry_run.stdout


def test_an_unknown_option_fails_loudly(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(INSTALLER), "--install-everything"],
        check=False,
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 1
    assert "do not understand" in result.stderr


def test_the_documented_command_is_the_command_this_script_answers(script: str) -> None:
    """A README one-liner pointing anywhere else is an install nobody gets."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    skill_readme = (REPO_ROOT / "skill" / "README.md").read_text(encoding="utf-8")

    assert INSTALL_COMMAND in script
    assert INSTALL_COMMAND in readme
    assert INSTALL_COMMAND in skill_readme
