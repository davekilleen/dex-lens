# Dex Lens diagnosis-engine publication checklist

**Status:** Preparing signed Lens v0.1.15. Signed latest is still v0.1.14.
**Public product:** signed Lens v0.1.14 until `v0.1.15` exists
**Published commit:** `7aa1587318821a49743f53e3ee1fb766d0d5aadc`
**Release run:** https://github.com/davekilleen/dex-lens/actions/runs/33166503410
**GitHub Release:** https://github.com/davekilleen/dex-lens/releases/tag/v0.1.14
**Chat-approve PR:** https://github.com/davekilleen/dex-lens/pull/49
**Mission Control:** davekilleen/dex-cards#99

The live `install.sh` in the repository is not hand-edited. The signed
release workflow renders the public installer from the signed manifest.

## Done

1. Signed Lens v0.1.13 published (run `33122132016`).
2. First real vault dogfood died on the local approval page.
3. Chat-native `diagnosis approve` landed on `main` (PR #49, `2c4a68d`).
4. Product version bumped to `0.1.14`.
5. `Release Dex Lens` dispatch (`33166503410`) on `7aa1587` succeeded.
6. GitHub Release `v0.1.14` exists, is not a prerelease, and
   `releases/latest/download/install.sh` declares
   `DEX_LENS_VERSION=0.1.14`.

## Remaining in this publication

1. Land the first-look skill fix on `main` as product version `0.1.15`.
2. Tag `v0.1.15` so the signed installer picks up the new skill.
3. Confirm `releases/latest/download/install.sh` declares
   `DEX_LENS_VERSION=0.1.15`.

## Still not done here

- MCP registration in user config
- Tester invitation
- A second hand-edit of the repository `install.sh`
