# The Dex Lens skill

Dex Lens runs inside the assistant a person already uses, rather than as a
separate application they have to visit.

## Why this shape

The comparison the product exists to make is *given what this person has
already built, which Dex capabilities would actually help them*. That is a
judgement about the content of hundreds or thousands of files: what each skill
does, whether two of them overlap, whether a person who has built eleven
content skills has any use for a twelfth.

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

One line, from nothing installed to ready to ask:

```sh
curl -fsSL https://raw.githubusercontent.com/davekilleen/dex-lens/main/install.sh | bash
```

It puts the skill in `~/.claude/skills/dex-lens`, builds the `dex-lens`
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

## The four commands the skill uses

| Command | What it does |
| --- | --- |
| `dex-lens inventory <folder>` | Every instruction, settings and skill file with the description it declares, copies folded together, and a housekeeping section naming leftover copies, drift and switched-off skills. Reads only. |
| `dex-lens catalogue` | Fetches Dex's catalogue, verifies the signature locally, prints it grouped by job to be done. `--jobs` and `--only` narrow it; `--since-last` makes it silent unless something changed. |
| `dex-lens brief <id>` | Everything needed to rebuild one capability elsewhere: method, verification, rollback, and Dex's own evidence with its limits. |
| `dex-lens reports` | The dated reports every diagnosis leaves behind, kept in app storage outside the inspected folder. `save` writes one and refuses a report that quotes no evidence, `check` says whether one is ready, and `--last` prints the previous one so the next run can say what changed. |

Each exits non-zero rather than printing anything unverified.

## What it writes

One thing, in one place: the dated report, under
`~/.local/state/dex-lens/reports/`. It is never written inside the folder
being inspected, and the command that writes it checks that separation before
writing rather than assuming it.

## The browser journey

`dex-lens <folder>` still opens the original local web application. It is
frozen: it works, its tests pass, and no further work is planned on it. See
`docs/STATUS.md`.
