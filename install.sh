#!/usr/bin/env bash
#
# Dex Lens installer.
#
# One action, from nothing installed to ready to ask. It puts the `dex-lens`
# command somewhere your shell can find it, and puts the Dex Lens skill where
# Claude Code looks for skills. It reads your machine to check the pieces it
# needs; it does not read, change, or send anything about the AI system you
# will later ask Lens to look at.
#
#   curl -fsSL https://raw.githubusercontent.com/davekilleen/dex-lens/main/install.sh | bash
#
# Run it again any time to update: it is safe to repeat, and says what it did
# rather than what it intended to do.
#
# Options:
#   --dry-run   Say exactly what would happen and change nothing.
#   --help      This text.
#
# Environment overrides, for people who keep things elsewhere:
#   DEX_LENS_HOME        where the private copy lives (default ~/.local/share/dex-lens)
#   DEX_LENS_BIN         where the `dex-lens` command is linked (default ~/.local/bin)
#   DEX_LENS_SKILLS_DIR  where skills live (default ~/.claude/skills)
#   DEX_LENS_REPO        the source to install from (default the public repository)

set -euo pipefail

readonly REPO_URL="${DEX_LENS_REPO:-https://github.com/davekilleen/dex-lens.git}"
readonly LENS_HOME="${DEX_LENS_HOME:-$HOME/.local/share/dex-lens}"
readonly BIN_DIR="${DEX_LENS_BIN:-$HOME/.local/bin}"
readonly SKILLS_DIR="${DEX_LENS_SKILLS_DIR:-$HOME/.claude/skills}"
readonly SOURCE_DIR="$LENS_HOME/source"
readonly VENV_DIR="$LENS_HOME/venv"
readonly SKILL_DEST="$SKILLS_DIR/dex-lens"
readonly MIN_PYTHON="3.11"

DRY_RUN=0

say() { printf '%s\n' "$*"; }
step() { printf '  %s\n' "$*"; }

# Failure has to be as clear as success. A half-finished install that says
# nothing is how someone ends up with a `dex-lens` command that is not there.
fail() {
  printf '\nDex Lens could not finish installing.\n\n  %s\n\n' "$*" >&2
  printf 'Nothing was left running. You can re-run this installer safely.\n' >&2
  exit 1
}

usage() {
  sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
}

for argument in "$@"; do
  case "$argument" in
    --dry-run) DRY_RUN=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) fail "I do not understand the option '$argument'. Try --help." ;;
  esac
done

# --- 1. Python -------------------------------------------------------------
find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
        >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON="$(find_python)" || fail \
  "Dex Lens needs Python $MIN_PYTHON or newer, and I could not find it. On a Mac: brew install python@3.13"

PYTHON_VERSION="$("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

say ""
say "Dex Lens"
say "========"
say ""
say "Found Python $PYTHON_VERSION at $PYTHON"

if [ "$DRY_RUN" -eq 1 ]; then
  say ""
  say "This is a dry run. Nothing below has happened, and nothing has changed."
  say ""
  say "What a real run would do:"
  step "keep a private copy of Dex Lens in $SOURCE_DIR"
  step "set up its own copy of Python in $VENV_DIR, so it cannot disturb anything else"
  step "link the dex-lens command into $BIN_DIR"
  step "put the Dex Lens skill in $SKILL_DEST"
  say ""
  say "It would not read, change, or send anything about the AI system you"
  say "later ask Lens to look at."
  exit 0
fi

# --- 2. The source ---------------------------------------------------------
# Running from a clone (a developer, or someone who downloaded the repository)
# installs that clone. Piped from the web there is no clone, so fetch one.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -d "$SCRIPT_DIR/skill/dex-lens" ]; then
  INSTALL_FROM="$SCRIPT_DIR"
  say "Installing from this copy: $INSTALL_FROM"
else
  command -v git >/dev/null 2>&1 ||
    fail "Dex Lens needs git to download itself. Install git and run this again."
  mkdir -p "$LENS_HOME"
  if [ -d "$SOURCE_DIR/.git" ]; then
    say "Updating the copy in $SOURCE_DIR"
    git -C "$SOURCE_DIR" fetch --quiet origin ||
      fail "I could not reach $REPO_URL. Check the network and run this again."
    git -C "$SOURCE_DIR" reset --quiet --hard origin/HEAD ||
      fail "The copy in $SOURCE_DIR could not be updated. Remove that folder and run this again."
  else
    say "Downloading Dex Lens into $SOURCE_DIR"
    git clone --quiet --depth 1 "$REPO_URL" "$SOURCE_DIR" ||
      fail "I could not download Dex Lens from $REPO_URL. Check the network and run this again."
  fi
  INSTALL_FROM="$SOURCE_DIR"
fi

# --- 3. Its own Python environment ----------------------------------------
# Its own, deliberately: nothing Lens installs can disturb another tool, and
# removing $LENS_HOME removes all of it.
if [ ! -x "$VENV_DIR/bin/python" ]; then
  say "Setting up its own copy of Python in $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR" ||
    fail "I could not create a Python environment in $VENV_DIR."
else
  say "Reusing the copy of Python already in $VENV_DIR"
fi

say "Installing the dex-lens command (this takes a minute the first time)"
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade "$INSTALL_FROM" ||
  fail "The dex-lens command could not be installed from $INSTALL_FROM."

[ -x "$VENV_DIR/bin/dex-lens" ] ||
  fail "The install finished but produced no dex-lens command. Nothing is usable yet."

# --- 4. Somewhere your shell can find it ----------------------------------
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/dex-lens" "$BIN_DIR/dex-lens"

# --- 5. The skill ----------------------------------------------------------
[ -n "$SKILL_DEST" ] || fail "The skill destination is empty; refusing to touch anything."
mkdir -p "$SKILLS_DIR"
STAGING="$SKILLS_DIR/.dex-lens.installing.$$"
rm -rf "$STAGING"
cp -R "$INSTALL_FROM/skill/dex-lens" "$STAGING" ||
  fail "I could not stage the Dex Lens skill in $SKILLS_DIR."
rm -rf "$SKILL_DEST"
mv "$STAGING" "$SKILL_DEST" ||
  fail "I could not put the Dex Lens skill in $SKILL_DEST."

INSTALLED_VERSION="$("$VENV_DIR/bin/dex-lens" reports --help >/dev/null 2>&1 && echo ok || echo unknown)"
[ "$INSTALLED_VERSION" = "ok" ] ||
  fail "The dex-lens command is installed but did not answer. Run $BIN_DIR/dex-lens reports --help to see why."

# --- 6. What just happened -------------------------------------------------
say ""
say "Done. Here is exactly what changed on this machine:"
step "$SKILL_DEST — the Dex Lens skill, so your assistant can use it"
step "$BIN_DIR/dex-lens — the command the skill runs"
step "$VENV_DIR — its own Python environment, used by nothing else"
say ""
say "Nothing else was touched, and nothing about your setup was sent anywhere."
say ""

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    say "One thing to fix. Your computer keeps a list of the places it looks"
    say "for commands, and $BIN_DIR is not on it yet, so the command is"
    say "installed but not findable. Add this line to the end of the file your"
    say "terminal reads at startup (~/.zshrc on most Macs):"
    say ""
    step "export PATH=\"$BIN_DIR:\$PATH\""
    say ""
    ;;
esac

say "To start, open Claude Code and ask, in your own words:"
say ""
step "Have a look at my setup and tell me what Dex has that I don't."
say ""
say "It reads. It never changes your system."
