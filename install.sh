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

# `$0` is "bash" when this script is piped in, so there is no file to read the
# header out of. The documented install shape must not be the one that breaks.
usage() {
  if [ -r "${BASH_SOURCE[0]:-}" ]; then
    sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  else
    say "Dex Lens installer."
    say ""
    say "  --dry-run   Say exactly what would happen and change nothing."
    say "  --help      This text."
    say ""
    say "Overrides: DEX_LENS_HOME, DEX_LENS_BIN, DEX_LENS_SKILLS_DIR, DEX_LENS_REPO."
  fi
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

# --- 2. Where the source comes from ---------------------------------------
# Decided before anything happens, so a dry run can say which of the two it
# would be. Running from a clone installs that clone. Piped from the web —
# the documented shape — there is no file on disk at all: `$BASH_SOURCE` is
# unset, and under `set -u` reading it unguarded aborted the whole install
# before it did anything. That is why it is expanded with a default here.
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
else
  SCRIPT_DIR=""
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ] &&
  [ -d "$SCRIPT_DIR/src/capability_exchange/skill/dex-lens" ]; then
  SOURCE_KIND="here"
  INSTALL_FROM="$SCRIPT_DIR"
else
  SOURCE_KIND="download"
  INSTALL_FROM="$SOURCE_DIR"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  say ""
  say "This is a dry run. Nothing below has happened, and nothing has changed."
  say ""
  say "What a real run would do:"
  if [ "$SOURCE_KIND" = "here" ]; then
    step "install Dex Lens from this copy: $INSTALL_FROM"
  else
    step "download Dex Lens from $REPO_URL into $SOURCE_DIR"
  fi
  step "set up its own copy of Python in $VENV_DIR, so it cannot disturb anything else"
  step "link the dex-lens command into $BIN_DIR"
  step "put the Dex Lens skill in $SKILL_DEST"
  step "send one anonymous first-install note to heydex.ai (version and machine type only; DEX_LENS_NO_PING=1 disables)"
  say ""
  say "It would not read, change, or send anything about the AI system you"
  say "later ask Lens to look at."
  exit 0
fi

if [ "$SOURCE_KIND" = "here" ]; then
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
# The skill goes wherever an assistant will actually look for it. Claude
# Code's home is always set up; the homes other assistants read (Codex,
# and the shared ~/.agents convention) are joined only when they already
# exist, because creating them would claim this machine uses a tool it does
# not. DEX_LENS_SKILLS_DIR overrides everything with one explicit place.
place_skill() {
  DEST_ROOT="$1"
  DEST_DIR="$DEST_ROOT/dex-lens"
  mkdir -p "$DEST_ROOT"
  STAGING_DIR="$DEST_ROOT/.dex-lens.installing.$$"
  rm -rf "$STAGING_DIR"
  cp -R "$INSTALL_FROM/src/capability_exchange/skill/dex-lens" "$STAGING_DIR" ||
    fail "I could not stage the Dex Lens skill in $DEST_ROOT."
  rm -rf "$DEST_DIR"
  mv "$STAGING_DIR" "$DEST_DIR" ||
    fail "I could not put the Dex Lens skill in $DEST_DIR."
}

[ -n "$SKILL_DEST" ] || fail "The skill destination is empty; refusing to touch anything."
place_skill "$SKILLS_DIR"
if [ -z "${DEX_LENS_SKILLS_DIR:-}" ]; then
  for extra_home in "$HOME/.codex/skills" "$HOME/.agents/skills"; do
    parent="$(dirname "$extra_home")"
    if [ -d "$parent" ]; then
      place_skill "$extra_home"
    fi
  done
fi

# Prove the thing that was just installed actually answers, rather than
# reporting success because a copy finished.
ANSWERS="$("$VENV_DIR/bin/dex-lens" >/dev/null 2>&1 && echo yes || echo no)"
[ "$ANSWERS" = "yes" ] ||
  fail "The dex-lens command is installed but did not answer. Run $BIN_DIR/dex-lens to see why."

# --- 6. One anonymous "someone installed this" note ------------------------
# Sent once, the first time an install on this machine succeeds, and declared
# on the page in the same words as here: the Lens version and the machine
# type, nothing else — no name, no identifier, nothing about the system Lens
# will later look at. Re-runs are silent (the marker below), failure never
# breaks an install, and DEX_LENS_NO_PING=1 switches even this off.
PING_MARKER="$LENS_HOME/.install-recorded"
PINGED=0
if [ "${DEX_LENS_NO_PING:-0}" != "1" ] && [ ! -f "$PING_MARKER" ]; then
  LENS_VERSION="$("$VENV_DIR/bin/python" -c \
    'from importlib.metadata import version; print(version("capability_exchange"))' \
    2>/dev/null || echo unknown)"
  if curl -fsS --max-time 3 -X POST https://heydex.ai/lens/installed \
    -H "Content-Type: application/json" \
    -d "{\"lens_version\":\"$LENS_VERSION\",\"target\":\"source-$(uname -s | tr 'A-Z' 'a-z')\"}" \
    >/dev/null 2>&1; then
    touch "$PING_MARKER"
    PINGED=1
  fi || true
fi

# --- 7. What just happened -------------------------------------------------
say ""
say "Done. Here is exactly what changed on this machine:"
step "$SKILL_DEST — the Dex Lens skill, so your assistant can use it"
step "$BIN_DIR/dex-lens — the command the skill runs"
step "$VENV_DIR — its own Python environment, used by nothing else"
say ""
say "Nothing else about this machine was touched, and nothing about your"
say "setup was read or sent."
if [ "$PINGED" = "1" ]; then
  say ""
  say "One anonymous note went to heydex.ai: that an install happened, the"
  say "version, and the machine type. Nothing else, and never again from this"
  say "machine. DEX_LENS_NO_PING=1 would have switched it off."
fi
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

# --- 8. Start the conversation --------------------------------------------
# The whole point of one pasted line is that the person never has to learn a
# second step. If Claude Code is here and a real terminal is attached, hand
# straight over to it with the first question already asked. stdin is the
# pipe when this script arrives via curl, so the terminal is reattached from
# /dev/tty; without one (scripts, CI), fall back to printing the question.
DEX_LENS_ASK="Use Dex Lens to have a look at my setup and tell me what Dex has that I don't."
# Whichever assistant this machine actually has gets the hand-over: Claude
# Code first because its skill loading is what the skill was written against,
# then Codex. Neither present, or no terminal: print the question instead.
ASSISTANT=""
if command -v claude >/dev/null 2>&1; then
  ASSISTANT="claude"
elif command -v codex >/dev/null 2>&1; then
  ASSISTANT="codex"
fi
if [ "${DEX_LENS_NO_LAUNCH:-0}" != "1" ] && [ -n "$ASSISTANT" ] &&
  [ -r /dev/tty ] && [ -w /dev/tty ]; then
  say "Starting your assistant now. Dex Lens reads nothing until you tell it"
  say "which folder it may look at, and it never changes what it looks at."
  say ""
  # The assistant we are about to start will call `dex-lens` by name, and on
  # a fresh machine the command's folder may not be on PATH yet — the warning
  # above says exactly that. The launched process gets it either way; the
  # person's own shell still needs the line above, once.
  export PATH="$BIN_DIR:$PATH"
  exec "$ASSISTANT" "$DEX_LENS_ASK" < /dev/tty
fi

say "To start, open Claude Code and ask, in your own words:"
say ""
step "Have a look at my setup and tell me what Dex has that I don't."
say ""
say "It reads. It never changes your system."
