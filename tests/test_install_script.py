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
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "install.sh"


def _sealed_interpreter_home() -> str:
    """A directory holding one interpreter and nothing else.

    The sealed PATH below exists to hide assistant choosers, not Python. But
    macOS ships 3.9 at ``/usr/bin/python3``, which the installer correctly
    refuses, so these tests were relying on a Homebrew interpreter that is not
    guaranteed on a given runner: the same commit passed on the macos-14
    py3.12 leg and failed on py3.11 on 2026-09-03, and STATUS.md records an
    earlier instance of the same class.

    Exposing the interpreter already running the tests makes the discovery
    deterministic without widening what the seal hides. The symlink is named
    for its real version because ``find_python`` looks for exact
    ``python3.13``/``python3.12``/``python3.11`` names before bare ``python3``.
    """

    directory = Path(tempfile.mkdtemp(prefix="dex-lens-sealed-interpreter-"))
    (directory / f"python3.{sys.version_info.minor}").symlink_to(sys.executable)
    return str(directory)


#: Assistant choosers stay hidden; a supported interpreter stays findable.
SEALED_PATH = ":".join(
    (_sealed_interpreter_home(), "/usr/bin", "/bin", "/usr/sbin", "/sbin", "/opt/homebrew/bin")
)
#: The source-install line: what this script answers, and the documented
#: fallback for development and unreleased changes.
#: One marker shared with the signed release installer, so a machine that runs
#: both installers still sends exactly one note, ever. Both halves are checked
#: because the path is now built in two steps: the folder is a change worth
#: listing on its own, and the file inside it is the marker.
MARKER_STATE_DIR = "{XDG_STATE_HOME:-$HOME/.local/state}/dex-lens"
MARKER_FILE = "/.install-recorded"
CODEX_GATE = '[ -d "$HOME/.codex" ] || command -v codex'

#: A line of this script's own source, printed where help text belongs. The
#: header used to be read by a hard-coded line range; the header shrank, the
#: range did not, and `--help` ended on `set -euo pipefail`.
SHELL_SOURCE = re.compile(
    r"^\s*(set -|readonly |export |local |trap |eval |source |printf |echo |"
    r"if |fi$|then$|else$|elif |for |done$|while |case |esac$|#!|"
    r"[A-Za-z_][A-Za-z0-9_]*\(\)\s*\{)"
)

INSTALL_COMMAND = (
    "bash <(curl -fsSL https://raw.githubusercontent.com/davekilleen/dex-lens/main/install.sh)"
)

#: The headline line: the signed release installer, rendered and published by
#: the release workflow. This script is not that installer, but both READMEs
#: lead with it, and a README leading anywhere else is an install nobody gets.
RELEASE_INSTALL_COMMAND = (
    "bash <(curl -fsSL https://github.com/davekilleen/dex-lens/releases/latest/download/install.sh)"
)


@pytest.fixture(scope="module")
def script() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def documented_header(script: str) -> str:
    """The comment header, exactly as `--help` has to print it.

    Computed the way the script itself has to read it — from the line after
    the shebang to the first line that is not a comment — rather than by a
    line number, because a line number in the test drifts in step with the
    line number in the script and so catches nothing.
    """
    lines: list[str] = []
    for line in script.splitlines()[1:]:
        if not line.startswith("#"):
            break
        lines.append(re.sub(r"^# ?", "", line))
    return "".join(f"{line}\n" for line in lines)


