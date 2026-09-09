# Signing checklist: the significant-family catalogue release (2026-09-09)

This is the founder's step list for turning the approved family contract into
the live catalogue at `https://heydex.ai/catalogue/dex-lens/v2.json`. It
follows `docs/runbooks/significant-family-contract.md`; each step names the
machine and repository it runs in. Nothing in the Lens repository signs,
publishes, or stores key material.

**Why now.** The catalogue served today (Core release v1.97.2, catalogue
version 6) carries no `capability_families` collection, so every Lens run
against it disables the release-distance dimension and the report says a
signed significant-family contract is absent. The enriched build Core
generated on 2026-09-07 (release v1.97.12, 117 capabilities) carries all
fourteen families, and they match the founder-approved Lens draft
(`release/significant-family-contract.draft.json`) field for field —
verified in this worktree on 2026-09-09. What remains is Core-side: fix one
version number, sign, publish, and verify.

**One blocking correction before signing.** The 2026-09-07 enriched build
stamped `catalog_version: 6` — the same number as the catalogue already
published (v1.97.2 is catalogue version 6). Lens compares catalogue versions
in two places, and an equal number fails both quietly: the newer-version
prompt only fires when the fetched version is *greater* than the last one a
machine saw (`should_prompt` in
`src/capability_exchange/catalogue/subscription.py`), and rollback
protection only refuses versions that are *lower* than the highest verified
(`src/capability_exchange/catalogue/v2.py`) — so a second "version 6" would
be accepted and stored with no signal that anything changed. **The new
release must be signed as catalogue version 7.** The runbook does not cover
where Core's generator sets `catalog_version`; find and bump it in the Dex
repo before the signing run.

## Already done (Lens repo, this worktree — no action needed)

- `python scripts/generate_family_contract.py --check` passes: the committed
  draft is the exact generator output, all fourteen families carry the
  founder's digest-bound 2026-09-07 resolution, no open `TODO(founder)`
  items.
- The enriched build's `capability_families` was compared to the draft:
  fourteen families, identical ids, titles, outcomes, jobs, members,
  components and assessments; `privacy-safe-feedback-loop` is `manual-only`
  and every other family is `automatic`/`catalogue`. All 117 capabilities
  validate as `CatalogueV2`, every family member id exists in
  `capabilities`, and all four capability classes are present.
- Fail-closed check: the unsigned enriched build is refused by
  `verify_catalogue_envelope` with Lens's default keyring, as it must be
  until the production key signs it.

## Steps for the founder

### In the Dex repo, on the Core release machine

1. Confirm the family registry is in place. The runbook (step 3) says the
   resolved families go into `core/lens-catalog/significant-capabilities.json`
   and the generator emits them as `catalogue.capability_families`. The
   2026-09-07 enriched build already emits families matching the Lens draft
   exactly, so this appears done — confirm rather than redo. If anything in
   the registry has changed since 2026-09-07, stop and re-run the Lens draft
   comparison first: the founder approval is digest-bound, and changed
   family content reopens review.

2. Bump the catalogue version to 7 in Core's generator (see the blocking
   correction above). The runbook does not cover where this number is set.

3. Dry-run without signing (runbook step 3):

   ```bash
   cd dex
   python scripts/generate-dex-lens-catalog.py --enriched --output-dir dist
   python -c "import json; e=json.load(open('dist/dex-lens-catalog-latest.json')); \
   print(len(e['catalogue']['capability_families']), 'families, catalog v', \
   e['metadata']['catalog_version'])"
   ```

   Expect: `14 families, catalog v 7`. If the release Core stamps is no
   longer v1.97.12, note the actual release string — step 8 needs it.

### In the Dex Core release environment (the only place the key exists)

4. Sign (runbook step 4). The private key is the release-environment secret
   named `DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64`; the matching public key
   pinned in Lens is `dex-core-lens-1`.

   ```bash
   python scripts/generate-dex-lens-catalog.py --enriched --sign --output-dir dist
   ```

   This writes `dist/dex-lens-catalog-v<release>.json`,
   `dist/dex-lens-catalog-latest.json`, and their `.sha256` digests.

### In the Lens repo, before anything is published

