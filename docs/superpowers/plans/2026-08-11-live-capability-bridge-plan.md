# Live Capability Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status, 11 August 2026:** live execution plan for the approved design in
> `docs/superpowers/specs/2026-08-11-dex-lens-live-capability-bridge-design.md`
> (approved by Dave, 2026-08-11). Cross-repo: Lens tasks live in this repo;
> Core tasks live in `davekilleen/Dex` and are labelled **[CORE]**. No task may
> weaken an existing gate (G1–G6, R1–R7); the adaptation refusal boundary is
> untouched by every task below.

**Goal:** One capability from an actual signed Dex Core release travels
publication → doorway consent → verified fetch → ranked shelf → briefing →
portable brief into three representative non-Dex hosts, with the opt-in
updates subscription working, every adversarial case failing safely, and the
catalogue GET pinned as the sole approved egress in both consent postures.

**Architecture:** Contract-first. Lens's catalogue schema v2 (jobs taxonomy +
human-meaningful entries + versioned signed envelope) is the cross-repo
contract; Core's producer emits it, Lens's verifier enforces it. All matching
is deterministic and local over the shared job/Foundation-Capability
vocabulary. Delivery uses stdlib HTTPS only (no new runtime dependency);
catalogue bytes are untrusted data everywhere — bounded, validated, escaped,
never interpreted. Subscription, last-seen version and parked shifts are small
inventoried local records with trivial deletion.

**Tech Stack:** Lens: Python, Pydantic, stdlib `urllib` behind a port,
existing concierge server/views, pytest + hostile fixtures + egress harness.
Core: existing release pipeline (`scripts/build-release.sh`, catalogue
generator/coverage gates, GitHub Actions `build-release` job, Pages deploy),
Ed25519 via `cryptography` in the release workflow only.

---

## Phase 1 — the contract (Lens repo)

### Task 1: Catalogue schema v2 and verifier upgrade

**Files:**
- Modify: `src/capability_exchange/catalog/verify.py`
- Create: `src/capability_exchange/catalog/schema.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`
- Test: `tests/catalog/test_schema_v2.py`
- Test: `tests/catalog/test_verify_v2.py`

- [ ] Write failing tests: a v2 envelope carries `catalog_format`, strictly
      increasing `catalog_version`, `issued_at`, `core_release`, a jobs
      taxonomy section, and entries with all twelve fields from the spec;
      over-length text, control characters, unknown fields, missing jobs
      references (`jobs_served` pointing at absent `job_id`s) and non-release
      provenance are unconstructable.
- [ ] Write failing tests for rollback protection: a genuinely signed envelope
      with `catalog_version` lower than the last verified one is refused with
      a plain-language message, and the last verified catalogue is retained.
- [ ] Implement `schema.py` (jobs + entry + envelope models, closed and
      bounded like existing `InventoriedModel` types) and extend
      `verify_catalog`/`CatalogVerifier` with version monotonicity.
- [ ] Inventory every new persisted field in `data_inventory.yaml` (G2 CI gate
      must pass, not be waived).
- [ ] Re-run the full catalog test module plus the data-inventory gate.

### Task 2: Local bridge state — last-verified envelope, last-seen version, subscription, parked shifts

**Files:**
- Create: `src/capability_exchange/catalog/store.py`
- Modify: `src/capability_exchange/boundary/data_inventory.yaml`
- Test: `tests/catalog/test_store.py`

- [ ] Write failing tests: the store lives only in Lens's own application
      directory (never inside an approved inspection root — constructing it
      under one refuses); a loaded envelope is re-verified before use; a
      tampered stored envelope degrades to "none" honestly; subscription
      on/off, last-seen `catalog_version` and parked-shift markers round-trip;
      deletion removes the bytes; none of the records can contain personal
      content by construction.
- [ ] Implement the store with atomic writes and explicit deletion paths;
      inventory each record (G2).
- [ ] Re-run focused tests and the egress-relevant boundary tests.

## Phase 2 — the producer (Core repo, parallel with Phase 3)

### Task 3 [CORE]: Lens catalogue registry and validator

**Files (in `davekilleen/Dex`):**
- Create: `core/lifecycle/catalog/lens-catalog-registry.json` (jobs taxonomy + curated entries)
- Create: `scripts/generate-lens-catalog.py`
- Create: `scripts/check-lens-catalog.py`
- Test: `tests/` following Core's existing catalogue-gate test conventions

