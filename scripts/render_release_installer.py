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

dex_lens_step() {{
  printf '  %s\\n' "$*"
}}

# This installer is pasted from a web page, and that page documents two
# options, so the two options have to exist here: one that says what would
# happen and does none of it, one that says what the options are. Both are
# answered before a single byte is fetched or written; anything else stops.
DEX_LENS_DRY_RUN=0

usage() {{
  printf '%s\\n' \\
    "Dex Lens installer, signed release $DEX_LENS_VERSION." \\
    "" \\
    "  --dry-run   Say exactly what would happen and change nothing." \\
    "  --help      This text." \\
    "" \\
    "Environment overrides, for people who keep things elsewhere:" \\
    "  DEX_LENS_DATA_HOME    where the private install lives" \\
    "  DEX_LENS_BIN_HOME     where the dex-lens command is linked (default ~/.local/bin)" \\
    "  DEX_LENS_SKILLS_DIR   where the skill is placed (default ~/.claude/skills)" \\
    "  DEX_LENS_NO_PING=1    send no first-install note" \\
    "  DEX_LENS_NO_LAUNCH=1  never start your assistant at the end" \\
    "  DEX_LENS_PREFERRED_ASSISTANT=claude|codex  choose when both are installed"
}}

for dex_lens_argument in "$@"; do
  case "$dex_lens_argument" in
    --dry-run) DEX_LENS_DRY_RUN=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "I do not understand the option '$dex_lens_argument'. Try --help." ;;
  esac
done

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

# Running this installer is permission to update a command that can be proven
# to belong to Dex Lens. The earlier source installer used one exact target;
# signed releases use the versioned root above. Everything else remains
# untouched. Decide before the dry run and before any download or write, so
# both paths make the same ownership promise.
DEX_LENS_LEGACY_SOURCE_ROOT="$HOME/.local/share/dex-lens"
DEX_LENS_LEGACY_SOURCE_TARGET="$DEX_LENS_LEGACY_SOURCE_ROOT/venv/bin/dex-lens"
DEX_LENS_LAUNCHER_STATE="absent"
DEX_LENS_EXISTING_TARGET=""
if [ -L "$DEX_LENS_LAUNCHER" ]; then
  DEX_LENS_EXISTING_TARGET="$(readlink "$DEX_LENS_LAUNCHER")"
  case "$DEX_LENS_EXISTING_TARGET" in
    "$DEX_LENS_DATA_HOME/dex-lens/versions/"*)
      DEX_LENS_LAUNCHER_STATE="signed"
      ;;
    "$DEX_LENS_LEGACY_SOURCE_TARGET")
      DEX_LENS_LAUNCHER_STATE="legacy-source"
      ;;
    *)
      die "Dex Lens found $DEX_LENS_LAUNCHER pointing to \\
$DEX_LENS_EXISTING_TARGET. It cannot prove that command belongs to Lens, so \\
it will not overwrite it. Nothing was downloaded or changed."
      ;;
  esac
elif [ -e "$DEX_LENS_LAUNCHER" ]; then
  die "Dex Lens found an existing command at $DEX_LENS_LAUNCHER. It cannot \\
prove that command belongs to Lens, so it will not overwrite it. Nothing was \\
downloaded or changed."
fi

if [ "$DEX_LENS_LAUNCHER_STATE" = "legacy-source" ]; then
  printf '%s\\n' \\
    "It looks like you used Dex Lens before." \\
    "Because you ran this installer, Dex Lens will update its command and" \\
    "skill to the signed release." \\
    "Your earlier private copy at $DEX_LENS_LEGACY_SOURCE_ROOT" \\
    "will be left in place, so the previous command can be restored if needed." \\
    ""
fi

# One marker shared with the source installer, so a machine that runs both
# still sends exactly one note, ever.
DEX_LENS_PING_STATE_DIR="${{XDG_STATE_HOME:-$HOME/.local/state}}/dex-lens"
DEX_LENS_PING_MARKER="$DEX_LENS_PING_STATE_DIR/.install-recorded"

