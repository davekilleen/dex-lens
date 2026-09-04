# Significant-family contract: produce, review, sign, publish

**Trigger:** the release-distance dimension of a Lens diagnosis is disabled —
the evaluation report says "No signed significant-family contract was present
in this catalogue" — because the verified catalogue carries no
`capability_families` collection.

**Owner:** the founder (Dave). Only the founder signs. Nothing in the Lens
repository signs, publishes, or stores key material; every step that touches
the private key runs in the Dex Core release environment.

**What the contract is.** There is no separate signed document. The contract is
the `capability_families` collection inside the one signed catalogue envelope
(`dex-lens-catalogue-v2`). The Ed25519 signature over the canonical
`{metadata, catalogue}` payload covers it; Lens derives
`family_contract_present` from `bool(catalogue.capability_families)` after full
envelope verification (`src/capability_exchange/catalogue/v2.py`,
`src/capability_exchange/diagnosis/defaults.py`). Signing a catalogue that
carries the resolved families is therefore the whole enabling act.

## 1. Produce the draft payload (Lens repo, no key material)

```bash
cd dex-lens
python scripts/generate_family_contract.py
```

This writes `release/significant-family-contract.draft.json`, derived only
from the signature-verified packaged catalogue
(`src/capability_exchange/skill/dex-lens/dex-capabilities.json`) and the
approved family definitions in
`docs/superpowers/plans/2026-09-01-dex-lens-significant-capability-coverage-gate.md`.
To draft against a newer signed envelope instead:

```bash
python scripts/generate_family_contract.py --input /path/to/dex-lens-catalog-latest.json
```

The draft is deterministic and model-validated against the exact source
catalogue, so a payload that generates cleanly will also verify after signing.
`python scripts/generate_family_contract.py --check` fails if the committed
draft has drifted from the generator.

## 2. Review and resolve every TODO

Open `release/significant-family-contract.draft.json`. Each family's
`founder_review` entry lists `TODO(founder)` items and the signed facts
(`member_basis`) the draft membership rests on. Resolve them by editing
`_FAMILY_DEFINITIONS` in `scripts/generate_family_contract.py` and
regenerating — never by hand-editing the output (the `--check` drift gate will
refuse it). The three judgment calls only you can make:

1. **Membership** — confirm or trim each family's `member_capability_ids`.
2. **Assessment** — keep the drafted `automatic`/`catalogue` profile, choose a
   stronger detector profile, or mark a family `manual-only`
   (`privacy-safe-feedback-loop` is drafted `manual-only`).
3. **Tool-level components** — only after Core publishes complete MCP tool
   inventories (`tool_inventory: "complete"`); the current signed catalogue's
   inventories are sampled, so `mcp-tool` components would fail verification
   today.

The family ids must remain exactly the fourteen in
`capability_exchange.diagnosis.expectations.WOW_EXPECTATIONS` — the Wow Gate
expectation rows activate only when all fourteen are signed.

## 3. Carry the resolved families into Dex Core

Core's generator (`scripts/generate-dex-lens-catalog.py` in the Dex repo,
building from `core/lens-catalog/registry.json` and
`core/lens-catalog/enriched-registry.json`) **does not yet emit
`capability_families`** — that is Workstream C Task 9 of the approved coverage
plan: add `core/lens-catalog/significant-capabilities.json` holding the
resolved families and wire the generator to emit them inside
`catalogue.capability_families`. Copy the resolved `capability_families` value
from the draft into that registry; Lens's exported schema
(`schemas/dex-lens-catalogue-v2.schema.json`) is the contract it must satisfy.

Dry-run without signing and confirm the emitted envelope carries the families:

```bash
cd dex
python scripts/generate-dex-lens-catalog.py --enriched --output-dir dist
python -c "import json; e=json.load(open('dist/dex-lens-catalog-latest.json')); \
print(len(e['catalogue']['capability_families']), 'families')"
```

## 4. Sign (Dex Core release environment only)

The private key lives only in the release environment as the base64 PEM secret
`DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64`; the pinned public key in Lens is
`dex-core-lens-1`. With the secret present in that environment:

```bash
python scripts/generate-dex-lens-catalog.py --enriched --sign --output-dir dist
```

This writes `dist/dex-lens-catalog-v<release>.json`,
`dist/dex-lens-catalog-latest.json` and their `.sha256` digests.

## 5. Verify with Lens before anything is published

From the Lens repo, against the freshly signed bytes:

```bash
python - dist/dex-lens-catalog-latest.json <<'EOF'
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

A failure here means Lens in the field would also refuse the catalogue — fix
before publishing, never after.

## 6. Publish

1. **Website** (serves the live catalogue):

   ```bash
   cd heydex-website
   node scripts/prepare-dex-lens-catalogue-static.mjs \
     --source ../dex/dist/dex-lens-catalog-latest.json \
     --dest-root <static root>
   ```

   which places it at the canonical `catalogue/dex-lens/v2.json`.

2. **Lens packaged fallback** (so offline diagnosis carries the contract too):

   ```bash
   cd dex-lens
   python scripts/generate_capability_reference.py --input ../dex/dist/dex-lens-catalog-latest.json
   pytest -q
   ```

## 7. Confirm the dimension is on

On a machine with Lens installed: refresh the catalogue (`dex-lens catalogue`),
run a diagnosis, and check the report. The significant-family section must show
the fourteen signed families and the report must no longer say a signed
significant-family contract is absent; release-distance proposals are now
accepted by `validate_proposal` because `family_contract_present` is true.

**Exit criteria:** the published `catalogue/dex-lens/v2.json` verifies against
the pinned `dex-core-lens-1` key, carries all fourteen `WOW_EXPECTATIONS`
family ids, and a fresh Lens diagnosis renders release-distance /
significant-family rows. No key material, signed-by-test artifacts, or private
data entered either repository.
