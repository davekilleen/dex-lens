# Dex Lens

**Understand what your Claude Code setup can really do — without replacing it, scoring it, or sending your private setup away.**

Dex Lens is a local second opinion for people who already use Claude Code on a
Mac. You choose a setup folder, confirm the real work you use it for, and Lens
shows what appears to work, what the evidence actually supports, and where the
picture is still uncertain.

You do not need to use Dex. There is no account or analytics, you keep your
existing system, and there is no hidden comparison with somebody else's setup.

> **Current status:** the source code is a pilot candidate, not a supported
> download or finished public release. The first real participant pilot has not
> run yet.

## What you get

- A map of the real jobs you say matter, which you can correct before Lens uses it.
- A plain-English view of your setup's strengths, gaps, and unnecessarily broad access.
- An explanation of how each finding is known — never a made-up overall score.
- A guided preview of one possible improvement, without adopting Dex or silently
  changing the setup you already own.
- The option to share a carefully limited recipe back, only after seeing and
  approving the exact information that would leave your machine.

## What a session feels like

1. **Choose the folder.** Lens reads only the Claude Code setup folder you approve.
2. **Confirm the purpose.** You edit the list of jobs Lens thinks you use the setup for.
3. **Review the evidence.** Lens separates what it can verify from what is merely
   configured, reported by you, or still unknown.
4. **Decide what happens next.** Diagnosis does not change anything. Lens can
   explain and preview a possible improvement, but the real-user pilot does not
   automate it until the agreed job outcome can genuinely be checked.
5. **Keep or share the result.** Your findings stay local. Sharing a sanitized
   Capability Card is optional, off by default, and asks for fresh approval.

## What Lens reads, changes, and sends

| Boundary | Plain-English promise |
| --- | --- |
| **Reads** | Supported setup files inside the folder you select, such as instructions, skills, and configuration. It does not silently widen that folder. |
| **Changes during diagnosis** | Nothing. The diagnosis is read-only. |
| **Changes after a separate approval** | None in the first real-user pilot. The recovery machinery is tested on isolated synthetic files, but Lens will not confuse “a file was created” with “your real job improved.” |
| **Sends during diagnosis or adaptation** | Nothing. Those stages require no account and make no external connection. |
| **Sends if you choose to contribute** | Only the exact sanitized Capability Card and disclosure bytes shown to you for approval. No sharing is selected by default. |

## Safety in plain English

Lens uses operating-system controls, not a polite promise, to keep deep
inspection read-only and offline. A **sandbox** is a restricted process that the
operating system prevents from writing files, contacting the internet, or
launching other commands.

If the Mac cannot prove that stronger sandbox is available, Lens does not carry
on and hope for the best. It switches to a more limited guided path where you
provide bounded evidence yourself. This is what **fail closed** means: when a
safety claim cannot be proven, the risky route stays unavailable.

Lens also keeps four evidence levels separate:

- **Verified:** directly demonstrated by a supported check.
- **Supported:** good evidence exists, but the full job was not directly demonstrated.
- **Reported:** you told Lens it works; Lens has not independently proved it.
- **Unknown:** the available evidence cannot support a stronger claim.

The test suite includes deliberately hostile setup files, planted secrets,
path escapes, prompt injection, sabotaged verification, interrupted changes,
and withdrawal failures. The technical evidence and remaining limitations live
in [the build status](docs/STATUS.md) and [risk register](docs/RISK-REGISTER.md).

## What is available now

The pilot candidate contains the complete local journey:

- private diagnosis and editable Job Map;
- evidence-backed Capability Map;
- a guided improvement preview, plus isolated synthetic tests of approval,
  recovery, receipts, and undo (real-user automation remains unavailable);
- optional Capability Card review, disclosure, consent, submission, and withdrawal;
- pilot enrolment, measurement, safety-gate, runbook, and evidence-pack machinery.

M3, the read-only source alpha, is merged in [PR #4](https://github.com/davekilleen/dex-lens/pull/4).
The M4–M6 pilot candidate is in [draft PR #5](https://github.com/davekilleen/dex-lens/pull/5),
where the Linux/macOS test matrix and exact-build safety gates are required
before merge. It remains unmerged and unreleased while delivery review completes.

## What is not complete

- There is no supported participant setup package or published Dex Lens release yet.
- No real participant pilot has run, so there is no real-world outcome evidence.
- Consent wording still needs human review before anyone enrols.
- The final evidence pack still needs named risk owners and independent safety sign-off.
- A Mac that cannot prove deep-inspection containment uses the guided path instead.
- Automated real-user improvements remain unavailable until Lens has a genuine
  way to observe the Success Contract outcome after real use.

## Try the source build

This is for developers and invited testers who are comfortable running a local
source build. Installing it does not scan anything; the first browser screen
asks which folder may be read.

```sh
git clone https://github.com/davekilleen/dex-lens.git
cd dex-lens
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/dex-lens --no-open /path/to/your/approved-folder
```

Open the printed `127.0.0.1` address in a browser. That address means the page is
served only from your own machine. Press `Ctrl-C` in the terminal to close the
session.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing code. The binding safety
gates live in [docs/handoff](docs/handoff/), with deeper architecture notes in
[docs/architecture.md](docs/architecture.md).

## Background

Dex Lens grew from a public product-design effort in the Dex repository
([issue #347](https://github.com/davekilleen/Dex/issues/347) and #348–#357).
Internally, the optional contribution machinery is called the Dex Capability
Exchange. The public product name is **Dex Lens**.

## License

A licence has not been chosen yet. Until one is added, all rights are reserved.
The code is public so its safety claims can be inspected rather than taken on trust.
