# Dex Lens

**A second opinion on your AI setup — from a tool with no interest in selling you a new one.**

> **Developer alpha.** The source build opens a local, read-only diagnosis
> concierge for approved Claude Code folders. It is not a supported release or
> pilot build yet. Adaptation and contribution are not available. The tests are
> the most honest description of what this can and cannot currently prove.

## Who this is for

You've built your own personal AI system. Custom instructions, a folder of
prompts, skills for Claude Code, an agent you wired up over a few weekends —
whatever shape it takes, it's *yours*, you use it every day, and it more or
less works.

You don't want to throw it away and adopt someone else's system. But you might
want to know, honestly, how good it actually is — and you might want to borrow
the load-bearing ideas from [Dex](https://github.com/davekilleen/Dex), an
open-source personal AI chief of staff, without migrating to it.

That's the gap Dex Lens exists for. It is deliberately **not** a funnel into
Dex. The person keeps and improves the system they already have. Ever.

## What it does now

The alpha implements the first two acts, kept visibly separate and each needing
its own yes:

1. **Diagnose** — a private, read-only look at your setup, on your machine,
   organised around the jobs *you* confirm you use it for. No account and no
   analytics.
2. **Decide** — you see what it found: what genuinely works, how it knows,
   and where your setup has more access than the job needs. No score, no
   grade, no "your setup is 62% as good as Dex" — that number is
   structurally impossible to produce here, on purpose.
The roadmap adds two later acts. Neither exists in the alpha:

3. **Adapt (roadmap)** — optionally take one evidence-backed capability from Dex and
   fit it *to your system*, one bounded change at a time: exact preview
   first, proven undo before anything is touched, receipt after.
4. **Contribute (roadmap)** — optionally share one recipe back, as a sanitized
   Capability Card you inspect, edit, and redact first. Nothing is ever
   selected by default. Most people will never use this, and that's fine.

## The ethos

- **Your system stays yours.** Installing Dex is never required and never
  the recommendation.
- **Diagnosis is read-only at the operating-system level**, not by promise.
  The inspection process runs inside an OS-enforced sandbox (seccomp on
  Linux, Seatbelt on macOS) that denies writes, network, and shell — even
  if our own code is buggy, even if a file it reads tells it otherwise.
- **Evidence language is literal.** "Configured" is not "working". A file
  existing proves you set something up, not that it does the job. Findings
  say how they're known: verified, supported, reported, or unknown.
- **Consequential jobs are never automated.** Anything touching money,
  messages, credentials, deletion, health, or legal matters can be looked
  at but falls closed to a manual path.
- **Fail closed, say so honestly.** When something can't be proven, the
  product refuses and explains, rather than proceeding on confidence.

These aren't aspirations; each one is enforced by tests in this repo,
including a corpus of deliberately hostile fixtures (planted secrets,
symlink and bind-mount escapes, prompt-injection files, sabotaged
verification) that any change must survive.

## Status

Built and tested so far: the versioned Host Adapter contract, a contained
Claude Code deep adapter (macOS is the first target), the evidence-state
vocabulary, the field-level data boundary, the Job Map with its
propose-then-confirm flow, the high-impact job taxonomy, and the diagnosis
engine with jobs-first Capability Map rendering. The source alpha now includes
the complete loopback-only browser concierge, editable job confirmation,
session security and cancellation, and end-to-end read-only evidence. Next on
the roadmap: the adaptation transaction layer, the contribution flow, and a
small pilot.

The current alpha does **not** claim that every M3 safety gate is closed. In
particular, the macOS sandbox can prove network use is denied but cannot prove
socket creation itself is denied, and the bind-mount hostile fixture still
needs a CI host able to execute it. Those limits are recorded rather than
smoothed over.

## Try the source alpha

Use a folder containing the Claude Code setup you want Dex Lens to offer for
inspection. Installing does not scan it; the first browser screen asks for
explicit read-only permission.

```sh
git clone https://github.com/davekilleen/dex-lens.git
cd dex-lens
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/dex-lens --no-open /path/to/your/approved-folder
```

Open the printed `127.0.0.1` address in a browser. The session stays on that
machine. Press `Ctrl-C` in the terminal to close it. This is a source alpha,
not a published package or a promise that adaptation, contribution, or pilot
support exists.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Read `CONTRIBUTING.md` before writing code: test-first, fail closed, and use
the binding domain vocabulary exactly. The full implementation pack lives in
[`docs/handoff/`](docs/handoff/) — the gates are the spec — with architecture
notes in [`docs/architecture.md`](docs/architecture.md).

## Background

Dex Lens grew out of a public planning effort in the Dex repo
([davekilleen/Dex#347](https://github.com/davekilleen/Dex/issues/347) and
#348–#357), hardened by an independent critique whose gates are binding
acceptance criteria for this codebase. Internally the contribution machinery
is called the *Dex Capability Exchange* — you'll see that name in the design
documents.

## License

Not yet chosen (see [`docs/DAVE-DECISIONS.md`](docs/DAVE-DECISIONS.md)).
Until one is added, all rights reserved — but the code is public precisely
so the safety claims can be inspected.
