# Dex Lens

## Install on Mac or Linux

```sh
bash <(curl -fsSL https://github.com/davekilleen/dex-lens/releases/latest/download/install.sh)
```

Paste that one line into your normal Terminal. If it finds only one of Claude
Code or Codex, it opens it with the first question already there. If you use
both, it asks which one to open. Nothing is read until you tell it which folder
Lens may inspect.

You can also open either assistant yourself and ask, in your own words:

> Have a look at my setup and tell me what Dex has that I don't.

That is the whole first run. The installer puts the Dex Lens skill in
`~/.claude/skills/dex-lens`, gives the `dex-lens` command its own Python
environment so it cannot disturb anything else, links the command into
`~/.local/bin`, and prints exactly what it changed. Running it again is safe.

Run the same installer again when you want to update Lens. That deliberate run
updates both the command and the complete skill your assistant reads. If it
recognises an earlier official Lens installation, it explains the move and
leaves the old private copy in place for rollback. Lens does not silently
update its software in the background; its signed public Dex reference can
refresh separately when you ask Lens to make a comparison.

This is the **signed release**: everything it downloads is checked on your
machine against a fingerprint that was signed when the release was built, so
what you install is exactly what was built and proven, byte for byte. It is
published only after the same installer has passed a real install on a clean
Apple Silicon Mac and a clean Linux machine.

The current Lens software is **Lens v0.1.15**. Its current Dex reference is
published by **Core v1.97.2**. Lens checks that signed reference when you use
it, so Dex can keep the list accurate without asking you to reinstall Lens
each time the list changes.

It reads your machine to check the pieces it needs. It does not read, change,
or send anything about the AI system you will later ask Lens to look at.

