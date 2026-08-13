# Dex Lens public self-serve launch — design

**Date:** 2026-08-13
**Status:** Implemented on the launch branch; public release pending review and live proofs
**Build Card:** dex-lens-public-self-serve-launcher

## Plain-English summary

Dex Lens will become something a person can start with one paste-in command instead
of a developer setup. The command installs Lens in its own private application
folder — never in the person's Vault — and opens a local browser page. The person
then chooses the exact folder they want Lens to consider, sees the read-only
boundary, and approves it before any Diagnosis starts.

The download is tied to one reviewed release, not whatever happens to be on GitHub
that day. It verifies what it downloaded before running it. Lens continues to run
locally, uses no account or analytics, and makes no catalogue request unless the
person separately asks for it.

Linux can offer the contained, read-only Diagnosis today. Mac must not pretend to
offer the same thing until its operating-system safety proof passes: the current
Mac implementation deliberately stops before reading because Apple's built-in
sandbox cannot yet prove the full boundary. This work therefore builds the Mac
product path and its proof, rather than publishing a weaker route as though it
were a Vault Diagnosis. Windows is a separate safe lane: an information-only,
signed Preview may arrive first; a full Windows Diagnosis waits for native
containment evidence.

## Founder direction and product boundary

Dave asked for Dex Lens itself to change: public self-serve, Mac/Linux first, then
Windows. The product decision in this design is:

1. **A person's Vault stays theirs.** Setup does not inspect it, write to it,
   upload it, or make it part of an account.
2. **A command is not a claim.** The platform route may only describe a full
   Diagnosis when its operating-system boundary has been demonstrated on that
   platform. An unavailable boundary produces an honest guided route; it never
   silently runs an uncontained collector.
3. **The first real test is meaningful.** Dave's own customised Mac Vault is not
   treated as a disposable test fixture or as evidence that can lower the safety
   bar.
4. **Public means repeatable.** The same artifact, checks, recovery instructions
   and plain language work for every person; it does not mean an unreviewed branch
   or an irreversible automatic update is public.

## What a person experiences

### 1. Start

The public GitHub README and Mac/Linux page will offer this command only after
its release assets exist and the consumer proof has passed:

    curl -fsSL https://github.com/davekilleen/dex-lens/releases/latest/download/install.sh | bash

The short bootstrap identifies the current supported release, downloads only that
release's manifest and artifact, verifies them, installs Lens in its private
application directory, and opens it. It explains each step in normal language. It
never asks for an administrator password, installs Git or Node, alters a system
Python, or accepts a Vault path in the command. If a supported Python is missing, it
points to the official installer and tells the person to paste the same Lens command
again. Lens asks for a folder only after the private local application starts.

An inspectable alternative is always available: download the versioned bootstrap and
manifest, review their displayed version and digest, then run the verified local
file. The generic one-liner is a convenience doorway, not a substitute for an
immutable application artifact.

### 2. Choose a folder without finding a path in a terminal

The installed dex-lens command opens the local experience and invokes a native
folder chooser for its normal desktop path. The chooser only returns the folder name
to Lens; it does not start a Diagnosis. A person selects the folder containing their
personal AI system, then sees the existing local permission screen naming the scope,
allowed read-only work, denials and cancellation control. Manual
dex-lens /path/to/folder remains for technical or headless use.

If a native chooser cannot run, Lens says so plainly and offers the manual form. It
never falls back to uploading a folder through a webpage or asking a browser to
expose an invisible local path.

### 3. Approve the exact scope

Before showing the local page, Lens records the selected directory's canonical
identity so a later path swap cannot silently widen the scope. It does not enumerate
or read the folder's contents. Only after the person approves the local page does the
Deep Adapter collect evidence. The current loopback-only address, single-use token,
same-origin form protections, cancellation, deletion and no-store response policy
remain intact.

### 4. Review the private Capability Map

The person sees the existing plain-English Capability Map. Every finding remains
marked by Evidence Level. An optional signed Dex Capability Catalog fetch is a
separate consent decision; skipping it keeps the Diagnosis useful offline.
Adaptation and Contribution remain separate, explicit steps and do not become part
of installation.

## Platform contract

| Platform | Public start | Direct Vault Diagnosis | Honest current outcome |
| --- | --- | --- | --- |
| Linux (supported CPU) | Versioned installer plus native chooser | Yes, when Linux containment probes pass | Contained, read-only Diagnosis |
| macOS | Versioned installer plus native chooser | Only after the Mac containment proof passes | Until then, guided route; no direct read and no Verified finding |
| Windows | Separate signed package, never a web-piped script | Not yet | Information-only Preview first; full Diagnosis only after native containment proof |

The table is a product contract, not marketing copy. It must be reflected in the
README, status document, landing page and user-facing error text in the same
delivery.

### macOS release condition

