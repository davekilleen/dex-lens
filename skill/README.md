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

```sh
mkdir -p ~/.claude/skills
cp -R skill/dex-lens ~/.claude/skills/
```

The skill calls the `dex-lens` command, so install the package too:

```sh
python3 -m venv .venv
.venv/bin/pip install .
```

Put `.venv/bin` on `PATH`, or install with `pipx install .` so `dex-lens`
resolves anywhere.

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

## The three commands the skill uses

| Command | What it does |
| --- | --- |
| `dex-lens inventory <folder>` | Every instruction, settings and skill file with the description it declares, copies folded together. Reads only. |
| `dex-lens catalogue` | Fetches Dex's catalogue, verifies the signature locally, prints it grouped by job to be done. |
| `dex-lens brief <id>` | Everything needed to rebuild one capability elsewhere: method, verification, rollback, and Dex's own evidence with its limits. |

Each exits non-zero rather than printing anything unverified.

## The browser journey

`dex-lens <folder>` still opens the original local web application. It is
frozen: it works, its tests pass, and no further work is planned on it. See
`docs/STATUS.md`.