For development, or to run unreleased changes, install from source instead:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/davekilleen/dex-lens/main/install.sh)
```

## A private second opinion on your personal AI operating system

Your AI assistant is no longer just a chat window. Over time, its instructions,
skills, tools, permissions and routines become a personal operating system for
how you work — the brain behind an AI assistant or chief of staff.

But as that system grows, a basic question becomes surprisingly difficult to
answer:

> **What can I genuinely trust it to do?**

Dex Lens helps you answer that question. It privately examines the AI system
you already use and gives you a clear view of:

- the real work it appears equipped to handle;
- what is backed by evidence and what is still an assumption;
- where instructions, tools or access may be missing, conflicting or
  unnecessarily broad; and
- the most useful improvement to consider next.

And understanding your system is only half of the promise. Lens is also being
built into a **bridge to Dex**: a way to see which proven Dex capabilities
could strengthen the system you already own, and — when you choose — to give
your own AI a clear, safe brief for bringing a capability across. You keep
your system. Nothing about it is uploaded, and nothing changes without you.

It does not ask you to move to Dex, replace your existing system or accept a
made-up score. The first diagnosis is read-only: Lens explains what it finds
and leaves every decision with you.

> **Dex Lens works with the assistant you already use.** Claude Code has the
> deepest support and Codex works too: the installer places the skill for
> Claude Code always and for Codex when this machine has it, and Lens reads
> both assistants' instruction files (`CLAUDE.md` and `AGENTS.md`). The
> one-line install keeps your keyboard attached, so it opens the assistant
> it finds — or asks when it finds both — with the first question ready. The assistant
> is simply where your system lives; Dex Lens assesses the whole personal AI
> operating system built around your work.

## Why this matters

A personal AI system can look impressive while still being difficult to rely
on.

It may be excellent at researching a market but inconsistent at remembering
commitments. It may draft strong meeting preparation but have no safe way to
check whether a follow-up was actually sent. It may have powerful tools with
broader access than the job requires. Or it may contain valuable capabilities
that you have forgotten are there.

For a product leader, founder or executive, the goal is not to collect more AI
features. The goal is to know where the system is dependable enough to
delegate to, where human judgment still belongs, and what would make it more
useful without surrendering control.

Dex Lens turns that invisible setup into something you can understand and act
on.

## How Dex Lens works

### The journey at a glance

**Your real work** → **A private local check** → **Clear strengths and gaps**
→ **One improvement preview** → **You decide what happens**

### 1. Name the work that matters

Lens starts with the outcomes you expect from your AI system: preparing for
meetings, tracking commitments, researching a market, helping with decisions,
drafting follow-ups, running routines or other work that matters to you.

You review and correct that list. Lens does not decide what “good” means
without you.

### 2. Choose what Lens may inspect

You select the local folder containing the instructions, skills, tools and
configuration behind your AI system. Lens stays inside the boundary you
approve; it does not silently widen its search.

### 3. Run a private, read-only check

Lens maps how your system is assembled and compares it with the work you
expect it to do. The diagnosis runs on your Mac, requires no account and does
not change your files.

### 4. See what holds up — and what does not

Instead of giving your system a simplistic score, Lens shows:

- what it checked directly;
- what has supporting evidence;
- what is based only on your report; and
- what remains unknown.

You see strengths, gaps, conflicting instructions and access that appears
broader than the work requires. Every conclusion shows why Lens reached it.

### 5. Preview one useful improvement

Lens can explain a small, concrete improvement that may make the system safer
or more capable. You see the proposed change before anything happens.

During the first real-user pilot, Lens will not automatically alter a
participant’s system. We will only introduce automation after Lens can verify
that the person’s real work improved — not merely that a file changed.

### 6. Keep control of the result

You can keep the diagnosis private, make a change yourself or leave the system
exactly as it is.

If you discover a useful capability that could help Dex improve, you may
separately choose to share a limited summary. Lens shows the exact information
first, selects nothing by default and asks for fresh approval before anything
leaves your Mac.

## Keep what you built — and still benefit from Dex

Many people built their own personal AI system after seeing what Dex made
possible. They should not have to choose between the system they own and the
capabilities Dex keeps developing.

That bridge is now live. Here is what it does:

- **See what Dex offers, ranked for your system.** Dex publishes a signed
  catalogue of its capabilities, generated only from real releases. Lens
  compares it — entirely on your machine — with the work you confirmed and the
  gaps it found, and shows what would genuinely help, with the reason stated
  for every suggestion.
- **Understand before you act.** Each capability comes with a plain-English
  explanation: what it does, what it needs, honest trade-offs, and the
  evidence that Dex itself ships and uses it.
- **Let your own AI do the adapting.** When you choose a capability, Lens
  produces a portable brief written for *your* AI to recreate the idea inside
  *your* architecture. Lens never applies changes itself, and nothing about
  your system is ever sent to Dex — the catalogue download is identical for
  every person in the world.

> **Where this stands today:** the connection is available and verified end
> to end against Dex's complete signed reference: 115 entries — 94 skills,
> 11 connection systems containing 146 individual tools, 5 recurring jobs
> that run on a schedule, and 5 behind-the-scenes services. Lens looks for those same kinds
> of things in the system you ask it to inspect, so it compares like with like
> instead of looking only at skills. Dex adds a digital seal to the reference
> and Lens checks that seal on your machine before showing anything. Still
> true, and always will be: no account, nothing about your system is ever sent
> anywhere, and Lens changes nothing without you.

## What you receive

- **A map of the work your AI system is meant to support**, checked and
  corrected by you.
- **A plain-English view of its strengths and gaps**, connected to that real
  work.
- **A confidence label for every finding**, so an assumption never masquerades
  as proof.
- **A review of tools and access**, including permissions that may be broader
  than necessary.
- **A prioritized improvement preview**, without a silent edit or forced
  migration.
- **A dated report you keep**, saved outside the folder that was inspected, so
  you can find it next month — and so the next look can tell you what changed
  rather than repeating what you already know.
- **An optional, carefully limited way to contribute**, only when you
  explicitly choose to.

## The trust boundary

| Your question | Dex Lens promise |
| --- | --- |
| **Does diagnosis change my system?** | No. Diagnosis is read-only. |
| **Does it write anything at all?** | Only inside its own storage, `~/.local/state/dex-lens/`: your dated report, plus the checked copy of Dex's public catalogue and the record of what this machine has already been shown, which is how a later look can tell you only what changed. Both of those are about Dex's catalogue, which is the same file for everyone. Never inside the folder it looked at, and it checks that before writing. |
| **Does it upload my setup?** | No. The diagnosis runs locally on your Mac. |
| **Do I need an account?** | No. There is no account or analytics in the diagnosis. |
| **Can it inspect anything it wants?** | No. You choose the folder, and Lens does not silently widen that boundary. |
| **Will it automatically “fix” my system?** | Not in the first participant pilot. Lens can explain and preview an improvement, but it does not apply it. |
| **Can anything be shared?** | Only if you choose to contribute, review the exact limited summary and approve that specific information. Nothing is selected by default. |
| **What happens if the safety boundary cannot be proven?** | The deeper check stays unavailable. Lens uses a more limited guided route rather than hoping for the best. |

## Evidence without theatre

AI products often sound more certain than their evidence allows. Dex Lens
deliberately uses four levels:

- **Verified** — Lens directly demonstrated it with a supported check.
- **Supported** — good evidence exists, but the full real-world job was not
  demonstrated.
- **Reported** — you told Lens it works; Lens has not independently proved it.
- **Unknown** — the available evidence does not justify a stronger claim.

There is no overall score. A single number would hide the difference between a
well-configured tool, a capability that has been observed working and an
outcome that has genuinely improved someone’s work.

## What Dex Lens is — and is not

**Dex Lens is:**

- an independent second opinion on the personal AI system you already own;
- a way to understand capability, evidence, access and gaps in human terms;
- private and read-only during diagnosis;
- a bridge for deliberately bringing selected Dex capabilities into your own
  system, on your terms (live for the complete 115-entry signed reference); and
- designed to help you make a better decision about what to trust or improve.

**Dex Lens is not:**

- a requirement to adopt Dex;
- a migration tool disguised as an assessment;
- a public leaderboard or comparison with somebody else’s system;
- background surveillance or analytics; or
- an autonomous repair agent with permission to change your system silently.

## Current status

Dex Lens v0.1.15 is a signed public release for Apple Silicon Macs and Linux
x86_64 machines. It is ready for invited beta testers on those two platforms.

- No real participant pilot has run yet, so we do not claim real-world outcome
  evidence.
- The first pilot will be deliberately small: 6–8 people who use a personal AI
  system regularly on a Mac.
- Consent wording will receive human review before enrolment.
- Named risk owners and an independent safety reviewer are required before the
  pilot begins.
- Real-user automation remains unavailable until Lens can observe whether an
  agreed work outcome genuinely improved.
- The live bridge to Dex's capability catalogue is available and verified end
  to end against the 115-entry reference published by Core v1.97.2.

This is the honest boundary: the software and safety gates are ready, but the
evidence that matters next must come from real people using it for real work.

## For invited testers and technical evaluators

Invited testers get the one-line installer above and a guided handoff. The
signed release bundle is published: each release carries the two platform
archives, a manifest naming the checksum of each, and a signature over that
manifest, which the installer checks against a public key written into the
installer itself before it unpacks anything.

The manual source build below is for evaluators who want to read every step
before running it. Installing does not scan anything.

```sh
git clone https://github.com/davekilleen/dex-lens.git
cd dex-lens
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/dex-lens --choose-folder
```

Dex Lens opens your computer's folder chooser. Selecting a folder only prepares
the local permission screen; it does not scan or change that folder. The screen
names the exact scope before you approve any read-only Diagnosis.

For a technical or headless start, use:

```sh
.venv/bin/dex-lens --no-open /path/to/your/approved-folder
```

Open the printed `127.0.0.1` address in a browser. That address means the page
is served only from your own machine. Press `Ctrl-C` in the terminal to close
the session.

## Technical evidence

The plain-English promises above are backed by operating-system controls and
deliberately hostile testing — not only by application copy.

If the Mac cannot prove that the stronger read-only boundary is available,
Lens refuses the deeper inspection route. The test suite covers hostile setup
files, planted secrets, attempts to escape the approved folder, instructions
that try to manipulate the assessor, interrupted changes and failed
withdrawals.

The deeper evidence and known limitations are documented in:

- [Build status](./docs/STATUS.md)
- [Risk register](./docs/RISK-REGISTER.md)
- [Architecture](./docs/architecture.md)
- [Pilot handoff and safety gates](./docs/handoff/)

The read-only source alpha merged in
[PR #4](https://github.com/davekilleen/dex-lens/pull/4). The complete pilot
candidate merged in
[PR #5](https://github.com/davekilleen/dex-lens/pull/5) after the Linux and
macOS checks and the exact-build safety gates passed.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Read [CONTRIBUTING.md](./CONTRIBUTING.md) before changing code.

## Background

Dex Lens grew from a public product-design effort in the Dex repository
([issue #347](https://github.com/davekilleen/Dex/issues/347) and #348–#357).

Internally, the optional contribution mechanism is called the Dex Capability
Exchange. The public product is **Dex Lens**: the independent lens through
which you understand the personal AI operating system you already use.

Learn more about Dex at [heydex.ai](https://heydex.ai).

## License

A licence has not been chosen yet. Until one is added, all rights are
reserved. The code is public so its safety claims can be inspected rather than
taken on trust.