# The skill goes wherever an assistant will actually look: Claude Code's home
# always, and the homes Codex and the shared ~/.agents convention read only
# when those already exist, because creating them would claim this machine
# uses a tool it does not. DEX_LENS_SKILLS_DIR overrides everything with one
# explicit place. Decided once, here, so the dry run below cannot name a
# different set of homes than the install itself writes.
DEX_LENS_SKILL_HOMES=""
if [ -n "${{DEX_LENS_SKILLS_DIR:-}}" ]; then
  case "$DEX_LENS_SKILLS_DIR" in
    /*) ;;
    *) die "Dex Lens needs an absolute skills folder; the skill was not placed." ;;
  esac
  DEX_LENS_SKILL_HOMES="$DEX_LENS_SKILLS_DIR
"
else
  DEX_LENS_SKILL_HOMES="$HOME/.claude/skills
"
  # The Codex home also counts as present when the `codex` command exists:
  # a machine that can launch Codex must never launch it blind to the skill.
  if [ -d "$HOME/.codex" ] || command -v codex >/dev/null 2>&1; then
    DEX_LENS_SKILL_HOMES="$DEX_LENS_SKILL_HOMES$HOME/.codex/skills
"
  fi
  if [ -d "$HOME/.agents" ]; then
    DEX_LENS_SKILL_HOMES="$DEX_LENS_SKILL_HOMES$HOME/.agents/skills
"
  fi
fi

# Whichever assistant this machine actually has gets the hand-over. A terminal
# cannot know which one a person intends when Claude Code and Codex both exist,
# so that one case gets a one-key choice rather than silently preferring one.
# Decided here so the dry run can name the ending a real run would reach.
DEX_LENS_ASSISTANT=""
DEX_LENS_CLAUDE_AVAILABLE=0
DEX_LENS_CODEX_AVAILABLE=0
if command -v claude >/dev/null 2>&1; then
  DEX_LENS_CLAUDE_AVAILABLE=1
fi
if command -v codex >/dev/null 2>&1; then
  DEX_LENS_CODEX_AVAILABLE=1
fi
if [ "$DEX_LENS_CLAUDE_AVAILABLE" -eq 1 ] && [ "$DEX_LENS_CODEX_AVAILABLE" -eq 1 ]; then
  DEX_LENS_ASSISTANT="choose"
elif [ "$DEX_LENS_CLAUDE_AVAILABLE" -eq 1 ]; then
  DEX_LENS_ASSISTANT="claude"
elif [ "$DEX_LENS_CODEX_AVAILABLE" -eq 1 ]; then
  DEX_LENS_ASSISTANT="codex"
fi

if [ "$DEX_LENS_DRY_RUN" = "1" ]; then
  printf '%s\\n' \\
    "" \\
    "This is a dry run. Nothing below has happened, and nothing has changed." \\
    "" \\
    "What a real run would do:"
  dex_lens_step \\
    "download the signed $DEX_LENS_TARGET release from $DEX_LENS_RELEASE_URL into a \\
temporary folder under ${{TMPDIR:-/tmp}}, and delete that folder again"
  dex_lens_step \\
    "refuse all of it unless the manifest verifies against the public key inside \\
this installer and the bundle matches its checksum"
  if [ -x "$DEX_LENS_VENV/bin/dex-lens" ]; then
    dex_lens_step "leave the Dex Lens $DEX_LENS_VERSION already installed in \\
$DEX_LENS_INSTALL_ROOT exactly as it is"
  elif [ -e "$DEX_LENS_INSTALL_ROOT" ]; then
    dex_lens_step "stop, leaving the part-finished install at $DEX_LENS_INSTALL_ROOT untouched"
  else
    dex_lens_step "install Dex Lens $DEX_LENS_VERSION into $DEX_LENS_INSTALL_ROOT, \\
in its own copy of Python that nothing else uses"
  fi
  dex_lens_step "link the dex-lens command into $DEX_LENS_LAUNCHER"
  while IFS= read -r dex_lens_skill_home; do
    [ -n "$dex_lens_skill_home" ] || continue
    dex_lens_step "put the Dex Lens skill in $dex_lens_skill_home/dex-lens"
  done <<DEX_LENS_SKILL_PLAN
$DEX_LENS_SKILL_HOMES
DEX_LENS_SKILL_PLAN
  # The dry run must name every path a real run would write, under the same
  # gates the real run uses — an honesty feature that overstates is not one.
  if [ "${{DEX_LENS_INSTALL_ONLY:-0}}" != "1" ] &&
    [ "${{DEX_LENS_NO_PING:-0}}" != "1" ] && [ ! -f "$DEX_LENS_PING_MARKER" ]; then
    dex_lens_step "record the install in $DEX_LENS_PING_STATE_DIR, so this machine \\
never sends a second note"
    dex_lens_step "send one anonymous first-install note to heydex.ai (version and \\
machine type only; DEX_LENS_NO_PING=1 disables)"
  fi
  # How a real run ends is a change to this terminal, so it is named too.
  if [ "${{DEX_LENS_INSTALL_ONLY:-0}}" = "1" ]; then
    dex_lens_step "stop there, because DEX_LENS_INSTALL_ONLY=1 asks for the install alone"
  elif [ "$DEX_LENS_ASSISTANT" = "choose" ]; then
    dex_lens_step "ask you to choose Claude Code or Codex before starting the conversation"
  elif [ "${{DEX_LENS_NO_LAUNCH:-0}}" != "1" ] && [ -n "$DEX_LENS_ASSISTANT" ] &&
    [ -t 0 ]; then
    dex_lens_step "hand this terminal over to your assistant ($DEX_LENS_ASSISTANT) \\
with the first question already asked, replacing this shell"
  elif [ -n "$DEX_LENS_ASSISTANT" ]; then
    dex_lens_step "print the one line to paste that starts your assistant \\
($DEX_LENS_ASSISTANT) with the first question"
  else
    dex_lens_step "print the question to ask your assistant, since neither Claude \\
Code nor Codex is on this machine"
  fi
  printf '%s\\n' \\
    "" \\
    "It would not read, change, or send anything about the AI system you" \\
    "later ask Lens to look at."
  exit 0
fi

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
  "$DEX_LENS_VENV/bin/python" -m pip install --quiet --no-index \\
    --find-links "$DEX_LENS_WHEELHOUSE" \\
    --only-binary=:all: "capability_exchange==$DEX_LENS_VERSION" \\
    || die "Dex Lens could not install the verified release bundle. Nothing was left running."
  "$DEX_LENS_VENV/bin/dex-lens" --help >/dev/null \\
    || die "Dex Lens installed but did not pass its local startup check."
  DEX_LENS_NEW_INSTALL=0
fi

mkdir -p "$DEX_LENS_BIN_HOME"
ln -sfn "$DEX_LENS_VENV/bin/dex-lens" "$DEX_LENS_LAUNCHER"

# The skill is the product: the file the person's own assistant reads to run
# a diagnosis. It ships inside the verified wheel, so what lands here is
# covered by the same signature as everything else — it is copied out of the
# installed package, never downloaded separately. Which homes it lands in was
# decided above, before anything was written, so the dry run and the install
# cannot disagree about where the skill goes.
DEX_LENS_PLACED=""

place_lens_skill() {{
  skill_home="$1/dex-lens"
  mkdir -p "$skill_home"
  "$DEX_LENS_VENV/bin/python" - "$skill_home" <<'PY'
import sys
from importlib.resources import files
from pathlib import Path

# Place every file the skill ships with, not only SKILL.md: the skill reads a
# bundled capability reference next to it, and a copy that took only SKILL.md
# left that reference behind, so the skill silently fell back to a skills-only
# comparison. Copy the whole directory the wheel carries.
dest = Path(sys.argv[1])
source = files("capability_exchange").joinpath("skill/dex-lens")
placed = 0
for entry in source.iterdir():
    if entry.is_file():
        (dest / entry.name).write_bytes(entry.read_bytes())
        placed += 1
if placed == 0:
    raise SystemExit("no Dex Lens skill files were found in the installed package")
PY
  test -s "$skill_home/SKILL.md" \\
    || die "Dex Lens installed but its skill did not land in $skill_home."
  test -s "$skill_home/dex-capabilities.json" \\
    || die "Dex Lens installed but its capability reference did not land in $skill_home."
  DEX_LENS_PLACED="$DEX_LENS_PLACED$skill_home
"
}}

while IFS= read -r dex_lens_skill_home; do
  [ -n "$dex_lens_skill_home" ] || continue
  place_lens_skill "$dex_lens_skill_home"
done <<DEX_LENS_SKILL_HOMES_LIST
$DEX_LENS_SKILL_HOMES
DEX_LENS_SKILL_HOMES_LIST

# One anonymous "someone installed this" note: sent once, the first time an
# install on this machine succeeds, and declared on the page in these same
# words — the Lens version and machine type, nothing else. Never during the
# install-only proof, never on a re-run (the marker), never if the person
# set DEX_LENS_NO_PING=1, and a failed note never fails an install.
# One marker shared with the source installer, so a machine that runs both
# still sends exactly one note, ever.
DEX_LENS_PINGED=0
DEX_LENS_PING_STATE_DIR_CREATED=0
if [ "${{DEX_LENS_INSTALL_ONLY:-0}}" != "1" ] && \\
  [ "${{DEX_LENS_NO_PING:-0}}" != "1" ] && [ ! -f "$DEX_LENS_PING_MARKER" ]; then
  # Created before the note is even attempted, so it is a change this machine
  # keeps whether or not the note reaches anywhere. It is named below.
  [ -d "$DEX_LENS_PING_STATE_DIR" ] || DEX_LENS_PING_STATE_DIR_CREATED=1
  mkdir -p "$DEX_LENS_PING_STATE_DIR"
  if curl -fsS --max-time 3 -X POST https://heydex.ai/lens/installed \\
    -H "Content-Type: application/json" \\
    -d "{{\"lens_version\":\"$DEX_LENS_VERSION\",\"target\":\"$DEX_LENS_TARGET\"}}" \\
    >/dev/null 2>&1; then
    touch "$DEX_LENS_PING_MARKER"
    DEX_LENS_PINGED=1
  fi || true
fi

printf '%s\\n' "Dex Lens is installed privately in $DEX_LENS_INSTALL_ROOT."
printf '%s\\n' "The dex-lens command is at $DEX_LENS_LAUNCHER."
printf '%s' "$DEX_LENS_PLACED" | while IFS= read -r lens_placed_line; do
  [ -n "$lens_placed_line" ] && printf '%s\\n' "The Dex Lens skill is in $lens_placed_line."
done
if [ "$DEX_LENS_LAUNCHER_STATE" = "legacy-source" ]; then
  printf '%s\\n' \\
    "Your earlier private copy is still in $DEX_LENS_LEGACY_SOURCE_ROOT for rollback."
fi
if [ "$DEX_LENS_PING_STATE_DIR_CREATED" = "1" ]; then
  printf '%s\\n' \\
    "The record that this machine has already been counted is in $DEX_LENS_PING_STATE_DIR."
fi
if [ "$DEX_LENS_PINGED" = "1" ]; then
  printf '%s\\n' \\
    "One anonymous note went to heydex.ai: that an install happened, the" \\
    "version, and the machine type. Nothing else, and never again from this" \\
    "machine. DEX_LENS_NO_PING=1 would have switched it off."
fi
printf '%s\\n' ""
printf '%s\\n' \\
  "Nothing has been read yet: Dex Lens looks at nothing until you ask it to," \\
  "and it never changes what it looks at."

# A command nobody's shell can find is not installed as far as the person is
# concerned, and the very next thing this installer prints is a line that
# calls it by name. Say so, in the words that fix it.
case ":$PATH:" in
  *":$DEX_LENS_BIN_HOME:"*) ;;
  *)
    printf '%s\\n' \\
      "" \\
      "One thing to fix. Your computer keeps a list of the places it looks for" \\
      "commands, and $DEX_LENS_BIN_HOME is not on it yet, so the command is" \\
      "installed but not findable. Add this line to the end of the file your" \\
      "terminal reads at startup (~/.zshrc on most Macs):" \\
      ""
    printf '  export PATH="%s:$PATH"\\n' "$DEX_LENS_BIN_HOME"
    ;;
esac
if [ "${{DEX_LENS_INSTALL_ONLY:-0}}" = "1" ]; then
  printf '%s\\n' "Install-only check complete; Dex Lens was not started."
  exit 0
fi
rm -rf "$DEX_LENS_TMP"
trap - EXIT

# One pasted line should end as close to the conversation as it honestly
# can. Run from a file with a real keyboard, hand straight over. Piped from
# curl, say how to rerun the installer with the keyboard still attached — a
# full-screen assistant started from a piped script comes up deaf.
DEX_LENS_ASK="Use Dex Lens to have a look at my setup and tell me what Dex has that I don't."
choose_assistant() {{
  if [ "$DEX_LENS_ASSISTANT" != "choose" ]; then
    return
  fi

  case "${{DEX_LENS_PREFERRED_ASSISTANT:-}}" in
    claude | codex)
      DEX_LENS_ASSISTANT="$DEX_LENS_PREFERRED_ASSISTANT"
      return
      ;;
    "") ;;
    *)
      die "DEX_LENS_PREFERRED_ASSISTANT must be claude or codex. Nothing was started."
      ;;
  esac

  printf '%s\\n' "I found both Claude Code and Codex. Which would you like to open?"
  while :; do
    printf '%s' "  1) Claude Code   2) Codex [1]: "
    IFS= read -r dex_lens_choice || die "No choice was received. Nothing was started."
    case "$dex_lens_choice" in
      "" | 1 | claude | Claude | "Claude Code")
        DEX_LENS_ASSISTANT="claude"
        return
        ;;
      2 | codex | Codex)
        DEX_LENS_ASSISTANT="codex"
        return
        ;;
      *) printf '%s\\n' "Please type 1 for Claude Code or 2 for Codex." ;;
    esac
  done
}}
# Hand over only when this script already owns a real keyboard — running
# from a file, not piped from curl. The first outside tester proved why:
# exec-ing a full-screen assistant out of a piped script left it running but
# deaf, the report printed and every keystroke dead. When stdin is the pipe,
# the honest hand-over is the exact command, ready to paste.
if [ "${{DEX_LENS_NO_LAUNCH:-0}}" != "1" ] && [ -n "$DEX_LENS_ASSISTANT" ] && [ -t 0 ]; then
  choose_assistant
  printf '%s\\n' \\
    "Starting your assistant now. Dex Lens reads nothing until you tell it" \\
    "which folder it may look at."
  # The assistant will call `dex-lens` by name; on a fresh machine its folder
  # may not be on PATH yet. The launched process gets it either way.
  export PATH="$DEX_LENS_BIN_HOME:$PATH"
  exec "$DEX_LENS_ASSISTANT" "$DEX_LENS_ASK"
fi
printf '%s\\n' ""
if [ -n "$DEX_LENS_ASSISTANT" ]; then
  printf '%s\\n' \\
    "This installer was run through a pipe, so it cannot safely open an" \\
    "interactive assistant here."
  printf '%s\\n' "Run this one line to start directly with your keyboard attached:"
  printf '%s\\n' ""
  printf '%s\\n' "  bash <(curl -fsSL https://heydex.ai/lens)"
else
  printf '%s\\n' "Now open your assistant and ask, in your own words:"
  printf '%s\\n' "  Have a look at my setup and tell me what Dex has that I don't."
fi
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
