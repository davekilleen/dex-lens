# Dex Lens graceful upgrade design

**Date:** 2026-08-26  
**Status:** Approved for implementation  
**Scope:** The signed public Dex Lens installer and its upgrade tests

## Problem

People who installed Dex Lens with the earlier official source installer have
a command link at `~/.local/bin/dex-lens` that points to
`~/.local/share/dex-lens/venv/bin/dex-lens`. The signed release installer uses
a newer, versioned private location. Its safety check recognises only that new
location, so it mistakes the older official Lens command for an unrelated
command and refuses to update it.

The refusal protects people from having an unrelated command overwritten, but
it also blocks exactly the returning users the installer says it can update.

## Permission model

Deliberately running the installer again is permission to update an installation
that can be proven to be an earlier official Dex Lens installation. No second
prompt or second command is required.

This permission is narrow. It does not allow the installer to replace an
arbitrary file or symlink named `dex-lens`. Anything that cannot be classified
as an official current or legacy Lens location remains untouched.

Lens does not silently update itself in the background. Lens code and its skill
change only when the person deliberately runs the installer. The signed public
Dex capability reference is separate data and may refresh when the person asks
Lens to compare systems.

## Installer experience

Before downloading or writing anything, the installer classifies the launcher
at `~/.local/bin/dex-lens`:

1. **No launcher:** continue with a first install.
2. **Current signed Lens launcher:** continue with an idempotent install or
   update.
3. **Earlier official source-install launcher:** explain that Lens was used
   before, name the older private location, say that this deliberate installer
   run will update the command and skill, and say that the older private copy
   will remain available for rollback. Then continue.
4. **Anything else:** stop before network or filesystem mutation, name the
   launcher and its target where available, and explain that Lens will not
   overwrite a command it cannot prove it owns.

The dry run uses the same classification and accurately describes the action
that a real run would take.

After a recognised upgrade, the installer:

- installs or reuses the exact signed, versioned Lens release;
- repoints only the `dex-lens` command link;
- refreshes the complete Dex Lens skill directory in each supported assistant
  home already present on the machine; and
- reports the new version, command location, skill locations, and preserved
  legacy location.

The older source installation is not deleted or edited. Repointing the command
is reversible by restoring its previous symlink target.

## Ownership classification

An earlier official source installation is recognised only when the launcher is
a symlink whose target exactly matches the source installer's documented
absolute target under the same user's home:

`$HOME/.local/share/dex-lens/venv/bin/dex-lens`

A current signed installation is recognised only when its target is beneath the
signed installer's configured Dex Lens versions directory. Relative links,
regular files, custom targets, and links outside those two proven locations are
not adopted automatically.

## Failure behaviour

- Classification happens before download, installation, skill replacement, or
  first-install reporting.
- An unrecognised launcher produces a clear refusal and leaves the machine
  unchanged.
- A failure after a recognised upgrade leaves the old private source install
  intact.
- A partially installed new signed version follows the existing guarded cleanup
  path; cleanup never touches the old source installation.

## Verification

Automated tests must prove:

- a legacy official launcher is recognised and may be repointed;
- its previous private install remains untouched;
- the person sees the returning-user explanation and rollback location;
- dry-run output describes the same migration without writing or fetching;
- a current signed launcher remains safely repeatable;
- a foreign symlink and a regular file are both refused before network access;
- the skill directory is refreshed from the signed release; and
- the generated public installer and checked-in installer remain in parity.

The full Lens test suite, lint, release-installer smoke proof, and macOS/Linux CI
matrix remain required before release.

## Out of scope

- Deleting the older source installation.
- Background self-updates.
- Automatically adopting custom install paths.
- Publishing or releasing a new Lens version without separate founder approval.