def run_installer(
    home: Path, *arguments: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = {"HOME": str(home), "PATH": SEALED_PATH}
    return subprocess.run(
        ["bash", str(INSTALLER), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment | (extra_env or {}),
    )


def piped_installer(home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """The documented shape: `curl … | bash -s -- …`, with no file to read."""
    return subprocess.run(
        ["bash", "-s", "--", *arguments],
        check=False,
        capture_output=True,
        text=True,
        input=INSTALLER.read_text(encoding="utf-8"),
        cwd="/",
        env={"HOME": str(home), "PATH": SEALED_PATH},
    )


class TestHelp:
    """Help says what the options are, and never a line of the script itself.

    Nothing here invoked `--help` at all until it printed `set -euo pipefail`
    at a person under the heading of documentation. Both documented shapes
    are exercised, because only one of them has a file to read the header out
    of: piped from curl there is none, and the fallback text is all there is.
    """

    def test_from_a_file_it_prints_the_header_and_stops_at_it(
        self, tmp_path: Path, script: str
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()

        result = run_installer(home, "--help")

        assert result.returncode == 0, result.stderr
        assert result.stdout == documented_header(script), result.stdout
        assert "set -euo pipefail" not in result.stdout
        assert list(home.iterdir()) == []

    def test_piped_in_it_still_answers_for_itself(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()

        result = piped_installer(home, "--help")

        assert result.returncode == 0, result.stderr
        assert "--dry-run" in result.stdout
        assert "DEX_LENS_HOME" in result.stdout
        assert list(home.iterdir()) == []

    @pytest.mark.parametrize("piped", [False, True])
    def test_no_line_of_help_is_a_line_of_shell(self, tmp_path: Path, piped: bool) -> None:
        home = tmp_path / "home"
        home.mkdir()

        result = piped_installer(home, "--help") if piped else run_installer(home, "--help")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip(), "help that prints nothing is not help"
        for line in result.stdout.splitlines():
            assert not SHELL_SOURCE.match(line), f"help printed a line of shell source: {line!r}"


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
            env={"HOME": str(home), "PATH": SEALED_PATH},
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
        assert 'bash <(curl -fsSL https://heydex.ai/lens)' in script
        assert "I found both Claude Code and Codex" in script
        assert "DEX_LENS_PREFERRED_ASSISTANT" in script
        assert 'command -v codex' in script, 'Codex is a first-class assistant too'
        assert "https://heydex.ai/lens/installed" in script
        assert "DEX_LENS_NO_PING" in script
        assert ".install-recorded" in script
        # The five review findings, held down:
        assert MARKER_STATE_DIR in script, "one shared marker; both installers, one ping ever"
        assert f'"$PING_STATE_DIR{MARKER_FILE}"' in script, "the marker sits in that one folder"
        assert CODEX_GATE in script, "a machine that can launch codex never launches it blind"
        assert "open your assistant" in script, "the fallback names no single assistant"
        assert "PLACED_SKILLS" in script, "the summary names every skill home written"
        assert "command -v claude" in script
        assert "DEX_LENS_NO_LAUNCH" in script
        assert "Starting your assistant" not in dry_run.stdout

    def test_the_dry_run_names_the_conditional_skill_homes(
        self, tmp_path: Path, script: str
    ) -> None:
        """The dry run uses the same gates as a real run, or it understates.

        A real run writes the Codex home when the codex command exists even
        if ~/.codex does not yet; the honesty path has to say so under the
        same condition, not a narrower one.
        """
        home = tmp_path / "home-with-codex"
        (home / ".codex").mkdir(parents=True)
        (home / ".agents").mkdir()
        result = subprocess.run(
            ["bash", str(INSTALLER), "--dry-run"],
            check=False,
            capture_output=True,
            text=True,
            env={"HOME": str(home), "PATH": SEALED_PATH},
        )

        assert result.returncode == 0, result.stderr
        assert "/.codex/skills/dex-lens" in result.stdout
        assert "/.agents/skills/dex-lens" in result.stdout

    def test_it_promises_the_note_only_where_a_real_run_would_send_one(
        self, tmp_path: Path
    ) -> None:
        """An honesty feature that overstates is not one.

        The dry run announced a first-install note under every condition,
        including the two where a real run sends nothing at all: the
        off-switch set, and a machine this note has already been sent from.
        """
        clean = tmp_path / "clean"
        clean.mkdir()

        first_run = run_installer(clean, "--dry-run")

        assert "anonymous" in first_run.stdout
        assert "/.local/state/dex-lens" in first_run.stdout, (
            "sending the note leaves a folder behind, so a real run writes there too"
        )

        switched_off = run_installer(clean, "--dry-run", extra_env={"DEX_LENS_NO_PING": "1"})

        assert "anonymous" not in switched_off.stdout, switched_off.stdout

        counted = tmp_path / "counted"
        (counted / ".local" / "state" / "dex-lens").mkdir(parents=True)
        (counted / ".local" / "state" / "dex-lens" / ".install-recorded").touch()

        already_counted = run_installer(counted, "--dry-run")

        assert "anonymous" not in already_counted.stdout, already_counted.stdout

    def test_it_names_the_hand_over_a_real_run_would_make(
        self, dry_run: subprocess.CompletedProcess[str]
    ) -> None:
        """A real run can replace this very shell with an assistant.

        That is the largest thing it does to the terminal it was pasted into,
        and the dry run used to be the one place that never mentioned it.
        """
        assert dry_run.returncode == 0, dry_run.stderr
        assert "assistant" in dry_run.stdout.lower(), dry_run.stdout
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
            env={"HOME": str(home), "PATH": SEALED_PATH},
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
            env={"HOME": str(home), "PATH": SEALED_PATH},
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
            env={"HOME": str(home), "PATH": SEALED_PATH},
        )

        assert f"install Dex Lens from this copy: {REPO_ROOT}" in result.stdout


def test_a_piped_installer_recommends_the_keyboard_preserving_handoff(script: str) -> None:
    """The public one-liner reruns from a file descriptor, not a pipe.

    That gives an interactive assistant the terminal's real keyboard, while
    retaining the one-command experience on the public page.
    """
    assert 'bash <(curl -fsSL https://heydex.ai/lens)' in script
    assert 'PATH="%s:$PATH" %s "%s"' not in script


def test_the_summary_lists_the_places_that_used_to_go_unmentioned(script: str) -> None:
    """"Prints exactly what it changed" was false in two places.

    The folder behind the first-install note is created before the note is
    even attempted, and pip fills its own cache on any install. Neither was
    listed, under a closing sentence claiming nothing else on the machine had
    been touched.
    """
    assert "Nothing else about this machine was touched" not in script, (
        "an absolute that is false is worse than no absolute"
    )
    assert "PING_STATE_DIR_CREATED" in script, "the note's folder is a change, so it is listed"
    assert "pip cache dir" in script, "pip's cache is named rather than quietly denied"


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
    readme_prose = " ".join(readme.split())

    assert INSTALL_COMMAND in script
    for document in (readme, skill_readme):
        assert RELEASE_INSTALL_COMMAND in document
        assert INSTALL_COMMAND in document
    assert "Run the same installer again when you want to update Lens" in readme_prose
    assert "does not silently update its software" in readme_prose
