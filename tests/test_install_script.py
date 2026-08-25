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
#: The source-install line: what this script answers, and the documented
#: fallback for development and unreleased changes.
MARKER_PATH = "{XDG_STATE_HOME:-$HOME/.local/state}/dex-lens/.install-recorded"
CODEX_GATE = '[ -d "$HOME/.codex" ] || command -v codex'

INSTALL_COMMAND = (
    "curl -fsSL https://raw.githubusercontent.com/davekilleen/dex-lens/main/install.sh | bash"
)

#: The headline line: the signed release installer, rendered and published by
#: the release workflow. This script is not that installer, but both READMEs
#: lead with it, and a README leading anywhere else is an install nobody gets.
RELEASE_INSTALL_COMMAND = (
    "curl -fsSL https://github.com/davekilleen/dex-lens/releases/latest/download/install.sh"
    " | bash"
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
        for expected in (
            "Dex Lens from",  # where the code comes from: this copy, or a download
            "venv",
            "/.local/bin",
            "/.claude/skills/dex-lens",
        ):
            assert expected in dry_run.stdout, expected

    def test_a_dry_run_never_starts_an_assistant(
        self, dry_run: subprocess.CompletedProcess[str], script: str
    ) -> None:
        """The hand-over to Claude Code is real, gated, and skippable.

        It must exist (one pasted line should end in the conversation), it
        must check for a terminal and for Claude Code before trying, it must
        honour DEX_LENS_NO_LAUNCH for scripts, and a dry run must exit long
        before reaching it.
        """
        assert 'exec "$ASSISTANT" "$DEX_LENS_ASK"' in script
        assert "[ -t 0 ]" in script, (
            "auto-launch only with a real keyboard: exec-ing a full-screen "
            "assistant from a piped script leaves it running but deaf"
        )
        assert "/dev/tty" not in script, "the deaf-assistant hand-off shape must not return"
        assert "One more paste and the conversation starts" in script
        assert 'command -v codex' in script, 'Codex is a first-class assistant too'
        assert "https://heydex.ai/lens/installed" in script
        assert "DEX_LENS_NO_PING" in script
        assert ".install-recorded" in script
        # The five review findings, held down:
        assert MARKER_PATH in script, "one shared marker; both installers, one ping ever"
        assert CODEX_GATE in script, "a machine that can launch codex never launches it blind"
        assert "open your assistant" in script, "the fallback names no single assistant"
        assert "PLACED_SKILLS" in script, "the summary names every skill home written"
        assert "command -v claude" in script
        assert "DEX_LENS_NO_LAUNCH" in script
        assert "Starting your assistant" not in dry_run.stdout

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


class TestThePipedInstall:
    """The shape the README documents: `curl … | bash`.

    Piped in, the script has no file on disk: `$BASH_SOURCE` is unset, and
    under `set -u` reading it unguarded printed
    `BASH_SOURCE[0]: unbound variable` and lost the ability to tell a clone
    from a download. Running the script by path never reproduced it, and the
    dry run used to exit before reaching the line, so nothing here caught it.
    """

    @staticmethod
    def _piped(home: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-s", "--", "--dry-run"],
            check=False,
            capture_output=True,
            text=True,
            input=INSTALLER.read_text(encoding="utf-8"),
            cwd="/",
            env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"},
        )

    def test_it_runs_clean_when_read_from_standard_input(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()

        result = self._piped(home)

        assert result.returncode == 0, result.stderr
        assert "unbound variable" not in result.stderr
        assert result.stderr == "", result.stderr

    def test_piped_in_it_knows_it_has_to_download_a_copy(self, tmp_path: Path) -> None:
        """There is no clone to install from, and it has to say which it is."""
        home = tmp_path / "home"
        home.mkdir()

        result = self._piped(home)

        assert "download Dex Lens from" in result.stdout
        assert "install Dex Lens from this copy" not in result.stdout
        assert list(home.iterdir()) == []

    def test_run_from_a_clone_it_installs_that_clone(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()

        result = subprocess.run(
            ["bash", str(INSTALLER), "--dry-run"],
            check=False,
            capture_output=True,
            text=True,
            env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"},
        )

        assert f"install Dex Lens from this copy: {REPO_ROOT}" in result.stdout


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


def test_the_documented_commands_are_the_commands_that_exist(script: str) -> None:
    """A README one-liner pointing anywhere else is an install nobody gets.

    Both lines must appear in both READMEs: the signed release first (the one
    a person is told to use), the source install as the stated fallback, and
    this script must name itself by the source line it answers.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    skill_readme = (REPO_ROOT / "docs" / "skill-README.md").read_text(encoding="utf-8")

    assert INSTALL_COMMAND in script
    for document in (readme, skill_readme):
        assert RELEASE_INSTALL_COMMAND in document
        assert INSTALL_COMMAND in document
