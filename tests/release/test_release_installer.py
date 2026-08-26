"""Tests for signing and rendering the public Dex Lens installer."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from scripts.release_bundle import (
    ReleaseAsset,
    ReleaseManifest,
    sign_manifest,
    verify_manifest_signature,
)
from scripts.render_release_installer import render_installer

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_URL = "https://github.com/davekilleen/dex-lens/releases/download/v0.1.0"

#: A line of the installer's own source, printed where help text belongs.
SHELL_SOURCE = re.compile(
    r"^\s*(set -|readonly |export |local |trap |eval |source |printf |echo |"
    r"if |fi$|then$|else$|elif |for |done$|while |case |esac$|#!|"
    r"[A-Za-z_][A-Za-z0-9_]*\(\)\s*\{)"
)


def _manifest() -> ReleaseManifest:
    return ReleaseManifest(
        version="0.1.0",
        source_commit="b" * 40,
        assets=(
            ReleaseAsset(
                target="linux-x86_64",
                filename="dex-lens-v0.1.0-linux-x86_64.tar.gz",
                sha256="a" * 64,
            ),
            ReleaseAsset(
                target="macos-arm64",
                filename="dex-lens-v0.1.0-macos-arm64.tar.gz",
                sha256="c" * 64,
            ),
        ),
    )


def _test_keypair(tmp_path: Path) -> tuple[Path, Path]:
    private = ec.generate_private_key(ec.SECP256R1())
    private_path = tmp_path / "release-private.pem"
    public_path = tmp_path / "release-public.pem"
    private_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def _rendered_installer(tmp_path: Path) -> Path:
    _, public_key = _test_keypair(tmp_path)
    installer_path = tmp_path / "install.sh"
    installer_path.write_text(
        render_installer(
            manifest=_manifest(),
            release_url=RELEASE_URL,
            public_key_pem=public_key.read_bytes(),
        ),
        encoding="utf-8",
    )
    return installer_path


def _sealed_network(tmp_path: Path, home: Path) -> tuple[dict[str, str], Path]:
    """An environment whose curl records the call it should never be asked to make.

    `--help` and `--dry-run` are answers, not installs. Anything they do
    reaches the network through curl, so a curl that only tells on itself is
    the whole proof.
    """
    home.mkdir(parents=True, exist_ok=True)
    sealed_bin = tmp_path / "sealed-bin"
    sealed_bin.mkdir(exist_ok=True)
    curl_called = tmp_path / "curl-called"
    (sealed_bin / "curl").write_text(
        f"#!/usr/bin/env bash\ntouch {shlex.quote(str(curl_called))}\nexit 99\n",
        encoding="utf-8",
    )
    (sealed_bin / "curl").chmod(0o755)
    environment = os.environ | {
        "HOME": str(home),
        "PATH": f"{sealed_bin}{os.pathsep}{os.environ['PATH']}",
    }
    environment.pop("DEX_LENS_SKILLS_DIR", None)
    return environment, curl_called


def _legacy_source_launcher(home: Path) -> tuple[Path, Path]:
    """The exact command link written by the earlier official source installer."""
    legacy = home / ".local" / "share" / "dex-lens" / "venv" / "bin" / "dex-lens"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    legacy.chmod(0o755)
    launcher = home / ".local" / "bin" / "dex-lens"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(legacy)
    return launcher, legacy


def _run_sealed_signed_install(
    tmp_path: Path, home: Path
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Run the real rendered installer with every release byte supplied locally."""
    archive = tmp_path / "release.tar.gz"
    placeholder = tmp_path / "placeholder.whl"
    placeholder.write_bytes(b"not installed: signed version is pre-created")
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(placeholder, arcname="wheelhouse/placeholder.whl")
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()

    manifest = ReleaseManifest(
        version="0.1.0",
        source_commit="b" * 40,
        assets=(
            ReleaseAsset(
                target="linux-x86_64",
                filename="dex-lens-v0.1.0-linux-x86_64.tar.gz",
                sha256=archive_sha,
            ),
            ReleaseAsset(
                target="macos-arm64",
                filename="dex-lens-v0.1.0-macos-arm64.tar.gz",
                sha256=archive_sha,
            ),
        ),
    )
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_bytes(manifest.to_bytes())
    signature_path = tmp_path / "release-manifest.sig"
    signature_path.write_bytes(b"test signature; openssl is sealed below")

    _, public_key = _test_keypair(tmp_path)
    installer = tmp_path / "signed-install.sh"
    installer.write_text(
        render_installer(
            manifest=manifest,
            release_url=RELEASE_URL,
            public_key_pem=public_key.read_bytes(),
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "sealed-release-bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text(
        """#!/usr/bin/env bash
set -eu
output=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  */release-manifest.json) cp "$DEX_LENS_TEST_MANIFEST" "$output" ;;
  */release-manifest.sig) cp "$DEX_LENS_TEST_SIGNATURE" "$output" ;;
  */dex-lens-v0.1.0-*.tar.gz) cp "$DEX_LENS_TEST_ARCHIVE" "$output" ;;
  *) exit 91 ;;
esac
""",
        encoding="utf-8",
    )
    (fake_bin / "openssl").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    for command in (fake_bin / "curl", fake_bin / "openssl"):
        command.chmod(0o755)

    data_home = tmp_path / "signed-data"
    signed_target = (
        data_home
        / "dex-lens"
        / "versions"
        / "v0.1.0"
        / "venv"
        / "bin"
        / "dex-lens"
    )
    signed_target.parent.mkdir(parents=True)
    signed_target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    signed_target.chmod(0o755)
    signed_python = signed_target.parent / "python"
    signed_python.write_text(
        f"#!/usr/bin/env bash\nexec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    signed_python.chmod(0o755)

    skill_home = tmp_path / "skills"
    environment = os.environ | {
        "HOME": str(home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "DEX_LENS_DATA_HOME": str(data_home),
        "DEX_LENS_SKILLS_DIR": str(skill_home),
        "DEX_LENS_INSTALL_ONLY": "1",
        "DEX_LENS_NO_PING": "1",
        "DEX_LENS_TEST_MANIFEST": str(manifest_path),
        "DEX_LENS_TEST_SIGNATURE": str(signature_path),
        "DEX_LENS_TEST_ARCHIVE": str(archive),
    }
    completed = subprocess.run(
        ["bash", str(installer)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    return completed, signed_target, skill_home


def _hand_off_line(text: str) -> str:
    """The whole printf that prints the start command, continuations joined.

    The line is written across two source lines to stay readable; what the
    shell sees is one command, and one command is what has to be run here.
    """
    lines = text.splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line.strip().startswith("printf") and '%s "%s"' in line
    )
    collected = []
    while True:
        current = lines[start].strip()
        collected.append(current.removesuffix("\\").strip())
        if not current.endswith("\\"):
            break
        start += 1
    return " ".join(collected)


def _start_line(installer: str, bin_home: Path) -> str:
    """Run the printed hand-off line the way the installer runs it.

    Executed rather than pattern-matched. The bug a real tester hit was
    invisible to a substring check: the rendered line left $DEX_LENS_ASK
    unquoted, the shell split it into fourteen words, and printf faithfully
    printed one word per line.
    """
    printed = subprocess.run(  # noqa: S602 - fixed line from the rendered installer
        f"DEX_LENS_BIN_HOME={shlex.quote(str(bin_home))}; DEX_LENS_ASSISTANT=claude; "
        f'DEX_LENS_ASK="Do a thing for me, please."; {_hand_off_line(installer)}',
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
    assert printed.returncode == 0, printed.stderr
    assert printed.stdout.count("\n") == 1, (
        f"the start command must print as one line, got: {printed.stdout!r}"
    )
    return printed.stdout.strip()


def test_p256_signature_covers_the_exact_manifest_bytes(tmp_path: Path) -> None:
    manifest_path = tmp_path / "release-manifest.json"
    signature_path = tmp_path / "release-manifest.sig"
    private_key, _ = _test_keypair(tmp_path)
    rendered_public_key = tmp_path / "signed-release-public.pem"
    manifest_path.write_bytes(_manifest().to_bytes())

    sign_manifest(manifest_path, private_key, signature_path, rendered_public_key)

    assert verify_manifest_signature(manifest_path, signature_path, rendered_public_key)
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
    assert not verify_manifest_signature(manifest_path, signature_path, rendered_public_key)


def test_renderer_contains_only_the_public_key_and_offline_install_controls(tmp_path: Path) -> None:
    private_key, public_key = _test_keypair(tmp_path)

    installer = render_installer(
        manifest=_manifest(),
        release_url=RELEASE_URL,
        public_key_pem=public_key.read_bytes(),
    )

    assert private_key.read_text(encoding="utf-8") not in installer
    assert public_key.read_text(encoding="utf-8") in installer
    assert "openssl dgst -sha256 -verify" in installer
    assert "--no-index" in installer
    assert "--only-binary=:all:" in installer
    # The product is the skill plus the command: the installer must place the
    # skill out of the verified wheel — never a separate download — and must
    # end at the person's real first step, not by launching the frozen
    # browser journey. It places the whole skill directory, not only SKILL.md:
    # the skill reads a bundled capability reference next to it, and a copy
    # that took only SKILL.md left the skill comparing against a quarter of Dex.
    assert 'files("capability_exchange").joinpath("skill/dex-lens")' in installer
    assert 'dex-capabilities.json' in installer, (
        "the installer must place the bundled capability reference, not only SKILL.md"
    )
    assert "Have a look at my setup and tell me what Dex has that I don't." in installer
    assert "that I do not." not in installer, (
        "two spellings of the one line people paste is one spelling too many"
    )
    assert "dex-lens --choose-folder" not in installer
    # One pasted line ends in the conversation: the installer hands over to
    # Claude Code when it exists and a real terminal is attached — and only
    # then. The install-only proof must exit before any launch is reachable,
    # so CI never starts an assistant.
    assert 'exec "$DEX_LENS_ASSISTANT" "$DEX_LENS_ASK"' in installer
    assert "[ -t 0 ]" in installer, (
        "auto-launch only with a real keyboard: exec-ing a full-screen "
        "assistant from a piped script leaves it running but deaf"
    )
    assert "/dev/tty" not in installer, "the deaf-assistant hand-off shape must not return"
    assert "One more paste and the conversation starts" in installer

    start_line = _start_line(installer, tmp_path / "bin")
    assert start_line.endswith('claude "Do a thing for me, please."'), start_line
    assert 'command -v codex' in installer, 'Codex is a first-class assistant too'
    # The first-install note: declared, triple-gated, and harmless on failure.
    assert "https://heydex.ai/lens/installed" in installer
    assert '"${DEX_LENS_INSTALL_ONLY:-0}" != "1"' in installer, "CI proofs must never ping"
    assert "DEX_LENS_NO_PING" in installer, "the off-switch is part of the declaration"
    assert ".install-recorded" in installer, "re-installs are silent"
    # The five review findings, held down:
    assert "{XDG_STATE_HOME:-$HOME/.local/state}/dex-lens" in installer, (
        "one shared marker; both installers, one ping ever"
    )
    assert '"$DEX_LENS_PING_STATE_DIR/.install-recorded"' in installer, (
        "the marker sits in that one folder, which is itself a change worth naming"
    )
    assert '[ -d "$HOME/.codex" ] || command -v codex' in installer, (
        "a machine that can launch codex never launches it blind"
    )
    assert "One anonymous note went to heydex.ai" in installer, (
        "the closing words disclose the note in the same sentences the page uses"
    )
    assert "DEX_LENS_PLACED" in installer, "the closing words name every skill home written"
    ping_at = installer.index("lens/installed")
    assert installer.index("Install-only check complete") > 0
    ping_block = installer[ping_at : ping_at + 600]
    assert "fi || true" in ping_block, "a failed note never fails an install"
    assert "command -v claude" in installer
    assert "DEX_LENS_NO_LAUNCH" in installer
    launch_at = installer.index('exec "$DEX_LENS_ASSISTANT"')
    assert installer.index("Install-only check complete") < launch_at
    assert "Python 3.11 through 3.14" in installer
    assert "https://www.python.org/downloads/" in installer
    assert "Library/Application Support" in installer
    assert "XDG_DATA_HOME" not in installer
    assert '"$DEX_LENS_VENV/bin/dex-lens" --help' in installer
    assert "A partial install from this run was removed safely" in installer
    # Two options exist because the page that publishes this installer says
    # they do, and both have to be answered before anything is fetched.
    assert "--dry-run) DEX_LENS_DRY_RUN=1 ;;" in installer
    assert "I do not understand the option" in installer
    # pip's own progress is not the person's business: fourteen "Processing
    # …whl" lines are what a wheelhouse install prints unasked.
    assert "-m pip install --quiet --no-index" in installer
    # A command nobody's shell can find is not installed, as far as the
    # person holding the terminal is concerned.
    assert 'case ":$PATH:" in' in installer
    assert "installed but not findable" in installer
    assert "The dex-lens command is at $DEX_LENS_LAUNCHER" in installer, (
        "the closing words name the command they just created"
    )
    assert "sudo" not in installer
    assert "git clone" not in installer
    assert "curl |" not in installer
    assert "pip install http" not in installer
    parsed = subprocess.run(  # noqa: S603 - fixed bash syntax check
        ["bash", "-n"], input=installer, text=True, capture_output=True, check=False
    )
    assert parsed.returncode == 0, parsed.stderr


class TestTheOptionsThePageDocuments:
    """`--dry-run` and `--help`, on the installer people actually run.

    The published installer parsed no arguments at all: `curl … | bash -s --
    --dry-run` performed a full install, forty-six megabytes of it, while the
    page beside the command promised that `--dry-run` says what it would do
    and does none of it. Every test here runs the rendered file.
    """

    @staticmethod
    def _run(
        tmp_path: Path, home: Path, *arguments: str, piped: bool = False, **overrides: str
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        installer = _rendered_installer(tmp_path)
        environment, curl_called = _sealed_network(tmp_path, home)
        environment |= overrides
        from_a_file = ["bash", str(installer), *arguments]
        command = ["bash", "-s", "--", *arguments] if piped else from_a_file
        completed = subprocess.run(  # noqa: S603 - test invokes the rendered installer
            command,
            text=True,
            capture_output=True,
            env=environment,
            input=installer.read_text(encoding="utf-8") if piped else None,
            check=False,
        )
        return completed, home, curl_called

    def test_help_answers_before_it_fetches_anything(self, tmp_path: Path) -> None:
        completed, home, curl_called = self._run(tmp_path, tmp_path / "home", "--help")

        assert completed.returncode == 0, completed.stderr
        assert "--dry-run" in completed.stdout
        assert "--help" in completed.stdout
        assert not curl_called.exists(), "help is an answer, not a download"
        assert list(home.iterdir()) == []

    def test_help_never_prints_a_line_of_shell(self, tmp_path: Path) -> None:
        completed, _, _ = self._run(tmp_path, tmp_path / "home", "--help")

        assert completed.stdout.strip(), "help that prints nothing is not help"
        for line in completed.stdout.splitlines():
            assert not SHELL_SOURCE.match(line), f"help printed a line of shell source: {line!r}"

    def test_a_piped_dry_run_says_what_it_would_do_and_does_none_of_it(
        self, tmp_path: Path
    ) -> None:
        """The published shape, with the option the published page promises."""
        completed, home, curl_called = self._run(
            tmp_path, tmp_path / "home", "--dry-run", piped=True
        )

        assert completed.returncode == 0, completed.stderr
        assert not curl_called.exists(), "a dry run downloads nothing"
        assert list(home.iterdir()) == [], "a dry run writes nothing"
        for named in (
            "dex-lens/versions/v0.1.0",  # the private install root
            "/.local/bin/dex-lens",  # the command
            "/.claude/skills/dex-lens",  # the skill, which is the product
            "/.local/state/dex-lens",  # the folder the first-install note leaves
            "anonymous",  # the note itself
            "your assistant",  # how a real run ends
        ):
            assert named in completed.stdout, named

    def test_the_dry_run_is_silent_about_a_note_that_would_not_be_sent(
        self, tmp_path: Path
    ) -> None:
        """The same gates as the real run, or the honesty feature overstates."""
        switched_off, _, _ = self._run(
            tmp_path, tmp_path / "quiet-home", "--dry-run", DEX_LENS_NO_PING="1"
        )

        assert switched_off.returncode == 0, switched_off.stderr
        assert "anonymous" not in switched_off.stdout, switched_off.stdout

        counted = tmp_path / "counted-home"
        (counted / ".local" / "state" / "dex-lens").mkdir(parents=True)
        (counted / ".local" / "state" / "dex-lens" / ".install-recorded").touch()

        already_counted, _, _ = self._run(tmp_path, counted, "--dry-run")

        assert already_counted.returncode == 0, already_counted.stderr
        assert "anonymous" not in already_counted.stdout, already_counted.stdout

    def test_an_option_it_does_not_know_stops_before_the_network(self, tmp_path: Path) -> None:
        completed, home, curl_called = self._run(
            tmp_path, tmp_path / "home", "--install-everything"
        )

        assert completed.returncode != 0
        assert "do not understand" in completed.stderr
        assert not curl_called.exists()
        assert list(home.iterdir()) == []


def test_a_dry_run_recognises_an_earlier_official_lens_install(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    launcher, legacy = _legacy_source_launcher(home)

    completed, _, curl_called = TestTheOptionsThePageDocuments._run(
        tmp_path, home, "--dry-run", piped=True
    )

    assert completed.returncode == 0, completed.stderr
    assert "It looks like you used Dex Lens before" in completed.stdout
    assert "Because you ran this installer" in completed.stdout
    assert str(legacy.parent.parent.parent) in completed.stdout
    assert "left in place" in completed.stdout
    assert launcher.resolve() == legacy
    assert not curl_called.exists()


def test_a_foreign_launcher_is_refused_before_network_or_writes(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    foreign = tmp_path / "some-other-tool" / "dex-lens"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    foreign.chmod(0o755)
    launcher = home / ".local" / "bin" / "dex-lens"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(foreign)

    completed, _, curl_called = TestTheOptionsThePageDocuments._run(
        tmp_path, home, "--dry-run", piped=True
    )

    assert completed.returncode != 0
    assert str(launcher) in completed.stderr
    assert str(foreign) in completed.stderr
    assert "will not overwrite" in completed.stderr
    assert launcher.resolve() == foreign
    assert not curl_called.exists()


def test_a_regular_launcher_is_refused_before_network_or_writes(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    launcher = home / ".local" / "bin" / "dex-lens"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    completed, _, curl_called = TestTheOptionsThePageDocuments._run(
        tmp_path, home, "--dry-run", piped=True
    )

    assert completed.returncode != 0
    assert str(launcher) in completed.stderr
    assert "will not overwrite" in completed.stderr
    assert launcher.is_file()
    assert not curl_called.exists()


def test_a_current_signed_launcher_remains_repeatable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    data_home = tmp_path / "signed-data"
    target = (
        data_home
        / "dex-lens"
        / "versions"
        / "v0.0.9"
        / "venv"
        / "bin"
        / "dex-lens"
    )
    target.parent.mkdir(parents=True)
    target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)
    launcher = home / ".local" / "bin" / "dex-lens"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(target)

    completed, _, curl_called = TestTheOptionsThePageDocuments._run(
        tmp_path,
        home,
        "--dry-run",
        piped=True,
        DEX_LENS_DATA_HOME=str(data_home),
    )

    assert completed.returncode == 0, completed.stderr
    assert launcher.resolve() == target
    assert not curl_called.exists()


def test_a_real_install_repoints_only_the_official_legacy_launcher(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    launcher, legacy = _legacy_source_launcher(home)

    completed, signed_target, skill_home = _run_sealed_signed_install(tmp_path, home)

    assert completed.returncode == 0, completed.stderr
    assert launcher.is_symlink()
    assert launcher.readlink() == signed_target
    assert legacy.exists(), "the rollback copy must remain untouched"
    assert (skill_home / "dex-lens" / "SKILL.md").is_file()
    assert (skill_home / "dex-lens" / "dex-capabilities.json").is_file()
    assert "It looks like you used Dex Lens before" in completed.stdout
    assert "Your earlier private copy is still" in completed.stdout


def test_the_printed_start_line_runs_where_the_command_is_not_yet_on_path(
    tmp_path: Path,
) -> None:
    """The documented install used to end in `dex-lens: command not found`.

    This installer has no PATH check and printed a bare `claude "…"` line, so
    the very command it had just linked into ~/.local/bin was unfindable by
    the assistant the person was told to paste. The line has to carry the
    folder itself; proved by running it in a shell that has never heard of it.
    """
    _, public_key = _test_keypair(tmp_path)
    installer = render_installer(
        manifest=_manifest(), release_url=RELEASE_URL, public_key_pem=public_key.read_bytes()
    )
    bin_home = tmp_path / "bin"
    bin_home.mkdir()
    (bin_home / "dex-lens").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_home / "dex-lens").chmod(0o755)
    assistant_dir = tmp_path / "assistant"
    assistant_dir.mkdir()
    (assistant_dir / "claude").write_text(
        '#!/usr/bin/env bash\nprintf "asked: %s\\n" "$1"\n'
        'printf "found: %s\\n" "$(command -v dex-lens || echo nowhere)"\n',
        encoding="utf-8",
    )
    (assistant_dir / "claude").chmod(0o755)

    start_line = _start_line(installer, bin_home)

    pasted = subprocess.run(  # noqa: S602 - the line the installer told the person to paste
        start_line,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
        env={"HOME": str(tmp_path), "PATH": f"{assistant_dir}{os.pathsep}/usr/bin:/bin"},
    )

    assert pasted.returncode == 0, pasted.stderr
    assert "asked: Use Dex Lens" not in pasted.stdout  # the ask is substituted, not hard-coded
    assert "asked: Do a thing for me, please." in pasted.stdout, pasted.stdout
    assert f"found: {bin_home / 'dex-lens'}" in pasted.stdout, (
        "the pasted line has to find dex-lens in a shell that never had it on PATH"
    )


def test_rendered_installer_refuses_windows_before_calling_curl(tmp_path: Path) -> None:
    _, public_key = _test_keypair(tmp_path)
    installer_path = tmp_path / "install.sh"
    installer_path.write_text(
        render_installer(
            manifest=_manifest(),
            release_url="https://github.com/davekilleen/dex-lens/releases/download/v0.1.0",
            public_key_pem=public_key.read_bytes(),
        ),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "uname").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' MINGW64_NT\n", encoding="utf-8"
    )
    (fake_bin / "curl").write_text(
        "#!/usr/bin/env bash\ntouch \"$DEX_LENS_CURL_CALLED\"\nexit 99\n", encoding="utf-8"
    )
    for command in (fake_bin / "uname", fake_bin / "curl"):
        command.chmod(0o755)
    curl_called = tmp_path / "curl-called"
    environment = os.environ | {
        "DEX_LENS_CURL_CALLED": str(curl_called),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    completed = subprocess.run(  # noqa: S603 - test invokes the rendered installer
        ["bash", str(installer_path)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert completed.returncode != 0
    assert "Windows Preview" in completed.stderr
    assert not curl_called.exists()


def test_renderer_cli_runs_as_a_direct_release_workflow_script() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed release-script smoke invocation
        [sys.executable, "scripts/render_release_installer.py", "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Render the signed public Dex Lens installer." in completed.stdout
