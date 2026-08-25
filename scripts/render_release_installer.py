#!/usr/bin/env python3
"""Render the version-specific, signed public Mac/Linux Dex Lens installer."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.release_bundle import (  # noqa: E402 - direct workflow script needs repository root first
    ReleaseManifest,
    ReleaseValidationError,
    parse_manifest_bytes,
)


class InstallerRenderError(ReleaseValidationError):
    """The release inputs cannot safely become a public installer."""


def _validate_release_url(release_url: str, version: str) -> str:
    parsed = urlparse(release_url)
    expected_suffix = f"/v{version}"
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith(expected_suffix)
    ):
        raise InstallerRenderError(
            "release URL must be an HTTPS versioned release endpoint ending in "
            f"{expected_suffix}"
        )
    return release_url.rstrip("/")


def _validate_public_key(public_key_pem: bytes) -> str:
    try:
        key = serialization.load_pem_public_key(public_key_pem)
        text = public_key_pem.decode("ascii")
    except (TypeError, UnicodeDecodeError, ValueError) as exc:
        raise InstallerRenderError("installer public key must be PEM-encoded P-256") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise InstallerRenderError("installer public key must use ECDSA P-256")
    if not text.endswith("\n"):
        raise InstallerRenderError("installer public key PEM must end with a newline")
    return text


def render_installer(
    *, manifest: ReleaseManifest, release_url: str, public_key_pem: bytes
) -> str:
    """Return a version-specific Bash installer with an embedded public key only."""
    url = _validate_release_url(release_url, manifest.version)
    public_key = _validate_public_key(public_key_pem).rstrip("\n")
    quoted_version = shlex.quote(manifest.version)
    quoted_url = shlex.quote(url)

    return f'''#!/usr/bin/env bash
set -euo pipefail

DEX_LENS_VERSION={quoted_version}
DEX_LENS_RELEASE_URL={quoted_url}

die() {{
  printf '%s\\n' "Dex Lens installer stopped: $*" >&2
  exit 1
}}

for tool in curl openssl; do
  command -v "$tool" >/dev/null 2>&1 || die "This installer needs $tool. Nothing was installed."
done

SYSTEM_NAME="$(uname -s)"
case "$SYSTEM_NAME" in
  Darwin)
    case "$(uname -m)" in
      arm64) DEX_LENS_TARGET="macos-arm64" ;;
      x86_64) die "This first signed release supports Apple Silicon Macs. \\
Intel Macs can use the source-build guide." ;;
      *) die "This Mac processor is not supported by this signed release." ;;
    esac
    ;;
  Linux)
    case "$(uname -m)" in
      x86_64|amd64) DEX_LENS_TARGET="linux-x86_64" ;;
      aarch64|arm64) die "Linux ARM is not in this first signed release. \\
Use the source-build guide." ;;
      *) die "This Linux processor is not supported by this signed release." ;;
    esac
    ;;
  MINGW*|MSYS*|CYGWIN*)
    die "Windows Preview is being built separately. \\
This Mac/Linux installer has not downloaded anything."
    ;;
  *) die "This installer supports macOS Apple Silicon and Linux x86_64 only." ;;
esac

DEX_LENS_PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" - <<'PY'
import sys

raise SystemExit(not ((3, 11) <= sys.version_info[:2] <= (3, 14)))
PY
  then
    DEX_LENS_PYTHON="$(command -v "$candidate")"
    break
  fi
done
[ -n "$DEX_LENS_PYTHON" ] || die \
  "Dex Lens needs Python 3.11 through 3.14. Install it from \
https://www.python.org/downloads/, then paste the same Dex Lens install command again. \
Nothing was installed."

[ -n "${{HOME:-}}" ] || die \\
  "Your home folder is unavailable, so Dex Lens cannot create its private install folder."
DEX_LENS_TMP="$(mktemp -d "${{TMPDIR:-/tmp}}/dex-lens-install.XXXXXX")" \\
  || die "Could not create a private temporary folder."
trap 'rm -rf "$DEX_LENS_TMP"' EXIT

DEX_LENS_MANIFEST="$DEX_LENS_TMP/release-manifest.json"
DEX_LENS_SIGNATURE="$DEX_LENS_TMP/release-manifest.sig"
DEX_LENS_PUBLIC_KEY="$DEX_LENS_TMP/release-public-key.pem"
DEX_LENS_ARCHIVE="$DEX_LENS_TMP/release.tar.gz"
DEX_LENS_WHEELHOUSE="$DEX_LENS_TMP/wheelhouse"

curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \\
  --output "$DEX_LENS_MANIFEST" "$DEX_LENS_RELEASE_URL/release-manifest.json"
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \\
  --output "$DEX_LENS_SIGNATURE" "$DEX_LENS_RELEASE_URL/release-manifest.sig"

cat > "$DEX_LENS_PUBLIC_KEY" <<'DEX_LENS_PUBLIC_KEY'
{public_key}
DEX_LENS_PUBLIC_KEY

openssl dgst -sha256 -verify "$DEX_LENS_PUBLIC_KEY" \\
  -signature "$DEX_LENS_SIGNATURE" "$DEX_LENS_MANIFEST" >/dev/null 2>&1 \\
  || die "Dex Lens could not verify this release. Nothing was installed."

DEX_LENS_SELECTION="$(
"$DEX_LENS_PYTHON" - "$DEX_LENS_MANIFEST" "$DEX_LENS_VERSION" "$DEX_LENS_TARGET" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path, version, target = map(Path, sys.argv[1:])
version_text = str(version)
target_text = str(target)
try:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset = document["assets"][target_text]
    filename = asset["filename"]
    digest = asset["sha256"]
except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
    raise SystemExit(f"unsafe signed release manifest: {{error}}")
expected_name = f"dex-lens-v{{version_text}}-{{target_text}}.tar.gz"
if filename != expected_name or not re.fullmatch(r"[0-9a-f]{{64}}", digest):
    raise SystemExit("unsafe signed release asset")
print(filename, digest)
PY
)" || die "The signed release manifest did not name a safe bundle for this computer."

IFS=' ' read -r DEX_LENS_FILENAME DEX_LENS_EXPECTED_SHA256 <<< "$DEX_LENS_SELECTION"
[ "$DEX_LENS_FILENAME" = "dex-lens-v$DEX_LENS_VERSION-$DEX_LENS_TARGET.tar.gz" ] \\
  || die "The signed release named an unexpected bundle."
[ -n "${{DEX_LENS_EXPECTED_SHA256:-}}" ] || die "The signed release omitted its checksum."

curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \\
  --output "$DEX_LENS_ARCHIVE" "$DEX_LENS_RELEASE_URL/$DEX_LENS_FILENAME"
DEX_LENS_ACTUAL_SHA256="$("$DEX_LENS_PYTHON" - "$DEX_LENS_ARCHIVE" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as archive:
    while chunk := archive.read(1024 * 1024):
        digest.update(chunk)
print(digest.hexdigest())
PY
)"
[ "$DEX_LENS_ACTUAL_SHA256" = "$DEX_LENS_EXPECTED_SHA256" ] \\
  || die "Dex Lens refused a bundle whose checksum changed. Nothing was installed."

"$DEX_LENS_PYTHON" - "$DEX_LENS_ARCHIVE" "$DEX_LENS_WHEELHOUSE" <<'PY' \\
  || die "Dex Lens refused an unsafe release archive. Nothing was installed."
import tarfile
import sys
from pathlib import Path, PurePosixPath

archive_path = Path(sys.argv[1])
wheelhouse = Path(sys.argv[2])
wheelhouse.mkdir(parents=True, exist_ok=False)
seen = set()
with tarfile.open(archive_path, "r:gz") as archive:
    members = archive.getmembers()
    if not members:
        raise SystemExit("release archive is empty")
    for member in members:
        parts = PurePosixPath(member.name).parts
        if (
            not member.isfile()
            or len(parts) != 2
            or parts[0] != "wheelhouse"
            or not parts[1].endswith(".whl")
            or parts[1] in seen
        ):
            raise SystemExit(f"unsafe archive member: {{member.name!r}}")
        seen.add(parts[1])
        source = archive.extractfile(member)
        if source is None:
            raise SystemExit(f"could not read archive member: {{member.name!r}}")
        with source, (wheelhouse / parts[1]).open("xb") as destination:
            while chunk := source.read(1024 * 1024):
                destination.write(chunk)
PY

case "$DEX_LENS_TARGET" in
  macos-arm64) DEX_LENS_DEFAULT_DATA_HOME="$HOME/Library/Application Support" ;;
  linux-x86_64) DEX_LENS_DEFAULT_DATA_HOME="$HOME/.local/share" ;;
esac
DEX_LENS_DATA_HOME="${{DEX_LENS_DATA_HOME:-$DEX_LENS_DEFAULT_DATA_HOME}}"
case "$DEX_LENS_DATA_HOME" in
  /*) ;;
  *) die "Dex Lens needs an absolute private install folder. Nothing was installed." ;;
esac
DEX_LENS_INSTALL_ROOT="$DEX_LENS_DATA_HOME/dex-lens/versions/v$DEX_LENS_VERSION"
DEX_LENS_VENV="$DEX_LENS_INSTALL_ROOT/venv"
DEX_LENS_BIN_HOME="${{DEX_LENS_BIN_HOME:-$HOME/.local/bin}}"
case "$DEX_LENS_BIN_HOME" in
  /*) ;;
  *) die "Dex Lens needs an absolute command folder. Nothing was installed." ;;
esac
DEX_LENS_LAUNCHER="$DEX_LENS_BIN_HOME/dex-lens"
DEX_LENS_NEW_INSTALL=0

cleanup_install() {{
  status="$?"
  trap - EXIT
  rm -rf "$DEX_LENS_TMP"
  if [ "$DEX_LENS_NEW_INSTALL" = "1" ]; then
    if "$DEX_LENS_PYTHON" - \\
      "$DEX_LENS_INSTALL_ROOT" "$DEX_LENS_DATA_HOME" "$DEX_LENS_VERSION" <<'PY'
import shutil
import sys
from pathlib import Path

install_root = Path(sys.argv[1])
expected_root = Path(sys.argv[2]) / "dex-lens" / "versions" / f"v{{sys.argv[3]}}"
if install_root != expected_root or install_root.is_symlink():
    raise SystemExit("refusing to clean an unexpected install path")
if install_root.exists():
    shutil.rmtree(install_root)
PY
    then
      printf '%s\\n' "A partial install from this run was removed safely."
    else
      printf '%s\\n' \\
        "Dex Lens could not verify cleanup of its partial install at $DEX_LENS_INSTALL_ROOT." >&2
    fi
  fi
  exit "$status"
}}
trap cleanup_install EXIT

if [ -x "$DEX_LENS_VENV/bin/dex-lens" ]; then
  printf '%s\\n' "Verified Dex Lens $DEX_LENS_VERSION is already installed."
elif [ -e "$DEX_LENS_INSTALL_ROOT" ]; then
  die "A partial Dex Lens install already exists at $DEX_LENS_INSTALL_ROOT. It was left untouched."
else
  mkdir -p "$DEX_LENS_INSTALL_ROOT"
  DEX_LENS_NEW_INSTALL=1
  "$DEX_LENS_PYTHON" -m venv "$DEX_LENS_VENV"
  "$DEX_LENS_VENV/bin/python" -m pip install --no-index --find-links "$DEX_LENS_WHEELHOUSE" \\
    --only-binary=:all: "capability_exchange==$DEX_LENS_VERSION"
  "$DEX_LENS_VENV/bin/dex-lens" --help >/dev/null \\
    || die "Dex Lens installed but did not pass its local startup check."
  DEX_LENS_NEW_INSTALL=0
fi

mkdir -p "$DEX_LENS_BIN_HOME"
if [ -L "$DEX_LENS_LAUNCHER" ]; then
  DEX_LENS_EXISTING_TARGET="$(readlink "$DEX_LENS_LAUNCHER")"
  case "$DEX_LENS_EXISTING_TARGET" in
    "$DEX_LENS_DATA_HOME/dex-lens/versions/"*) ;;
    *) die "Refusing to replace a Dex Lens command owned by something else." ;;
  esac
elif [ -e "$DEX_LENS_LAUNCHER" ]; then
  die "Refusing to replace an existing command at $DEX_LENS_LAUNCHER."
fi
ln -sfn "$DEX_LENS_VENV/bin/dex-lens" "$DEX_LENS_LAUNCHER"

# The skill is the product: the file the person's own assistant reads to run
# a diagnosis. It ships inside the verified wheel, so what lands here is
# covered by the same signature as everything else — it is copied out of the
# installed package, never downloaded separately.
DEX_LENS_SKILLS_DIR="${{DEX_LENS_SKILLS_DIR:-$HOME/.claude/skills}}"
case "$DEX_LENS_SKILLS_DIR" in
  /*) ;;
  *) die "Dex Lens needs an absolute skills folder. The command is installed; the skill is not." ;;
esac
DEX_LENS_SKILL_HOME="$DEX_LENS_SKILLS_DIR/dex-lens"
mkdir -p "$DEX_LENS_SKILL_HOME"
"$DEX_LENS_VENV/bin/python" - "$DEX_LENS_SKILL_HOME/SKILL.md" <<'PY'
import sys
from importlib.resources import files
from pathlib import Path

skill = files("capability_exchange").joinpath("skill/dex-lens/SKILL.md").read_text(encoding="utf-8")
Path(sys.argv[1]).write_text(skill, encoding="utf-8")
PY
test -s "$DEX_LENS_SKILL_HOME/SKILL.md" \\
  || die "Dex Lens installed but its skill did not land in $DEX_LENS_SKILL_HOME."

printf '%s\\n' "Dex Lens is installed privately in $DEX_LENS_INSTALL_ROOT."
printf '%s\\n' "The Dex Lens skill is in $DEX_LENS_SKILL_HOME."
printf '%s\\n' ""
printf '%s\\n' "Now open Claude Code and ask, in your own words:"
printf '%s\\n' "  Have a look at my setup and tell me what Dex has that I do not."
printf '%s\\n' ""
printf '%s\\n' \\
  "Nothing has been read yet: Dex Lens looks at nothing until you ask it to," \\
  "and it never changes what it looks at."
if [ "${{DEX_LENS_INSTALL_ONLY:-0}}" = "1" ]; then
  printf '%s\\n' "Install-only check complete; Dex Lens was not started."
  exit 0
fi
rm -rf "$DEX_LENS_TMP"
trap - EXIT
'''


def _read_manifest(path: Path) -> ReleaseManifest:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise InstallerRenderError(f"release manifest is missing: {path}") from exc
    manifest = parse_manifest_bytes(raw)
    if raw != manifest.to_bytes():
        raise InstallerRenderError("release manifest must use exact canonical signed bytes")
    return manifest


def _write_new_text(path: Path, content: str) -> None:
    if path.exists():
        raise InstallerRenderError(f"refusing to overwrite existing installer: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the signed public Dex Lens installer.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--release-url", required=True)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        manifest = _read_manifest(args.manifest)
        public_key = args.public_key.read_bytes()
        installer = render_installer(
            manifest=manifest,
            release_url=args.release_url,
            public_key_pem=public_key,
        )
        _write_new_text(args.output, installer)
    except (FileNotFoundError, InstallerRenderError, ReleaseValidationError) as exc:
        print(f"Dex Lens installer rendering refused: {exc}", file=sys.stderr)
        return 2
    print(f"rendered signed Dex Lens installer for {manifest.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