MacOSStrategy currently fails closed because sandbox-exec cannot prove the required
runtime socket boundary. No code change may weaken that refusal merely to make a Mac
job look green.

For Mac to advertise a full Diagnosis, the exact release must prove its collector
cannot reach the network, write inside or outside the approved roots, execute
arbitrary programs, or use an unapproved local communication path. The proof must
run on a real macOS environment and be able to fail deliberately. If that condition
is not met, the released Mac path says that no Vault file was read and offers only
the guided evidence route.

## Release and install contract

### Immutable application artifact

Dex Lens owns its package and release workflow. The first release supports
Apple Silicon macOS and Linux x86_64 and publishes:

- two offline wheelhouse archives containing a non-editable Python wheel built
  from one exact reviewed commit plus the fixed runtime wheels for each
  supported platform;
- a canonical manifest binding version, source commit, Python requirement,
  archive filenames and SHA-256 values; and
- a detached ECDSA P-256 signature for the exact manifest bytes, verified
  against the public key embedded in the installer. P-256 is dedicated to the
  installer bootstrap because the system OpenSSL available before Python setup
  can verify it on both supported platforms; it never reuses the Ed25519 Dex
  Core catalogue key.

The installer rejects a missing, mismatched, malformed or incorrectly signed
manifest. It never fetches main, a floating Git branch, or source code through
pip. A release signing key is held only through the approved secrets route; it
is never committed or pasted into chat.

GitHub Releases owns the exact-version bootstrap and the current release pointer. It
does not build Lens on download or silently substitute source from a branch. After
publication, a live probe compares the anonymously served manifest, installer and
archive bytes with the release record.

### Private installation layout

Installation is per person and is chosen before any approved root exists:

- macOS: the user's Application Support folder, under Dex Lens releases;
- Linux: the user's application-data folder, under dex-lens releases.

Each release receives its own virtual environment. The launcher changes only after
the new version passes a local startup check, so an earlier version remains in its
versioned folder. Interrupted downloads remain temporary; if a new install fails
after its version folder is created, the installer removes only that just-created
Lens-owned folder and leaves every pre-existing path untouched. Re-running the same
command is the supported retry and reopen path.

The first release has no background updater and no automated uninstall command.
Those remain follow-on work; neither may ever touch an approved root.

### Network and data boundary

The installer downloads only public, identical-for-everyone release material. The
application makes no network request on first start. The only normal-path request
remains the existing optional public catalogue GET after clear consent; it sends no
Vault path, contents, job text, account or identifier. A signature or freshness
failure leaves the person with the last verified catalogue or none, visibly labelled.

## Windows follow-on

Windows must not use irm piped to iex, administrator elevation, restricted tokens or
Job Objects as a false equivalent to containment. The first safe public Windows
deliverable is a version-pinned, signed information-only Preview that reads no chosen
folder, changes nothing and does not contact a service before separate catalogue
consent.

A future full Windows Deep Adapter requires a native AppContainer-style boundary,
Windows-specific reparse-point, ACL and snapshot handling, and hostile proofs for no
host writes, no network, no arbitrary process execution, cancellation and no partial
output. Windows Sandbox may be useful for host isolation but is not enough by itself
to label a finding Verified.

## Verification before public availability

The public claim stays closed until all relevant evidence is green:

1. A clean downloaded artifact installs and launches on Linux x86_64 and Apple
   Silicon macOS without Git, Node or any global Python modification. Python
   3.11–3.14 must already be present; a missing version gets an exact official
   install-and-retry instruction. Intel Mac
   and Linux ARM remain explicit source-build routes until native wheel lanes
   prove their complete dependency sets.
2. Deliberately altered wheel, digest, signature, manifest, install path and
   interrupted-download cases fail closed without a partial current install.
3. The normal launcher and native folder chooser perform no approved-root read before
   the visible permission action; cancellation leaves no partial collection or Vault
   change.
4. Linux's real containment, egress and hostile-scope tests remain green. macOS has
   either an equivalent demonstrated proof or an explicit no-read guided outcome.
5. The production GitHub bootstrap, manifest and artifact are fetched
   anonymously and match the exact release bytes. The installer command works from a
   clean test machine.
6. README, status, Build Card and Dispatch say the same thing about platform
   capability and release state.

## Deliberately not included

- Moving a person's system to Dex, automatic adaptation, upload of a person's system, analytics,
  accounts or background catalogue subscription.
- A Windows full Diagnosis before its native containment evidence exists.
- A claim that a successful installation proves that a person's system works well.

## Implementation handoff

The next artifact is a test-first implementation plan. It will split the work into a
small launcher/runtime slice, release and manifest slice, website slice,
platform-proof slice, and a separate Windows Preview and containment track. Each
slice will have a deliberately failing test before code, and the final release work
will be independently reviewed before publication.
