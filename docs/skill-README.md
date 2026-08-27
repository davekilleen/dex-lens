# The Dex Lens skill

Dex Lens runs inside the assistant a person already uses, rather than as a
separate application they have to visit.

## Why this shape

The comparison the product exists to make is *given what this person has
already built, which Dex capabilities would actually help them — and what
should Dex learn from the way they work*. That is a judgement about the
content of hundreds or thousands of files: what each skill does, which tools
an assistant can call, which jobs run on their own, whether those things are
merely written down or genuinely active, and whether a person who has built
eleven content skills has any use for a twelfth.

The original local web application could not make that judgement. It checked
whether files of a given name existed and counted them. On the reference vault
it correctly reported 6,263 skill files and had no idea what any of them did.
Filename matching was never going to get there, and it also asked the person to
fill in six free-text fields per job before showing them anything.

An assistant reading those files can make the judgement. So the analysis moved
to where the reading already happens, and what stayed behind in Python is the
part a prompt should not be trusted with: proving the catalogue is genuinely
Dex's, and reducing a large system to something that fits in a context window.

## Install

One line, from nothing installed to ready to ask — the signed release, every
downloaded file checked on your machine against a fingerprint signed when the
release was built:

```sh
curl -fsSL https://github.com/davekilleen/dex-lens/releases/latest/download/install.sh | bash
```

To install from source instead — for development, or unreleased changes:

```sh
curl -fsSL https://raw.githubusercontent.com/davekilleen/dex-lens/main/install.sh | bash
```

It puts the skill where your assistants look for it (Claude Code always;
Codex and shared `~/.agents` homes when they exist), builds the `dex-lens`
command its own Python environment in `~/.local/share/dex-lens`, links the
command into `~/.local/bin`, and prints exactly what it changed. Run it again
to update; running it twice is safe. `--dry-run` says what it would do and
does none of it.

Nothing about the system you will later ask Lens to look at is read, changed,
or sent during the install.

From a clone, the same script installs that clone rather than downloading one:

```sh
./install.sh
```

## Use

Ask the assistant, in your own words:

> Have a look at my setup and tell me what Dex has that I don't.

Or invoke it directly with `/dex-lens`.

## What it does and does not do

It reads. It never writes to the system it is looking at. When you choose a
capability it produces a brief for your own AI to work from, and stops there;
applying it is a separate decision you make with the brief in front of you.

The only network request is for Dex's public signed catalogue, which is the
same file for everyone and carries nothing about you. Its signature is checked
on your machine before any of it is shown.

## The five commands the skill uses

| Command | What it does |
| --- | --- |
| `dex-lens inventory <folder>` | Builds an evidence fingerprint of the approved system: instructions, skills, tool connections, hooks, scheduled work, integration registries, health and recovery definitions, release identity and vault shape. Copies are folded together. Extra folders and live job state require separate permission. Reads only. |
| `dex-lens catalogue` | Fetches Dex's catalogue, verifies the signature locally, and prints all four kinds of capability grouped by job to be done. `--ledger-template` creates a complete accounting sheet tied to those exact signed bytes. |
| `dex-lens brief <id>` | Everything needed to rebuild one capability elsewhere: method, verification, rollback, and Dex's own evidence with its limits. |
| `dex-lens reports` | The dated two-way reports every diagnosis leaves behind, kept outside the inspected folder with their catalogue ledger. `save` refuses missing evidence, missing praise, missing reciprocal value, more than three suggestions, or an unaccounted catalogue entry. |
| `dex-lens share <card.md>` | The only way anything goes the other direction, and only when the person asks. It prints exactly what an idea card would send and sends nothing; `--yes` sends after they have approved those exact bytes, and `--to github` prints a pre-filled issue link they submit themselves. |

Each exits non-zero rather than printing anything unverified.

## What it writes

Everything, in one place: Lens's own storage at `~/.local/state/dex-lens/`.
Nothing is ever written inside the folder being inspected, and the command
that writes the report checks that separation before writing rather than
assuming it.

- `reports/` — the dated report the person reads plus a same-named JSON ledger
  proving every entry in the exact signed catalogue was considered.
- `capability-bridge/` — the verified copy of Dex's catalogue, so a second
  look need not fetch and re-check it, and the record of which capabilities
  this machine has already been shown, which is the whole of how
  `--since-last` knows what is new. Both describe Dex's published catalogue,
  which is the same file for everyone; neither holds anything about the
  system that was inspected.

## The browser journey

`dex-lens <folder>` still opens the original local web application. It is
frozen: it works, its tests pass, and no further work is planned on it. See
`docs/STATUS.md`.
