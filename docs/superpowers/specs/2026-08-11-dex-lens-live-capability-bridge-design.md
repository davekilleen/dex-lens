# Dex Lens live capability bridge — design

Status: DRAFT for Dave's review (Roughdraft). Nothing here is built. Implementation
starts only after Dave approves this document.

Date: 2026-08-11. Author: Fable 5 session (thread thr_25m7xetm6a), continuing the
design brainstorm Dave started. Binding prior material: `docs/handoff/HANDOFF.md`
(gates G1–G6, R1–R7), the Build Card `dex-lens-live-capability-bridge` (dex-cards
PR #31), and Dave's three adopted decisions below.

---

## The short version (plain English)

People who built their own Dex-inspired AI systems fear missing what Dex ships
next. Today Lens can privately examine their system and show honest strengths and
gaps — but it has no connection to Dex at all. This design adds that connection,
Dave's way:

1. **Dex starts publishing a signed "capability catalogue"** — a small, tamper-proof
   file describing what each real Dex release can do, in plain language, produced
   automatically when a release ships and never from unfinished work.
2. **A person connects only when they press a button.** At the end of a Lens
   session, after they have confirmed what their system is for, Lens offers:
   *"See what's new in Dex that fits your system."* Pressing it shows exactly what
   will be requested (no personal data — the request is the same for every person
   on the same version), fetches the catalogue once, and checks the signature.
3. **Matching happens on their machine.** Lens compares the catalogue against the
   jobs they confirmed and the gaps it found, and shows at most three relevant
   capabilities — each with a plain reason ("shown because your job X has a gap in
   Y"). If nothing is relevant, Lens says so calmly. No FOMO manufacturing.
4. **Choosing one produces a brief, not a change.** The person gets a plain-English
   explanation (what it is, prerequisites, trade-offs, evidence) and a portable
   brief written for *their own AI* to adapt the idea into *their* system. Lens
   never applies it, never writes into their system, and the existing rule stands:
   automatic adaptation for real users stays refused.

Three adopted decisions bound everything here:

- **Dex Lens is the bridge, not the destination** (Dispatch decision, 2026-08-11).
- **Lens never polls Dex in the background** (Dispatch decision, 2026-08-11).
- **The connection moment is an in-session button after job confirmation**
  (Dave's answer to this thread's one question, 2026-08-11).

---

## 1. Catalogue producer in Dex Core

### What it is

A step in Dex Core's release process that generates, signs, and publishes the
Capability Catalogue — a single JSON envelope describing the user-facing
capabilities of that exact release. Only real, shipped releases produce catalogue
entries; merged-but-unreleased or experimental work never appears (R4).

### Entry schema (v2 — the human-meaningful upgrade)

The current `CatalogEntry` carries only identity (`card_id`, `version_hash`,
`core_release`, `release_provenance`). That cannot power matching or briefing.
Version 2 adds bounded, validated, plain-text fields:

| Field | Purpose |
|---|---|
| `title` | Short human name of the capability. |
| `summary` | One paragraph: what it does, in plain language. |
| `value` | Why it may help — written job-first, not feature-first. |
| `foundation_capabilities` | Which of the eight Foundation Capabilities it strengthens (shared vocabulary with the Capability Map — this is what makes local matching honest and explainable). |
| `prerequisites` | What a host system needs before adapting it. |
| `trade_offs` | Honest costs and limits. |
| `evidence` | How the capability is exercised in Dex itself (docs, tests, usage) — never a marketing claim. |
| `brief` | The portable adaptation brief (see §4): goal, method outline, verification checklist, rollback advice. Data, never executed. |
| `compatibility` | Host requirements in machine-checkable terms (e.g. needs a skills directory, needs hooks). |
| `docs_url` | Public documentation link. |

Envelope-level additions: `catalog_format` (schema version), `catalog_version`
(strictly increasing integer — rollback protection), `issued_at`, `core_release`
(the git tag), plus the existing `signature` and `key_id`.

All text fields are length-bounded and validated exactly like existing Lens
boundary types; catalogue content is untrusted input and is always rendered
inert (escaped) and never interpreted as instructions by Lens (R4).

### What Dex Core already has (verified by repo survey, 2026-08-11)

This producer is an extension of proven machinery, not a new invention:

- Core cuts real releases, several per day, through an automated pipeline
  (`scripts/release.sh` → CI `build-release` job → GitHub Release with
  checksum-sidecar assets). Releases are guarded against double-publish.
- Core already generates a release catalogue on every release
  (`System/.release-catalog.json`) from a publisher-owned registry
  (`core/lifecycle/catalog/official-capabilities.json`), hash-bound,
  schema-validated and fail-closed: a bad catalogue already fails the release.
- Core's catalogue schema already anticipates **ed25519 signing**
  (`integrity.signatures` with `key_id`) but nothing fills it — no key exists
  yet, no signing step, no verifier. This design introduces the first real
  signing key and signing step. The Lens-facing artifact is its own envelope in
  the exact shape Lens's verifier already accepts; whether Core's internal
  release catalogue also starts carrying signatures is out of scope here.
- The natural capability unit is the **skill** (slash command): ~76 active
  skills each carry a stable id and a plain-language, editorially reviewed
  description in `SKILL.md` frontmatter. Today's registry covers only 27
  dormant role skills; the active skills have no catalogue presence.
- One trap: inside Core, the word "capabilities" already names an unrelated
  registry of optional vault rooms. The Core-side artifact therefore gets a
  distinct name — **`dex-lens-catalog-v<version>.json`** — while Lens keeps its
  existing "Capability Catalog" vocabulary.

### Extraction: how entries are authored

**Chosen approach: a curated, publisher-owned Lens registry in the Core repo,
assembled and validated at release time.** A sibling registry to the existing
one holds one entry per capability Dave chooses to publish to Lens. Identity,
version hash, release tag and description are derived automatically from the
shipped skill (descriptions are already written to a "CFO test" plain-language
bar); the Lens-specific fields — `value`, `foundation_capabilities`,
`prerequisites`, `trade_offs`, `brief` — are authored deliberately, because the
catalogue's whole value is that its claims are editorial and honest. The release
pipeline validates every entry against the release tree exactly the way the
existing catalogue generator pins files and hashes: an entry referencing a
skill that is not in the release fails the build.

*Alternative considered — fully automatic extraction from all 76 skills:*
rejected for v1. Auto-shipped prose under Dex's signature would be unreviewed,
and prerequisites/trade-offs genuinely require authorship (the survey confirmed
prerequisite information is scattered across prose today).

*Alternative considered — maintain the catalogue by hand outside the repo:*
rejected; it drifts from releases immediately and has no release gate.

v1 scope: **three to five entries** authored from real shipped skills, chosen
with Dave during implementation — enough to prove the loop end to end.

### Signing, key custody, rotation, revocation

- **Algorithm:** Ed25519 — the algorithm Core's schema already mandates and the
  shape Lens's `SignedCatalog` envelope and `key_id` field anticipate.
- **Private key custody:** a GitHub Actions *environment* secret in the Dex Core
  repo, restricted to the release workflow. Dave holds an offline backup. No
  agent, no laptop checkout, no other workflow can read it. (Key generation and
  secret installation is a one-time founder step with exact copy-pasteable
  commands in the implementation plan.)
- **Public keys:** pinned in Lens source as a `key_id → public key` table.
  Rotation = add the new key in a Lens release, keep the old key valid for its
  window, then retire it. `key_id` in the envelope selects the key.
- **Revocation/rollback:** supersession. Publishing a new envelope with a higher
  `catalog_version` (with an entry removed or corrected) is the revocation
  mechanism. Lens refuses any verified envelope whose `catalog_version` is lower
  than the one it last verified, so a replayed old-but-genuinely-signed catalogue
  cannot reintroduce a withdrawn entry.

### Publication and release gate

Two channels, both riding existing Core plumbing:

- **Durable audit copy:** `dex-lens-catalog-v<version>.json` + `.sha256` sidecar
  uploaded as GitHub Release assets, alongside the four assets the release job
  already uploads on a double-publish-guarded path.
- **Stable "latest" URL:** the same signed envelope served from the Core repo's
  GitHub Pages site, which CI already deploys. This is the URL Lens fetches.
  (A `heydex.ai` vanity URL can front it later via the website repo; not
  required for v1 and not a blocker.)

**Release-pipeline gate:** catalogue validation, signing and publication join
the existing fail-closed catalogue gates — a Core release does not complete
without a valid signed published catalogue, and the e2e proof (§6) includes
demonstrating that a deliberately broken entry fails the pipeline.

## 2. User-invoked delivery route

### The moment (decided by Dave)

After the person has confirmed their Job Map and seen their Capability Map — the
natural end of a session — Lens offers one clearly labelled, optional button:

> **See what's new in Dex that fits your system**

Nothing about the session requires pressing it. Declining or ignoring it changes
nothing about diagnosis (non-negotiable boundary: local-first, useful offline).

### Consent screen (before any network traffic)

Pressing the button does not fetch. It first shows a consent screen in the same
style as the existing inspection-permission screen:

- The exact URL that will be requested.
- The exact request contents: a plain HTTP GET for a static file, carrying no
  cookies, no identifiers, no parameters, no personal data — nothing that
  distinguishes one person from another. (Format compatibility is checked
  locally after download: if the catalogue is newer than this Lens build
  understands, Lens says so and suggests updating Lens — it never sends its
  version to find out.)
- What comes back: a signed catalogue describing Dex capabilities; nothing about
  the person's system is sent, and nothing on their machine changes.
- One approve button, one decline button. Approval is per-press; there is no
  "always allow" in v1.

### Fetch, verification, caching, offline

- One GET per approval. No retries beyond a bounded, visible one; no scheduling,
  no startup fetch, no reminder ("no background polling" is structural).
- The response envelope goes through the existing `verify_catalog` fail-closed
  path: signature invalid or content malformed → the whole envelope is rejected
  and Lens says so plainly.
- **Persistence:** the last *verified* envelope (which contains zero personal
  data) is stored in Lens's own application directory — never inside the
  inspected system — and re-verified on load. This gives last-known-good
  behaviour across sessions and offline. Its storage gets a G2 data-inventory
  entry with a trivial deletion path.
- **Offline / fetch failure:** the button still works — Lens offers the last
  verified catalogue labelled with its age ("verified 12 days ago, release
  v0.9.2"), or states honestly that no catalogue has ever been verified. Stale
  is visible, never silent.

### Egress budget

The catalogue GET becomes the *sole* approved default-path network flow, pinned
in the egress harness (G2): the harness asserts the request carries no canary
values or derivations, and that no other traffic occurs anywhere in the journey,
including on the catalogue screens. The endpoint, request fields, and failure
behaviour become inventoried G2 fields.

## 3. Local relevance matching

### Inputs (all already on the machine)

- Confirmed Success Contracts (the person's own jobs, importance, cadence).
- The Capability Map: per job, one finding per Foundation Capability with its
  evidence level — i.e. where the gaps and weak spots are.
- The verified catalogue entries with their `foundation_capabilities` tags,
  prerequisites, and compatibility fields.

### Mechanism: deterministic, explainable, local

For each catalogue entry, relevance to each *confirmed* job is computed by rule,
not by model:

1. **Gap match:** the entry strengthens a Foundation Capability where that job's
   finding shows a gap or weak evidence.
2. **Compatibility check:** the entry's machine-checkable requirements are
   satisfied by (or at least not contradicted by) the observed host system;
   unmet prerequisites demote the entry and are stated, never hidden.
3. **Ranking:** entries helping more confirmed jobs rank higher; ties break by
   the importance of the jobs helped, then by release recency.

No cloud calls, no embeddings, no profile leaves the machine, nothing is sent
anywhere (the matching happens after the fetch; the egress harness proves it).

*Alternative considered — local LLM/semantic matching:* rejected for v1. It would
be unexplainable, unreproducible across machines, and would either need a model
download or a cloud call. Rule-based matching over a shared closed vocabulary
(the eight Foundation Capabilities on both sides of the bridge) is honest and
auditable. Semantic matching can be revisited once the vocabulary proves too
coarse in practice.

### Anti-FOMO rules (product behaviour, enforced in code)

- At most **three** capabilities shown per session.
- Only entries matched to a *confirmed job* are ever shown — no generic feed.
- Every shown entry carries its reason ("shown because your job 'weekly review'
  has weak evidence for safe-change recovery") and its uncertainty ("Lens cannot
  see whether your system already does this another way").
- An empty result is a first-class, calm outcome: "Nothing new in Dex looks
  relevant to the jobs you confirmed." No badges, no counts, no urgency copy.

## 4. Briefing experience

Selecting a shown capability opens the briefing screen — two layers, strictly
ordered:

**Human layer first** (plain English, for the person):
what it is, why it was shown (job-linked), what it needs, honest trade-offs, and
the evidence that Dex itself ships and uses it.

**Portable brief second** (for their AI, on their explicit action):
a structured Markdown document the person can copy or save to a location of
their choosing — never written into the inspected system. It contains:

- the goal in outcome terms, referencing the person's own job wording;
- a method outline (how Dex approaches it) written to be *adapted, not pasted* —
  it names the concepts, not Dex file paths;
- host-tailoring notes derived from the adapter contract and Capability Map
  (e.g. "your setup keeps skills in `~/.claude/skills`; an equivalent here
  would be…");
- a verification checklist ("you'll know it works when…") and rollback advice;
- a visible header stating: this brief is information for the owner's AI; it was
  produced locally; it grants nothing and changes nothing by itself.

The brief is data. Lens never executes it, never offers to apply it, and the
existing adaptation machinery does not accept it as input in v1 (see §5).

## 5. Safe adoption handoff (boundary preserved)

The existing rule is untouched: **real-user automatic adaptation stays refused**
until Lens can verify a genuine later-use job outcome. The catalogue connection
does not unlock writes of any kind. The briefing journey terminates at
copy/save. The adaptation preview/approval/undo machinery remains where it is,
behind its own separate boundary, and this design deliberately does not connect
the catalogue to it. When that connection is ever proposed, it is a new design
with its own approval — not an increment of this one.

## 6. End-to-end proof (the definition of "connected")

The bridge is claimed as real only when all of the following pass:

1. **The golden path:** one capability from an actual signed Dex Core release
   travels release pipeline → publication → in-session button → consent →
   verified fetch → local match → briefing → portable brief, into **three
   representative non-Dex host fixtures**: (a) a minimal hand-rolled Claude Code
   setup (single CLAUDE.md), (b) a heavily customised Claude Code setup
   (skills, hooks, subagents), (c) a guided/export-assisted host that Lens's
   deep adapter cannot inspect. Each produces a coherent, host-appropriate brief.
2. **Adversarial cases fail safely:** tampered signature; replayed older signed
   catalogue (rollback refusal); unsigned/malformed envelope; malicious entry
   content (HTML/script and prompt-injection text render inert everywhere and
   never perturb matching); entry with unmet prerequisites (demoted and
   explained); offline press of the button (last-verified or honest none).
3. **Egress:** the full journey including catalogue screens re-passes the
   canary harness with the catalogue GET as the sole approved flow.
4. **Release gate:** a deliberately broken catalogue card fails the Core release
   pipeline (the gate is proven, not assumed).

## 7. Public story

After the bridge genuinely passes §6, the README and GitHub About centre the
bridge: keep the system you built, consult Dex when you choose, bring across
only what you want, with your own AI doing the adapting. The in-progress README
draft (reviewed with Dave on 2026-08-11) is finished then, with an honest
current-vs-future boundary: diagnosis and guided improvement are the pilot
candidate today; the connected bridge is described as available only once §6 is
true. No copy ships before that.

---

## Implementation shape (for the plan that follows approval)

Two repos, explicit ownership, isolated worktrees:

- **Dex Core** (`davekilleen/Dex`): the curated Lens registry + validator
  (extending the existing publisher-owned catalogue machinery), the
  release-pipeline job that assembles/signs/publishes `dex-lens-catalog`,
  one-time signing-key setup, and three to five initial entries authored from
  real shipped skills. Naming avoids Core's existing unrelated "capabilities"
  (vault rooms) vocabulary.
- **Dex Lens** (`davekilleen/dex-lens`): schema v2 + verifier upgrade + rollback
  protection + persistence; journey stages (`CATALOG_CONSENT`, `CATALOG_RESULT`,
  `BRIEFING`) and screens; delivery client; relevance matcher; brief renderer;
  G2 inventory entries; egress harness update; adversarial and e2e fixtures.

Sequencing: Lens schema/verifier first (it defines the contract), Core producer
against that contract, then delivery + matching + briefing, then the §6 proof.
Test-driven throughout; no cross-repo work in a shared checkout.

## What this design refuses (so it stays refused)

- Background polling, scheduled refresh, startup fetch, notifications, badges.
- Sending anything about the person's system to Dex to "improve matching."
- Auto-applying briefs, or catalogue-triggered writes of any kind.
- Catalogue entries from unreleased work.
- A generic "what's new in Dex" feed disconnected from the person's confirmed jobs.