5. Verify the freshly signed bytes with Lens (runbook step 5 — a failure
   here means Lens in the field would also refuse it; fix before
   publishing, never after). From the Lens repo root, using the repo's own
   interpreter:

   ```bash
   cd dex-lens
   .venv/bin/python - ../dex/dist/dex-lens-catalog-latest.json <<'EOF'
   import sys
   from pathlib import Path
   from capability_exchange.catalogue.v2 import default_keyring, verify_catalogue_envelope
   from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS

   envelope = verify_catalogue_envelope(
       Path(sys.argv[1]).read_text(encoding="utf-8"), keyring=default_keyring()
   )
   signed = [f.family_id for f in envelope.catalogue.capability_families]
   assert signed, "no capability_families: the contract is still absent"
   assert set(WOW_EXPECTATIONS) <= set(signed), sorted(set(WOW_EXPECTATIONS) - set(signed))
   print(f"verified: {len(signed)} signed families, catalog v{envelope.metadata.catalog_version}")
   EOF
   ```

   Expect: `verified: 14 signed families, catalog v7`.

### In the heydex-website repo

6. Publish to the canonical URL (runbook step 6.1):

   ```bash
   cd heydex-website
   node scripts/prepare-dex-lens-catalogue-static.mjs \
     --source ../dex/dist/dex-lens-catalog-latest.json \
     --dest-root <static root>
   ```

   This places the file at `catalogue/dex-lens/v2.json`. The runbook does
   not cover how the static root deploys to the live site; use whatever
   deploy step the website repo already uses.

### In the Lens repo, after publishing

7. Refresh the packaged offline fallback (runbook step 6.2):

   ```bash
   cd dex-lens
   .venv/bin/python scripts/generate_capability_reference.py \
     --input ../dex/dist/dex-lens-catalog-latest.json
   .venv/bin/python -m pytest -q
   ```

8. Complete the release manifest `docs/pilot/live-catalogue-release.json`.
   A draft is already staged in this worktree with the new capability list
   (117 ids), catalogue version 7, and job count 8. Two fields wait on the
   signed bytes:

   - `raw_sha256` — currently sixty-four zeros on purpose; replace it with
     the digest from `dist/dex-lens-catalog-latest.json.sha256`. Until it is
     replaced, the exact-identity check refuses loudly instead of passing a
     wrong file.
   - `core_release` — drafted as `v1.97.12`; correct it if the signing run
     stamped a different release.

   This manifest is what CI's live-bridge proof
   (`scripts/section6_live_bridge_proof.py --expectation-manifest ...` in
   `.github/workflows/ci.yml`) checks the live URL against, so it must land
   in the same change as the publish. The signing runbook itself does not
   mention this manifest; the requirement comes from that CI check.

   One test pins the checked-in manifest to the identity that is live:
   `test_checked_in_live_release_manifest_is_the_exact_complete_catalogue_identity`
   in `tests/catalogue/test_release_acceptance.py` currently asserts
   v1.97.2, catalogue version 6, 115 capabilities and the old digest. It
   fails against this draft on purpose — the manifest describes what is
   live, and the new catalogue is not live yet. Update that test's expected
   values (release, version 7, count 117, the real digest) in the same
   change as the completed manifest, after publishing, and run the test
   file alone as well as in the suite:

   ```bash
   .venv/bin/python -m pytest tests/catalogue/test_release_acceptance.py
   .venv/bin/python -m pytest -q
   ```

### On a machine with Lens installed

9. Prove the live file is on (runbook step 7). The exact command:

   ```bash
   dex-lens catalogue
   ```

   This fetches `https://heydex.ai/catalogue/dex-lens/v2.json`, verifies the
   signature against the pinned `dex-core-lens-1` key on the local machine,
   and prints the catalogue digest. Then run a diagnosis and check the
   report: the significant-family section must show the fourteen signed
   families, and the report must no longer say a signed significant-family
   contract is absent.

**Exit criteria (from the runbook):** the published
`catalogue/dex-lens/v2.json` verifies against the pinned `dex-core-lens-1`
key, carries all fourteen expected family ids, and a fresh Lens diagnosis
renders release-distance and significant-family rows. No key material,
signed-by-test artifacts, or private data entered either repository.
