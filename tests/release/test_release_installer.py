"""Tests for signing and rendering the public Dex Lens installer."""

from __future__ import annotations

import os
import subprocess
import sys
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
        release_url="https://github.com/davekilleen/dex-lens/releases/download/v0.1.0",
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
    # browser journey.
    assert "skill/dex-lens/SKILL.md" in installer
    assert 'files("capability_exchange")' in installer
    assert "Have a look at my setup and tell me what Dex has that I do not." in installer
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

    # Execute the hand-off line rather than pattern-matching it. The bug a
    # real tester hit was invisible to a substring check: the rendered line
    # left $DEX_LENS_ASK unquoted, the shell split it into fourteen words,
    # and printf faithfully printed one word per line. Running it is the
    # only check that would have caught that.
    hand_off = next(
        line.strip()
        for line in installer.splitlines()
        if line.strip().startswith("printf") and '%s "%s"' in line
    )
    printed = subprocess.run(  # noqa: S602 - fixed line from the rendered installer
        f'DEX_LENS_ASSISTANT=claude; DEX_LENS_ASK="Do a thing for me, please."; {hand_off}',
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
    assert printed.returncode == 0, printed.stderr
    assert printed.stdout.count("\n") == 1, (
        f"the start command must print as one line, got: {printed.stdout!r}"
    )
    assert printed.stdout.strip() == 'claude "Do a thing for me, please."', printed.stdout
    assert 'command -v codex' in installer, 'Codex is a first-class assistant too'
    # The first-install note: declared, triple-gated, and harmless on failure.
    assert "https://heydex.ai/lens/installed" in installer
    assert '"${DEX_LENS_INSTALL_ONLY:-0}" != "1"' in installer, "CI proofs must never ping"
    assert "DEX_LENS_NO_PING" in installer, "the off-switch is part of the declaration"
    assert ".install-recorded" in installer, "re-installs are silent"
    # The five review findings, held down:
    assert "{XDG_STATE_HOME:-$HOME/.local/state}/dex-lens/.install-recorded" in installer, (
        "one shared marker; both installers, one ping ever"
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
    assert "sudo" not in installer
    assert "git clone" not in installer
    assert "curl |" not in installer
    assert "pip install http" not in installer
    parsed = subprocess.run(  # noqa: S603 - fixed bash syntax check
        ["bash", "-n"], input=installer, text=True, capture_output=True, check=False
    )
    assert parsed.returncode == 0, parsed.stderr


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
