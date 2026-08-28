# Dex Lens diagnosis-engine publication checklist

**Status:** Published. Signed Lens v0.1.14 is latest.
**Public product:** signed Lens v0.1.14
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

None.

## Still not done here

- MCP registration in user config
- Tester invitation
- A second hand-edit of the repository `install.sh`
