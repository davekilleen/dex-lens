#!/usr/bin/env python3
"""Exercise a rendered release installer against local, exact release assets.

The public installer still believes it is downloading from its immutable HTTPS
release URL. This proof replaces only ``curl`` with a tiny fixed-argument copy
adapter, so every signature, checksum, archive, offline-pip and launch check in
the real script runs unchanged on Linux and Apple Silicon macOS CI.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path


class SmokeProofError(RuntimeError):
    """The exact rendered installer did not work as a clean consumer would."""


_CURL_ADAPTER = r'''#!/usr/bin/env bash
set -euo pipefail

output_path=""
release_url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output)
      output_path="$2"
      shift 2
      ;;
    *)
      release_url="$1"
      shift
      ;;
  esac
done

[ -n "$output_path" ]
[ -n "$release_url" ]
asset_name="${release_url##*/}"
case "$asset_name" in
  release-manifest.json|release-manifest.sig|dex-lens-v*.tar.gz) ;;
  *) printf '%s\n' "smoke adapter refused unexpected asset: $asset_name" >&2; exit 91 ;;
esac
cp "$DEX_LENS_RELEASE_FIXTURE/$asset_name" "$output_path"
'''


def _expected_target() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Linux" and machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    if system == "Darwin" and machine == "arm64":
        return "macos-arm64"
    raise SmokeProofError(f"release smoke proof has no supported target for {system} {machine}")


def run_smoke_proof(*, artifacts: Path, installer: Path) -> None:
    """Install into disposable paths and prove the resulting command starts."""
    target = _expected_target()
    try:
        manifest = json.loads((artifacts / "release-manifest.json").read_text(encoding="utf-8"))
        version = manifest["version"]
    except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SmokeProofError("release smoke manifest has no readable version") from exc
    if not isinstance(version, str) or not re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version
    ):
        raise SmokeProofError("release smoke manifest version is unsafe")
    required = {
        "release-manifest.json",
        "release-manifest.sig",
        f"dex-lens-v{version}-{target}.tar.gz",
    }
    missing = sorted(name for name in required if not (artifacts / name).is_file())
    if missing:
        raise SmokeProofError(f"release smoke fixture is incomplete: {missing}")
    if not installer.is_file():
        raise SmokeProofError(f"rendered installer is missing: {installer}")

    with tempfile.TemporaryDirectory(prefix="dex-lens-release-smoke-") as temporary:
        proof_root = Path(temporary)
        fake_bin = proof_root / "fake-bin"
        fake_bin.mkdir()
        curl_adapter = fake_bin / "curl"
        curl_adapter.write_text(_CURL_ADAPTER, encoding="utf-8")
        curl_adapter.chmod(0o755)

        data_home = proof_root / "data"
        bin_home = proof_root / "bin"
        skills_home = proof_root / "skills"
        environment = os.environ | {
            "DEX_LENS_RELEASE_FIXTURE": str(artifacts.resolve()),
            "DEX_LENS_INSTALL_ONLY": "1",
            "DEX_LENS_BIN_HOME": str(bin_home),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "DEX_LENS_DATA_HOME": str(data_home),
            # Point the skill somewhere disposable, so the proof never touches
            # the runner's real ~/.claude and its landing can be asserted.
            "DEX_LENS_SKILLS_DIR": str(skills_home),
        }
        installed = subprocess.run(  # noqa: S603 - exact reviewed installer path
            ["bash", str(installer.resolve())],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        if installed.returncode != 0:
            raise SmokeProofError(
                "rendered installer failed: "
                + " ".join((installed.stderr or installed.stdout).split())[:600]
            )
        if "Install-only check complete" not in installed.stdout:
            raise SmokeProofError("installer did not report its completed install-only proof")

        # The skill is the product; a release whose installer leaves it behind
        # installs a command with nothing to drive it.
        skill_file = skills_home / "dex-lens" / "SKILL.md"
        if not skill_file.is_file() or not skill_file.read_text(encoding="utf-8").strip():
            raise SmokeProofError("installer did not place the Dex Lens skill")

        command = bin_home / "dex-lens"
        launched = subprocess.run(  # noqa: S603 - newly installed exact release command
            [str(command), "--help"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        if launched.returncode != 0 or "Choosing a folder does not scan it" not in launched.stdout:
            raise SmokeProofError("installed Dex Lens command lacked the reviewed folder doorway")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove the exact public Dex Lens installer.")
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--installer", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        run_smoke_proof(artifacts=args.artifacts, installer=args.installer)
    except SmokeProofError as exc:
        print(f"Dex Lens release smoke proof failed: {exc}", file=sys.stderr)
        return 2
    print(f"Dex Lens release smoke proof passed for {_expected_target()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
