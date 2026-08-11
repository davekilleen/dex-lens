# Dex Lens live capability bridge — design
Status: **APPROVED — Dave Killeen, 2026-08-11**, relayed via the Front Desk after his Roughdraft review ("all looks good"). Revision 2 incorporates all seven of his review comments from the first pass. If any additional annotations surface from his review session, they will be folded in as tracked amendments. Nothing here is built yet; implementation proceeds under the companion plan in `docs/superpowers/plans/`.

Date: 2026-08-11. Author: Fable 5 session (thread thr_25m7xetm6a), continuing the design brainstorm Dave started. Revision 2 incorporates Dave's seven review comments from the first Roughdraft pass. Binding prior material: `docs/handoff/HANDOFF.md` (gates G1–G6, R1–R7) and the Build Card `dex-lens-live-capability-bridge` (dex-cards PR #31).

* * *
## The short version (plain English)
People who built their own Dex-inspired AI systems — and people who have never heard of Dex at all — should be able to see what Dex offers that would genuinely help _their_ system, and bring across only what they choose. Today Lens can privately examine their system and show honest strengths and gaps, but it has no connection to Dex. This design adds that connection:

1. **Dex publishes a signed catalogue of everything it offers.** A tamper-proof file, regenerated with every real Dex release, carrying two things: the overall list of jobs Dex helps people do, and the full suite of capabilities that serve those jobs — each described in plain language with prerequisites, trade-offs and evidence. It is cumulative (the whole offering, not just the latest release's changes), and it never includes unfinished work.
  
2. **The person's system is never sent anywhere.** Whether checking once or subscribed to updates, the only network traffic is downloading that public catalogue file — a request identical for every person in the world. All comparison happens on their machine.
  
3. **Lens lays out the shelf.** It compares the catalogue against the jobs the person confirmed and the gaps it found, and presents the full shelf of Dex capabilities — the ones that look most valuable for _their_ system ranked at the top and pitched with grounding in what Lens actually saw ("your weekly-review job has weak safe-recovery evidence; this is what Dex uses for exactly that"). Everything else stays browsable by job area below. Nothing is hidden, and nothing is oversold: every item shows why it ranked where it did.
  
4. **Staying in the loop is a choice.** By default Lens touches the network only when the person deliberately asks. They can also **subscribe to Dex updates**: Lens then refreshes the catalogue quietly and, when something relevant shifts, opens with "Some things have shifted with Dex. Want me to look at that for you, or park it for another time?" Parking is respected — no nagging, and unsubscribing is one click.
  
5. **Choosing a capability produces a brief, not a change.** A plain-English explanation plus a portable brief written for _their own AI_ to adapt the idea into _their_ system. Lens never applies it, never writes into their system, and the existing rule stands: automatic adaptation for real users stays refused.
  

Adopted decisions bounding this design:

- **Dex Lens is the bridge, not the destination** (Dispatch decision, 2026-08-11).
  
- **No unsolicited connection — but subscription is allowed.** The original "Lens will not poll Dex in the background" decision was amended by Dave in this review (2026-08-11): background refresh is permitted **only** as an explicit, revocable end-user subscription, surfaced through a gentle look-or-park prompt. A fresh install performs zero network traffic until the person chooses either a one-off check or a subscription.
  
- **The first connection moment lives inside the Lens session**, after the person confirms their jobs — spelled out concretely in the walkthrough below (Dave asked for the actual flow; this section is the answer).
  

* * *
## What a person actually experiences
### First visit — including someone who has never heard of Dex
1. **They run Lens** (today: a command that opens a page in their own browser on their own machine). The first screen is the existing permission screen: the exact folders Lens wants to read, read-only, everything stays local. Nothing has been read yet; they approve or walk away.
  
2. **Lens reads their setup and proposes the jobs it thinks the system is for** ("prepare my weekly review", "draft customer replies"). The person edits and confirms — this is the Job Map, in their own words.
  
3. **Lens shows the Capability Map**: for each confirmed job, what looks strong, what looks weak, and how it knows. This is the private second opinion that exists today. Everything so far involved zero network traffic.
  
4. **New screen — the doorway to Dex.** Lens offers, plainly and optionally: **"See what Dex offers for your system."** Not "what's new" — this works for someone meeting Dex for the first time. The screen states: pressing this downloads Dex's public capability catalogue; the download is identical for everyone; nothing about _your_ system is sent. One approve, one decline. Declining changes nothing about the diagnosis they already have.
  
5. **The shelf.** After the catalogue downloads and its signature checks out, Lens lays out the full offering, grounded in _their_ system:
  
  - **Top of the shelf: "Picked for your system"** — the capabilities Lens ranks most valuable for their confirmed jobs and observed gaps, each pitched with its grounding ("shown because…"), prerequisites, trade-offs and evidence. Ranked by expected impact, not by what Dex wants to promote.
    
  - **The rest of the shelf: everything else Dex offers**, browsable by the job it serves, honestly labelled ("didn't match a job you confirmed — but here's what it does"). The person can wander the whole supermarket; Lens just did the picking first.
    
6. **Choosing a capability opens the briefing**: the plain-English layer first (what it is, why it fits, what it needs, honest limits), then the portable brief they can copy or save and hand to their own AI to adapt it into their system. Lens changes nothing itself.
  
7. **On the way out, one calm question: "Want Lens to keep an eye on Dex for you?"** Yes creates the updates subscription (below). No is a complete answer and is never re-asked in-session.
  
### Returning visit — not subscribed
Same flow; the shelf button now reads **"Check Dex — see what's new for your system"**. The shelf marks which capabilities are new or changed since their last look (Lens remembers which catalogue version they last saw — locally). Offline or fetch failure: the last verified catalogue is shown with its age, clearly labelled; stale is visible, never silent.
### Returning visit — subscribed to Dex updates
Because they explicitly subscribed, Lens refreshes the catalogue automatically when it runs (same anonymous download, no per-press consent — the subscription _is_ the consent, and it is shown on screen with a one-click off switch). When something has shifted that is relevant to their confirmed jobs, Lens opens with:

> **"Some things have shifted with Dex since you last looked. Want me to look at that for you, or should we park it for another time?"**

**Look** goes straight to the shelf with the changes ranked and grounded. **Park** is respected: no nagging, no red dots, the same shift is not re-pitched next time unless something new arrives. Unsubscribing removes the standing consent and deletes the subscription record.

**A clearly separated follow-on (not in the v1 build):** true away-from-Lens alerting — a small scheduled check that can notify the person even when Lens isn't running. It is honest to say Dave's "proactively comes to the end user" points here; it needs its own opt-in and its own design pass on the notification surface, so v1 ships the in-Lens subscription loop first and this follow-on is listed in §8 as the next decision.

* * *
## 1. Catalogue producer in Dex Core
### What it is
A step in Dex Core's release process that generates, signs, and publishes the Capability Catalogue — a single JSON envelope describing the jobs Dex helps with and the full suite of user-facing capabilities of that exact release. Only real, shipped releases produce catalogue content; merged-but-unreleased or experimental work never appears (R4). The catalogue is **cumulative**: it always describes Dex's whole current offering, so a first-time visitor sees everything, while version markers let Lens show returning visitors what changed.
### Catalogue structure (v2 — the human-meaningful upgrade)
The current `CatalogEntry` carries only identity (`card_id`, `version_hash`, `core_release`, `release_provenance`). That cannot power matching or briefing. Version 2 has **two sections** (answering Dave's review question: yes, the catalogue needs the overall jobs list, not just capability entries):

**Jobs section** — Dex's jobs-to-be-done taxonomy: for each job Dex addresses, a stable `job_id`, a short human `title`, and a plain-language description of the situation and desired outcome, written in the person's terms. This is what lets the shelf have aisles, lets a first-timer see the shape of what Dex covers, and lets matching align the person's confirmed jobs with Dex's jobs rather than guessing from feature names.

**Capability entries** — one per published capability, with bounded, validated, plain-text fields:

| Field | Purpose |
| --- | --- |
| `title` | Short human name of the capability. |
| `summary` | One paragraph: what it does, in plain language. |
| `value` | Why it may help — written job-first, not feature-first. |
| `jobs_served` | Which catalogue jobs (by `job_id`) this capability serves — the shelf's aisle assignment and the primary matching signal. |
| `foundation_capabilities` | Which of the eight Foundation Capabilities it strengthens (shared vocabulary with the Capability Map — the gap-matching signal). |
| `prerequisites` | What a host system needs before adapting it. |
| `trade_offs` | Honest costs and limits. |
| `evidence` | How the capability is exercised in Dex itself (docs, tests, usage) — never a marketing claim. |
| `brief` | The portable adaptation brief (see §4): goal, method outline, verification checklist, rollback advice. Data, never executed. |
| `compatibility` | Host requirements in machine-checkable terms (e.g. needs a skills directory, needs hooks). |
| `docs_url` | Public documentation link. |
| `since_release` | The Core release that first published this entry (and `changed_in` when materially revised) — what powers honest "new since you last looked" marking. |

Envelope-level fields: `catalog_format` (schema version), `catalog_version` (strictly increasing integer — rollback protection), `issued_at`, `core_release` (the git tag), plus the existing `signature` and `key_id`.

All text fields are length-bounded and validated exactly like existing Lens boundary types; catalogue content is untrusted input and is always rendered inert (escaped) and never interpreted as instructions by Lens (R4).
### What Dex Core already has (verified by repo survey, 2026-08-11)
This producer is an extension of proven machinery, not a new invention:

- Core cuts real releases, several per day, through an automated pipeline (`scripts/release.sh` → CI `build-release` job → GitHub Release with checksum-sidecar assets). Releases are guarded against double-publish.
  
- Core already generates a release catalogue on every release (`System/.release-catalog.json`) from a publisher-owned registry (`core/lifecycle/catalog/official-capabilities.json`), hash-bound, schema-validated and fail-closed: a bad catalogue already fails the release.
  
- Core's catalogue schema already anticipates **ed25519 signing** (`integrity.signatures` with `key_id`) but nothing fills it — no key exists yet, no signing step, no verifier. This design introduces the first real signing key and signing step. The Lens-facing artifact is its own envelope in the exact shape Lens's verifier already accepts; whether Core's internal release catalogue also starts carrying signatures is out of scope here.
  
- The natural capability unit is the **skill** (slash command): ~76 active skills each carry a stable id and a plain-language, editorially reviewed description in `SKILL.md` frontmatter. Today's registry covers only 27 dormant role skills; the active skills have no catalogue presence.
  
- One trap: inside Core, the word "capabilities" already names an unrelated registry of optional vault rooms. The Core-side artifact therefore gets a distinct name — `dex-lens-catalog-v<version>.json` — while Lens keeps its existing "Capability Catalog" vocabulary.
  
### Extraction: how entries are authored
**Chosen approach: a curated, publisher-owned Lens registry in the Core repo, assembled and validated at release time.** A sibling registry to the existing one holds the jobs taxonomy and one entry per capability Dave chooses to publish to Lens. Identity, version hash, release tag and description are derived automatically from the shipped skill (descriptions are already written to a "CFO test" plain-language bar); the Lens-specific fields — `value`, `jobs_served`, `foundation_capabilities`, `prerequisites`, `trade_offs`, `brief` — are authored deliberately, because the catalogue's whole value is that its claims are editorial and honest. The release pipeline validates every entry against the release tree exactly the way the existing catalogue generator pins files and hashes: an entry referencing a skill that is not in the release fails the build.

_Alternative considered — fully automatic extraction from all 76 skills:_ rejected for v1. Auto-shipped prose under Dex's signature would be unreviewed, and prerequisites/trade-offs genuinely require authorship (the survey confirmed prerequisite information is scattered across prose today).

_Alternative considered — maintain the catalogue by hand outside the repo:_ rejected; it drifts from releases immediately and has no release gate.

v1 scope: the jobs taxonomy plus an initial tranche of entries authored from real shipped skills, chosen with Dave during implementation. Because the shelf now shows the full offering, the tranche should be large enough to make the shelf feel real (target: cover the most-used skills and every taxonomy job with at least one entry), while the end-to-end proof (§6) only requires the loop to work — coverage can grow release by release.
### Signing, key custody, rotation, revocation
- **Algorithm:** Ed25519 — the algorithm Core's schema already mandates and the shape Lens's `SignedCatalog` envelope and `key_id` field anticipate.
  
- **Private key custody:** a GitHub Actions _environment_ secret in the Dex Core repo, restricted to the release workflow. Dave holds an offline backup. No agent, no laptop checkout, no other workflow can read it. (Key generation and secret installation is a one-time founder step with exact copy-pasteable commands in the implementation plan.)
  
- **Public keys:** pinned in Lens source as a `key_id → public key` table. Rotation = add the new key in a Lens release, keep the old key valid for its window, then retire it. `key_id` in the envelope selects the key.
  
- **Revocation/rollback:** supersession. Publishing a new envelope with a higher `catalog_version` (with an entry removed or corrected) is the revocation mechanism. Lens refuses any verified envelope whose `catalog_version` is lower than the one it last verified, so a replayed old-but-genuinely-signed catalogue cannot reintroduce a withdrawn entry.
  
### Publication and release gate
Two channels, both riding existing Core plumbing:

- **Durable audit copy:** `dex-lens-catalog-v<version>.json` + `.sha256` sidecar uploaded as GitHub Release assets, alongside the four assets the release job already uploads on a double-publish-guarded path.
  
- **Stable "latest" URL:** the same signed envelope served from the Core repo's GitHub Pages site, which CI already deploys. This is the URL Lens fetches. (A `heydex.ai` vanity URL can front it later via the website repo; not required for v1 and not a blocker.)
  

**Release-pipeline gate:** catalogue validation, signing and publication join the existing fail-closed catalogue gates — a Core release does not complete without a valid signed published catalogue, and the e2e proof (§6) includes demonstrating that a deliberately broken entry fails the pipeline.
## 2. Consented delivery route — deliberate check, plus the updates subscription
### Default: deliberate check (always available)
After the person has confirmed their Job Map and seen their Capability Map, Lens offers the doorway button — **"See what Dex offers for your system"** on a first visit, **"Check Dex — see what's new for your system"** on return visits. Nothing about the session requires pressing it; declining or ignoring it changes nothing about diagnosis (non-negotiable boundary: local-first, useful offline).
### Consent screen (before any network traffic)
Pressing the button does not fetch. It first shows a consent screen in the same style as the existing inspection-permission screen:

- The exact URL that will be requested.
  
- The exact request contents: a plain HTTP GET for a static file, carrying no cookies, no identifiers, no parameters, no personal data — nothing that distinguishes one person from another. (Format compatibility is checked locally after download: if the catalogue is newer than this Lens build understands, Lens says so and suggests updating Lens — it never sends its version to find out.)
  
- What comes back: a signed catalogue describing Dex jobs and capabilities; nothing about the person's system is sent, and nothing on their machine changes.
  
- One approve button, one decline button — plus the option to **subscribe to updates**, which converts this one-off consent into the standing consent described next.
  
### The updates subscription (opt-in background refresh — Dave's amendment, 2026-08-11)
- **Creating it is deliberate:** offered once at the end of the shelf visit ("Want Lens to keep an eye on Dex for you?") and available from the consent screen. The subscription screen states exactly what it authorises: Lens may download the same anonymous catalogue file automatically whenever Lens runs, and may open with a look-or-park prompt when something relevant shifted. Nothing else. Nothing personal leaves the machine — the request is identical to the deliberate-check request.
  
- **Living with it:** subscribed state is always visible on the shelf and consent screens with a one-click off switch. The look-or-park prompt fires only when a _relevant_ shift exists (new or changed entries matching their confirmed jobs), never on every release. **Park** suppresses that shift permanently; only genuinely new shifts prompt again.
  
- **Leaving it:** unsubscribing deletes the subscription record and returns the install to zero-network-without-a-press behaviour.
  
- **Storage:** the subscription flag, last-seen `catalog_version`, and parked-shift markers are stored in Lens's own application directory — never inside the inspected system — and each gets a G2 data-inventory entry with a trivial deletion path. None of them contain personal content.
  
- **v1 boundary:** background refresh happens when Lens runs. True away-from-Lens alerting (a scheduled check + OS notification while Lens is closed) is a separately consented follow-on (§8), not quietly included here.
  
### Fetch, verification, caching, offline
- Deliberate check: one GET per approval, bounded visible retry only. Subscribed: one GET per Lens run, same request. No other schedule exists in v1.
  
- The response envelope goes through the existing `verify_catalog` fail-closed path: signature invalid or content malformed → the whole envelope is rejected and Lens says so plainly.
  
- **Persistence:** the last _verified_ envelope (which contains zero personal data) is stored in Lens's own application directory — never inside the inspected system — and re-verified on load. This gives last-known-good behaviour across sessions and offline. Its storage gets a G2 data-inventory entry with a trivial deletion path.
  
- **Offline / fetch failure:** the shelf still works — Lens uses the last verified catalogue labelled with its age ("verified 12 days ago, release v0.9.2"), or states honestly that no catalogue has ever been verified. Stale is visible, never silent.
  
### Egress budget
The catalogue GET is the _sole_ approved network flow, pinned in the egress harness (G2) in **both postures**: default (traffic only after a per-press approval; zero traffic on a fresh install) and subscribed (traffic at Lens run without a per-press approval). The harness asserts the request carries no canary values or derivations in either posture, and that no other traffic occurs anywhere in the journey, including on the shelf and briefing screens. The endpoint, request fields, subscription flag and failure behaviour become inventoried G2 fields.
## 3. Local relevance matching and the shelf
### Inputs (all already on the machine)
- Confirmed Success Contracts (the person's own jobs, importance, cadence).
  
- The Capability Map: per job, one finding per Foundation Capability with its evidence level — i.e. where the gaps and weak spots are.
  
- The verified catalogue: the jobs taxonomy plus entries with `jobs_served`, `foundation_capabilities`, prerequisites and compatibility.
  
### Mechanism: deterministic, explainable, local
For each catalogue entry, relevance to each _confirmed_ job is computed by rule, not by model:

1. **Job alignment:** the entry serves a catalogue job that aligns with one of the person's confirmed jobs (via the shared taxonomy Lens already uses to propose jobs).
  
2. **Gap match:** the entry strengthens a Foundation Capability where that job's finding shows a gap or weak evidence.
  
3. **Compatibility check:** the entry's machine-checkable requirements are satisfied by (or at least not contradicted by) the observed host system; unmet prerequisites demote the entry and are stated, never hidden.
  
4. **Expected-impact ranking:** relevant entries are ranked by how hard they hit — alignment strength, severity of the gap addressed, number of confirmed jobs helped, importance and cadence of those jobs, then release recency. The top of the shelf is the heaviest-hitting pick, pitched with its grounding in what Lens actually observed.
  

No cloud calls, no embeddings, no profile leaves the machine, nothing is sent anywhere (the matching happens after the fetch; the egress harness proves it).

_Alternative considered — AI/semantic ranking:_ deferred, not rejected. Dave raised AI ranking ("the AI ranks what it thinks will hit heaviest and pitches it back, grounded in their system"). v1 achieves the pitch with deterministic ranking plus grounded presentation, because rule-based ranking over the shared jobs + Foundation Capability vocabulary is explainable, reproducible, and needs no model download or cloud call. If the deterministic shelf proves too coarse, model-assisted ranking can be layered on later under D8's separate model-consent rules — it would still run locally or under explicit consent, and every pitch would still carry its evidence.
### The shelf (the whole supermarket, picked for you)
- **No artificial cap.** Everything genuinely relevant appears in "Picked for your system", ranked by expected impact. (Revision 2 change: the earlier three-item limit is gone, per Dave — the limit was solving oversell, and the honesty rules below solve that without hiding value.)
  
- **The full offering stays browsable.** Below the picks, the entire catalogue is laid out by job aisle, including entries that matched nothing — labelled honestly ("didn't match a job you confirmed"). A first-time visitor sees the whole of what Dex offers; a returning visitor sees new-since-last-look markers.
  
### Honesty rules (product behaviour, enforced in code)
- Every pick carries its reason ("shown because your job 'weekly review' has weak evidence for safe-change recovery") and its uncertainty ("Lens cannot see whether your system already does this another way").
  
- Ranking is never manufactured: an entry with no job alignment cannot appear in picks, and an empty picks list is stated calmly ("Nothing in Dex stands out for the jobs you confirmed — here's the full shelf if you want to browse").
  
- No urgency copy, no manufactured scarcity, no unread-count nagging. The subscription prompt is calm and parkable (§2).
  
## 4. Briefing experience
Selecting a shelf capability opens the briefing screen — two layers, strictly ordered:

**Human layer first** (plain English, for the person): what it is, why it was shown (job-linked), what it needs, honest trade-offs, and the evidence that Dex itself ships and uses it.

**Portable brief second** (for their AI, on their explicit action): a structured Markdown document the person can copy or save to a location of their choosing — never written into the inspected system. It contains:

- the goal in outcome terms, referencing the person's own job wording;
  
- a method outline (how Dex approaches it) written to be _adapted, not pasted_ — it names the concepts, not Dex file paths;
  
- host-tailoring notes derived from the adapter contract and Capability Map (e.g. "your setup keeps skills in `~/.claude/skills`; an equivalent here would be…");
  
- a verification checklist ("you'll know it works when…") and rollback advice;
  
- a visible header stating: this brief is information for the owner's AI; it was produced locally; it grants nothing and changes nothing by itself.
  

The brief is data. Lens never executes it, never offers to apply it, and the existing adaptation machinery does not accept it as input in v1 (see §5).
## 5. Safe adoption handoff (boundary preserved)
The existing rule is untouched: **real-user automatic adaptation stays refused** until Lens can verify a genuine later-use job outcome. The catalogue connection does not unlock writes of any kind. The briefing journey terminates at copy/save. The adaptation preview/approval/undo machinery remains where it is, behind its own separate boundary, and this design deliberately does not connect the catalogue to it. When that connection is ever proposed, it is a new design with its own approval — not an increment of this one.
## 6. End-to-end proof (the definition of "connected")
The bridge is claimed as real only when all of the following pass:

1. **The golden path:** one capability from an actual signed Dex Core release travels release pipeline → publication → doorway button → consent → verified fetch → shelf → briefing → portable brief, into **three representative non-Dex host fixtures**: (a) a minimal hand-rolled Claude Code setup (single CLAUDE.md), (b) a heavily customised Claude Code setup (skills, hooks, subagents), (c) a guided/export-assisted host that Lens's deep adapter cannot inspect. Each produces a coherent, host-appropriate brief.
  
2. **The first-timer path:** a host fixture with no Dex history sees the full shelf (jobs taxonomy aisles + all entries), with picks grounded only in its own confirmed jobs.
  
3. **The subscription loop:** subscribe → a new catalogue version with a relevant entry appears → next Lens run opens with the look-or-park prompt; **park** suppresses that shift permanently; unsubscribe deletes the record and returns the install to zero-traffic-without-a-press (proven by the egress harness in both postures). New-since-last-look markers are correct across versions.
  
4. **Adversarial cases fail safely:** tampered signature; replayed older signed catalogue (rollback refusal); unsigned/malformed envelope; malicious entry content (HTML/script and prompt-injection text render inert everywhere and never perturb matching); entry with unmet prerequisites (demoted and explained); offline press of the button (last-verified or honest none).
  
5. **Egress:** the full journey including shelf and briefing screens re-passes the canary harness with the catalogue GET as the sole approved flow, in both default and subscribed postures.
  
6. **Release gate:** a deliberately broken catalogue entry fails the Core release pipeline (the gate is proven, not assumed).
  
## 7. Public story
After the bridge genuinely passes §6, the README and GitHub About centre the bridge: keep the system you built, see the full shelf of what Dex offers for it, stay in the loop on your terms, bring across only what you want, with your own AI doing the adapting. The in-progress README draft (reviewed with Dave on 2026-08-11) is finished then, with an honest current-vs-future boundary: diagnosis and guided improvement are the pilot candidate today; the connected bridge is described as available only once §6 is true. No copy ships before that.
## 8. Follow-on decisions (explicitly out of the v1 build)
- **Away-from-Lens alerting:** a scheduled background check plus OS notification while Lens is closed — the full version of "proactively comes to the end user." Needs its own opt-in and notification-surface design; recommended as the first follow-on once the in-Lens subscription loop proves itself.
  
- **Model-assisted ranking/pitching** under D8's separate model-consent rules, if the deterministic shelf proves too coarse.
  
- **Connecting briefs to the adaptation machinery** — a new design with its own approval (§5).
  

* * *
## Implementation shape (for the plan that follows approval)
Two repos, explicit ownership, isolated worktrees:

- **Dex Core** (`davekilleen/Dex`): the curated Lens registry (jobs taxonomy + entries) + validator (extending the existing publisher-owned catalogue machinery), the release-pipeline job that assembles/signs/publishes `dex-lens-catalog`, one-time signing-key setup, and the initial entry tranche authored from real shipped skills. Naming avoids Core's existing unrelated "capabilities" (vault rooms) vocabulary.
  
- **Dex Lens** (`davekilleen/dex-lens`): catalogue schema v2 + verifier upgrade + rollback protection + persistence; journey stages and screens (doorway consent, shelf, briefing, subscription); delivery client; relevance matcher + shelf ranking; brief renderer; subscription/last-seen/parked-state storage; G2 inventory entries; egress harness update for both postures; adversarial, first-timer, subscription-loop and e2e fixtures.
  

Sequencing: Lens schema/verifier first (it defines the contract), Core producer against that contract, then delivery + shelf + briefing + subscription, then the §6 proof. Test-driven throughout; no cross-repo work in a shared checkout.
## What this design refuses (so it stays refused)
- Any network contact without the person's explicit consent — per-press or a standing subscription they created and can revoke in one click. A fresh install makes zero requests.
  
- Sending anything about the person's system to Dex — ever, in any posture. The catalogue request is identical for every person on earth.
  
- Auto-applying briefs, or catalogue-triggered writes of any kind.
  
- Catalogue entries from unreleased work.
  
- Manufactured urgency: no unread counts, no nagging re-prompts for parked shifts, no pitch without its grounding shown.