- [ ] Write failing checks mirroring Core's existing catalogue gates: every
      entry references a skill that exists in the release tree with a pinned
      content hash; text fields are bounded; `jobs_served` references resolve;
      the emitted envelope validates against the Lens v2 schema (vendored
      JSON Schema exported from Task 1 so the two repos cannot drift
      silently).
- [ ] Implement the generator (derive id/version-hash/release/description from
      the shipped skill; carry authored `value`, `jobs_served`,
      `foundation_capabilities`, `prerequisites`, `trade_offs`, `brief`,
      `compatibility`, `docs_url`, `since_release`) and the fail-closed checker.
- [ ] Name everything `lens-catalog`, never bare "capabilities" (Core already
      uses that word for vault rooms).
- [ ] Author the initial tranche with Dave: every taxonomy job covered by at
      least one entry; target the most-used shipped skills first.

### Task 4 [CORE]: Signing and publication in the release pipeline

**Files (in `davekilleen/Dex`):**
- Modify: `scripts/build-release.sh`
- Modify: `.github/workflows/ci.yml` (`build-release` job + Pages deploy job)
- Create: `scripts/sign-lens-catalog.py`

- [ ] One-time founder step (exact commands delivered to Dave; private key
      never touches a checkout): generate an Ed25519 keypair, store the
      private key as a GitHub Actions environment secret scoped to the release
      workflow, keep an offline backup, hand the public key + `key_id` to
      Task 5.
- [ ] Write a failing pipeline check: a release build with an invalid or
      missing signed `dex-lens-catalog-v<version>.json` fails before tagging
      (extend the existing fail-closed catalogue gates).
- [ ] Implement signing (canonical payload bytes, Ed25519, `key_id`) and
      publication: release asset + `.sha256` sidecar on the existing guarded
      upload path, and the same envelope served from the repo's GitHub Pages
      site as the stable latest URL.
- [ ] Prove the gate: a deliberately broken registry entry fails the pipeline
      in a dry run; record the run as evidence.

## Phase 3 — the journey (Lens repo)

### Task 5: Delivery client and pinned egress

**Files:**
- Create: `src/capability_exchange/catalog/delivery.py`
- Modify: `tests/egress/harness.py`
- Test: `tests/catalog/test_delivery.py`
- Test: `tests/egress/test_catalog_flow.py`

- [ ] Write failing tests: the client issues exactly one stdlib HTTPS GET to
      the pinned endpoint with no cookies, no query parameters, no identifying
      headers; one bounded visible retry; response size capped; the raw bytes
      go only to the Task 1 verifier; Lens's public-key table (`key_id` →
      key) verifies the Core signature; format-newer-than-understood is
      reported locally with an update suggestion, never negotiated over the
      wire.
- [ ] Write failing egress-harness assertions for **both postures**: default
      (zero traffic on a fresh install; traffic only after a per-press
      approval) and subscribed (one GET at Lens run, no per-press consent),
      with planted canaries and their derivations never on the wire.
- [ ] Implement the client behind a port so tests inject fakes; wire the
      public keys.
- [ ] Re-run the full egress suite at the syscall/packet level, both postures.

### Task 6: Journey stages and screens — doorway, shelf, briefing, subscription

**Files:**
- Modify: `src/capability_exchange/concierge/journey.py`
- Modify: `src/capability_exchange/concierge/server.py`
- Modify: `src/capability_exchange/concierge/views.py`
- Test: `tests/concierge/test_catalog_stages.py`
- Test: `tests/concierge/test_catalog_views.py`

- [ ] Write failing tests for new stages after `CAPABILITY_MAP`:
      `CATALOG_CONSENT` (exact URL and request contents rendered before any
      traffic; decline returns to the map unchanged), `CATALOG_SHELF`,
      `CATALOG_BRIEFING`, plus subscription create/revoke and the
      look-or-park prompt on session open for subscribed installs (park
      suppresses that shift permanently; unsubscribe deletes the record). No
      new stage carries a write capability; adaptation stages remain
      unreachable from catalogue stages.
- [ ] Write failing view tests: catalogue text renders escaped everywhere
      (hostile HTML/script/prompt-injection fixtures from Task 9 render
      inert); `PermissionMetadata.no_catalog` flips only after a verified
      catalogue exists; offline shows the last verified catalogue with its
      age or an honest "none"; button copy follows the spec (first visit vs
      returning).
- [ ] Implement stages, handlers and screens in the existing server-rendered
      style with CSRF on every form.
- [ ] Re-run the full concierge suite including session-security tests.

### Task 7: Relevance matcher and shelf ranking

