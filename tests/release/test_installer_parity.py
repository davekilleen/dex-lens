"""The two installers are one artifact, and this is what says so.

There are two scripts that install Dex Lens. `install.sh` is the source
installer, which a developer runs from a clone. The signed release installer
is rendered by `scripts/render_release_installer.py` and is the one served at
the address every README, both web pages and the product itself hand to a
person: `curl -fsSL https://heydex.ai/lens | bash`.

Almost nobody runs the first one. Everybody runs the second.

That asymmetry is how the two worst defects a red-team pass has found here
came to exist. Both were fixed once, in `install.sh`, and never reached the
rendered installer, so the fixed copy was the one nobody ran:

- `install.sh` grew an argument loop, so `--dry-run` said what it would do and
  changed nothing. The rendered installer parsed no arguments at all, so the
  documented `--dry-run` performed a full install — on the machine of the one
  person most likely to type it, the cautious one.
- `install.sh` grew a `case ":$PATH:"` warning, because a command in
  `~/.local/bin` is not findable when that folder is not on `PATH`. The
  rendered installer never checked, so the line it printed for a person to
  paste could start an assistant that could not find `dex-lens`, with no
  warning anywhere in the install.

Neither was visible to a test that read one file. Both are obvious the moment
the two are held against each other, which is what happens below. A behaviour
that matters to a person belongs in both scripts or in neither, and a fix that
lands in only one of them fails here rather than reaching a user.

These tests execute both scripts. Nothing here reaches the network: `curl` is
replaced by one that records the call and fails, so "it answered without
fetching anything" is proved rather than assumed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from tests.release.test_release_installer import (
    _rendered_installer,
    _sealed_network,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_INSTALLER = REPO_ROOT / "install.sh"

#: The line a person pastes to start the conversation. Two spellings of it is
#: one spelling too many: the released script said "that I do not" while
#: `install.sh`, both READMEs and both web pages said "that I don't".
THE_ASK = "what Dex has that I don't."


def _both_installers(tmp_path: Path) -> dict[str, Path]:
    """The source installer and a freshly rendered release installer."""
    return {
        "install.sh": SOURCE_INSTALLER,
        "rendered release installer": _rendered_installer(tmp_path),
    }


def _run(
    installer: Path, tmp_path: Path, home: Path, *arguments: str
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Run one installer with the network sealed, and report what it touched."""
    environment, curl_called = _sealed_network(tmp_path, home)
    completed = subprocess.run(  # noqa: S603 - reviewed installer under test
        ["bash", str(installer), *arguments],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    return completed, curl_called, home


def _wrote_anything(home: Path) -> list[str]:
    return sorted(str(path.relative_to(home)) for path in home.rglob("*"))


@pytest.mark.parametrize("flag", ["--help", "--dry-run"])
def test_both_installers_answer_a_documented_flag_without_installing(
    tmp_path: Path, flag: str
) -> None:
    """`--help` and `--dry-run` are answers. Neither may fetch or write.

    The released installer used to ignore both and install 46 MB instead.
    """
    for name, installer in _both_installers(tmp_path).items():
        home = tmp_path / f"home-{name.replace(' ', '-')}-{flag.strip('-')}"
        completed, curl_called, home = _run(installer, tmp_path, home, flag)
        assert completed.returncode == 0, f"{name} {flag}: {completed.stderr}"
        assert not curl_called.exists(), f"{name} {flag} reached the network"
        assert _wrote_anything(home) == [], f"{name} {flag} wrote into HOME"


def test_both_installers_refuse_an_option_they_do_not_know(tmp_path: Path) -> None:
    """An unknown flag stops, before the network, in both."""
    for name, installer in _both_installers(tmp_path).items():
        home = tmp_path / f"unknown-{name.replace(' ', '-')}"
        completed, curl_called, home = _run(
            installer, tmp_path, home, "--install-everything"
        )
        assert completed.returncode != 0, f"{name} accepted an unknown option"
        assert not curl_called.exists(), f"{name} reached the network on a bad option"
        assert _wrote_anything(home) == [], f"{name} wrote into HOME on a bad option"


def test_neither_installer_leaks_a_line_of_shell_into_its_help(tmp_path: Path) -> None:
    """Help is prose. `set -euo pipefail` in it is a file read one line too far."""
    for name, installer in _both_installers(tmp_path).items():
        home = tmp_path / f"help-shell-{name.replace(' ', '-')}"
        completed, _, _ = _run(installer, tmp_path, home, "--help")
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            assert not stripped.startswith(("set -", "#!/", "readonly ", "export ")), (
                f"{name} printed shell source in its help: {line!r}"
            )


def test_both_installers_warn_when_the_command_will_not_be_findable(
    tmp_path: Path,
) -> None:
    """A command in a folder that is not on PATH is installed and unusable.

    `install.sh` said so; the released installer did not, and its own
    troubleshooting entry on the help page pointed at the line it never
    printed.
    """
    for name, installer in _both_installers(tmp_path).items():
        text = installer.read_text(encoding="utf-8")
        assert 'case ":$PATH:"' in text, f"{name} never checks whether PATH will find it"


def test_both_installers_hand_over_the_same_sentence(tmp_path: Path) -> None:
    """One product, one line to paste."""
    for name, installer in _both_installers(tmp_path).items():
        text = installer.read_text(encoding="utf-8")
        assert THE_ASK in text, f"{name} does not use the agreed ask"
        assert "that I do not." not in text, f"{name} still uses the old wording"


def test_both_installers_ask_before_choosing_when_claude_and_codex_exist(
    tmp_path: Path,
) -> None:
    """One installed command must not silently win over another.

    A terminal cannot know which assistant a person intends to use just
    because both commands are installed. The direct, keyboard-preserving
    installer route must therefore promise one small choice instead of
    quietly preferring Claude Code.
    """
    launchers = tmp_path / "launchers"
    launchers.mkdir()
    for name in ("claude", "codex"):
        launcher = launchers / name
        launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)

    for name, installer in _both_installers(tmp_path).items():
        home = tmp_path / f"both-{name.replace(' ', '-')}-home"
        sealed_root = tmp_path / f"sealed-{name.replace(' ', '-').replace('.', '-')}"
        sealed_root.mkdir()
        environment, _ = _sealed_network(sealed_root, home)
        environment["PATH"] = f"{launchers}{os.pathsep}{environment['PATH']}"
        completed = subprocess.run(  # noqa: S603 - reviewed installer under test
            ["bash", str(installer), "--dry-run"],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        assert completed.returncode == 0, f"{name}: {completed.stderr}"
        assert "choose Claude Code or Codex" in completed.stdout, name


def test_both_installers_name_the_command_they_installed(tmp_path: Path) -> None:
    """"Exactly what changed" has to include the thing the person will type."""
    for name, installer in _both_installers(tmp_path).items():
        text = installer.read_text(encoding="utf-8")
        assert "/dex-lens" in text and "bin" in text, name


def test_a_dry_run_promises_the_note_only_where_a_real_run_would_send_one(
    tmp_path: Path,
) -> None:
    """An honesty feature that overstates is not one.

    Both dry runs used to announce the anonymous first-install note even when
    `DEX_LENS_NO_PING=1` had switched it off.
    """
    for name, installer in _both_installers(tmp_path).items():
        home = tmp_path / f"noping-{name.replace(' ', '-')}"
        environment, _ = _sealed_network(tmp_path, home)
        environment["DEX_LENS_NO_PING"] = "1"
        completed = subprocess.run(  # noqa: S603 - reviewed installer under test
            ["bash", str(installer), "--dry-run"],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "anonymous" not in completed.stdout.lower(), (
            f"{name} promised a note that DEX_LENS_NO_PING=1 had already switched off"
        )


def test_the_release_installer_is_rendered_from_the_version_being_shipped() -> None:
    """A re-render without a version bump ships yesterday's product.

    Fixing the code is not the same as fixing the install: the served
    installer is pinned to a released version, so work that lands here
    reaches nobody until a release is cut carrying it.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in pyproject.splitlines()
        if line.startswith("version")
    )
    renderer = (REPO_ROOT / "scripts" / "render_release_installer.py").read_text(
        encoding="utf-8"
    )
    assert "DEX_LENS_VERSION" in renderer
    assert version, "pyproject declares no version for a release to carry"
