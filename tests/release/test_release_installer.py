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
    assert "dex-lens --choose-folder" in installer
    assert "No folder is read until you approve it inside Dex Lens." in installer
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
        "HOME": str(tmp_path / "home"),
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
