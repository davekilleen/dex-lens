# Dex Lens harness-neutral installer hand-off design

**Date:** 2026-08-26  
**Status:** Approved design; implementation has not started  
**Scope:** The source and signed-release installers, their closing messages,
and their launch tests

## Problem

The public command is deliberately one paste:

```sh
curl -fsSL https://heydex.ai/lens | bash
```

The installer currently detects Claude Code and Codex, but it always prefers
Claude Code when both commands exist. When the installer is piped through
`bash`, its keyboard input is still connected to the download pipe rather than
the person's Terminal. The installer therefore avoids launching a full-screen
assistant and prints a second command containing a temporary `PATH` instead.

That ending is safe but too technical. It also frames the hand-off as if Lens
belonged to Claude Code even though Codex is already a supported host and future
harnesses may support the same skill contract.

## Goals

- Move a person from installation into the Lens conversation without a second
  paste when a supported harness can be launched safely.
- Route to the person's chosen harness rather than silently preferring Claude
  Code.
- Ask only when more than one supported harness is genuinely available, then
  remember the answer.
- Make support for another harness explicit and testable rather than guessing
  from an executable name.
- Keep non-interactive installs, automated proofs, and explicit no-launch modes
  unable to prompt, hang, or start an assistant.
- Replace the normal success transcript's filesystem detail with short,
  plain-language confirmation while retaining full detail for dry runs and
  troubleshooting.

## Non-goals

- Inferring preference by reading recent conversations, projects, histories, or
  other private activity.
- Launching an arbitrary program merely because a command with a plausible name
  is present.
- Changing what Lens may inspect or its read-only promise.
- Editing shell startup files automatically.
- Publishing a new Lens release without a separate release decision.

## Decision

Use a small registry of supported harness adapters and a one-time chooser.

Each adapter declares only the facts needed for a safe hand-off:

- a stable harness identifier and human-readable name;
- the executable that proves the launch target is installed;
- the skill home or homes that the harness reads; and
- the tested argument shape for opening the harness with the first Lens
  question.

The first registry contains Claude Code and Codex because both are already
recognised by the released installer. A future harness enters the registry only
after its command, skill discovery, prompt hand-off, Terminal behaviour, and
no-launch behaviour have dedicated tests. The shared `~/.agents/skills` folder
may distribute the Lens skill, but its presence alone never proves that an
unknown harness is safe to launch.

## Selection rules

Selection is deterministic and uses this precedence:

1. `DEX_LENS_HARNESS=<id>` explicitly selects a registered harness. The initial
   identifiers are `claude` and `codex`. An unknown or unavailable value is
   refused clearly rather than evaluated as a command.
2. A saved preference is used when that registered harness is still installed.
3. If exactly one registered harness is installed, use it automatically.
4. If several are installed and no valid preference exists, ask once through
   the real Terminal and save the answer.
5. If none is installed, complete the installation without launching anything
   and show the plain-English question to ask in the person's usual assistant.

The installer does not inspect recent activity to break a tie. If a saved
harness later disappears, the preference is treated as stale: one remaining
harness is selected automatically, several cause the chooser to return, and
none uses the unsupported-harness fallback.

The preference lives at
`$DEX_LENS_DATA_HOME/dex-lens/harness-preference`, outside versioned release
folders and outside every harness-owned folder. It is a private, one-line file
containing only the stable harness identifier. The installer writes it with
owner-only permissions via a temporary file in the same directory followed by
an atomic rename, and refuses to follow an existing symbolic link. A dry run
names that this preference would be written; normal success does not print its
filesystem path.

## Terminal hand-off

The installer keeps its existing install-only and no-launch controls as
absolute gates. It never opens or prompts for a harness when either gate is
active.

For the documented `curl | bash` route, the installer may reconnect the chooser
and selected harness to `/dev/tty` only when all of the following are true:

- a readable and writable Terminal device is available;
- the run is interactive rather than automated;
- launch has not been disabled; and
- the selected adapter has passed the platform-specific hand-off tests.

The chosen process receives the temporary Dex Lens command path directly, so
the first conversation works even when the person's shell has not yet learned
that path. Arguments are passed as an array of quoted values; no saved value or
harness name is executed through `eval`.

If Terminal reconnection is unavailable or fails, installation remains
successful. The installer must not wait for input, leave a deaf full-screen
process running, or claim that the conversation started.

## User experience

With one supported harness installed:

```text
Dex Lens is ready.
Opening Codex…
```

For a recognised returning tester:

```text
Dex Lens has been updated safely.
Your previous copy is still available if you need it.
Opening Codex…
```

When both initial adapters are available and no choice has been saved:

```text
Which assistant should Lens use?

1. Claude Code
2. Codex
```

After a valid answer, Lens records the choice and opens that harness. Re-running
the installer uses it without asking again.

When no supported launch target is available:

```text
Dex Lens is ready.
Open your usual AI coding assistant and ask:

  Use Dex Lens to have a look at my setup and tell me what Dex has that I don't.
```

When a supported harness is detected but cannot be opened, the message names
that harness and gives the same plain-language question. It does not expose a
long `PATH=…` command.

Normal success no longer lists the version directory, launcher path, or every
skill destination. Dry-run output continues to name every planned read and
write. `DEX_LENS_VERBOSE=1` retains the exact locations needed for support and
recovery. The preserved earlier installation is mentioned in one sentence by
default; its exact path remains available in verbose output.

## Failure and safety behaviour

- An invalid chooser response explains the valid choices and asks again only
  while a real Terminal remains attached.
- End-of-file or loss of the Terminal abandons launch without failing the
  completed installation.
- A saved preference is data, never executable shell text.
- `DEX_LENS_HARNESS` accepts only registered identifiers.
- `DEX_LENS_INSTALL_ONLY=1` and `DEX_LENS_NO_LAUNCH=1` prevent both chooser and
  launch, including during dry-run descriptions and release proofs.
- An assistant launch failure does not undo a successfully verified install or
  damage a previous installation.
- No selection or launch step reads the vault or the system Lens may later be
  asked to inspect.
- Source and signed-release installers use the same routing rules and messages.

## Verification

Automated tests must prove, for both the source and rendered signed installer:

- Claude Code alone is detected, receives the first question, and has the Lens
  skill available;
- Codex alone receives the equivalent hand-off;
- two installed harnesses produce the one-time chooser;
- the selected preference is saved and reused without a second prompt;
- a removed selected harness invalidates the preference safely;
- a `DEX_LENS_HARNESS` registered override wins and an unknown or unavailable
  override is refused;
- no supported harness produces the plain-language fallback;
- piped installation reconnects a real pseudo-Terminal and leaves the launched
  harness able to receive keyboard input;
- a missing Terminal never prompts, hangs, or launches;
- install-only and no-launch runs never prompt or launch;
- paths containing spaces on macOS remain correctly quoted;
- normal success contains no installation-path inventory or `PATH=…` hand-off;
- dry-run and `DEX_LENS_VERBOSE=1` output preserve truthful locations and
  planned preference writes; and
- the generated public installer remains byte-for-byte reproducible from the
  signed release inputs.

The pseudo-Terminal journeys run on the supported macOS and Linux release
targets. The full Lens suite, lint, release-installer proof, and platform matrix
remain required before any release proposal.

## Delivery boundary

Implementation may proceed through a draft pull request after this specification
is reviewed. Merging, publishing a new Lens version, and changing the public
installer each require their normal verification and explicit release approval.