**Files:**
- Create: `src/capability_exchange/catalog/match.py`
- Test: `tests/catalog/test_match.py`

- [ ] Write failing tests: deterministic given identical inputs; an entry with
      no confirmed-job alignment can never appear in picks; unmet
      machine-checkable prerequisites demote and annotate, never hide
      silently; ranking follows the spec order (alignment strength, gap
      severity, jobs helped, importance/cadence, recency); every pick carries
      its machine-readable reason and uncertainty note; empty picks with a
      browsable full shelf is a first-class result; new-since-last-look
      markers derive from `since_release`/`changed_in` and the stored
      last-seen version.
- [ ] Implement pure functions over confirmed `SuccessContract`s, the
      `CapabilityMap`, and verified v2 entries — no I/O, no model calls.
- [ ] Property-test ranking stability and the no-manufactured-relevance rule.

### Task 8: Briefing renderer and portable brief

**Files:**
- Create: `src/capability_exchange/catalog/brief.py`
- Modify: `src/capability_exchange/concierge/views.py`
- Test: `tests/catalog/test_brief.py`

- [ ] Write failing tests: human layer precedes the portable brief; the brief
      is generated locally from the entry's `brief` material plus
      host-tailoring derived from the adapter contract and Capability Map;
      it references the person's own job wording; it carries the mandatory
      header (produced locally, grants nothing, changes nothing by itself);
      save targets are always outside the approved inspection roots; the
      adaptation machinery rejects a brief as input.
- [ ] Implement rendering (copy + save affordances) in the existing view style.
- [ ] Re-run brief, view, and boundary suites.

## Phase 4 — proof (both repos)

### Task 9: Adversarial and hostile-content fixtures

**Files:**
- Create: `tests/fixtures/hostile/catalog_v2.py`
- Test: `tests/catalog/test_adversarial.py`

- [ ] Build fixtures: tampered signature; replayed older signed envelope;
      unsigned/malformed envelope; format-from-the-future; entries carrying
      HTML/script and prompt-injection payloads in every text field;
      `jobs_served`/prerequisite mismatches; oversized envelope.
- [ ] Write tests proving each fails safely per the spec (rejection message,
      last-verified retention, inert rendering, unperturbed matching) with
      zero writes and zero egress.

### Task 10: End-to-end golden paths and the §6 evidence pack

**Files:**
- Create: `tests/e2e/test_bridge_golden_path.py`
- Create: `tests/e2e/hosts/` (three representative host fixtures)
- Create: `docs/pilot/bridge-evidence.md`

- [ ] Build the three host fixtures: minimal single-CLAUDE.md setup; heavily
      customised setup (skills, hooks, subagents); guided/export-assisted
      host without deep-adapter support.
- [ ] Golden path: a real signed envelope produced by Task 4's pipeline (from
      an actual Core release) travels doorway → consent → verified fetch →
      shelf → briefing → portable brief in all three hosts, offline replay
      included; assert each brief is coherent and host-appropriate.
- [ ] First-timer path: fresh host sees the full shelf with taxonomy aisles;
      subscription loop: subscribe → new relevant version → look-or-park on
      next run → park suppresses permanently → unsubscribe returns to
      zero-traffic (egress-proven).
- [ ] Full egress harness re-run over the complete journey in both postures.
- [ ] Write the evidence pack mapping every §6 spec criterion to its passing
      test/run, including the Core pipeline-gate proof from Task 4.

### Task 11: Delivery transaction — status surfaces reconciled

**Files:**
- Modify: `README.md`
- Modify: `docs/STATUS.md`
- Modify (dex-cards): `dex-lens-live-capability-bridge.md`

- [ ] Only after Task 10 is green: update the README's "where this stands
      today" boundary to describe the live bridge as real, per the approved
      public story (§7) — ask Dave before this publish, since it changes the
      outward claim.
- [ ] Update `docs/STATUS.md`, the Build Card (status, PR, merge commit,
      date, evidence), and log the Dispatch finish event in the same
      transaction as the merge.

---

## Sequencing and ownership

1. Task 1–2 first (Lens; they define the contract and are prerequisites for
   everything).
2. Tasks 3–4 [CORE] and Tasks 5–8 (Lens) proceed in parallel in separate
   worktrees/agents — never a shared checkout; the vendored schema from
   Task 1 is the only coupling point.
3. Tasks 9–10 run once both sides land; Task 11 closes the transaction.

Founder dependencies (exactly two, both in Task 4): approve the one-time
signing-key setup, and choose the initial capability tranche with the
implementer. Everything else needs no Dave input.
