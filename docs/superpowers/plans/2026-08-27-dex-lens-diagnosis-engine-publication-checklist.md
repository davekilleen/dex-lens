# Dex Lens diagnosis-engine publication checklist

**Status:** Published. Signed Lens v0.1.15 is latest.
**Public product:** signed Lens v0.1.15
**Published commit:** `d009a8d907572ae32880f629d7a311f6fcc377de`
**Release run:** https://github.com/davekilleen/dex-lens/actions/runs/33167244234
**GitHub Release:** https://github.com/davekilleen/dex-lens/releases/tag/v0.1.15
**First-look PR:** https://github.com/davekilleen/dex-lens/pull/50
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
7. First-look skill fix landed on `main` as `0.1.15` (PR #50).
8. GitHub Release `v0.1.15` exists, is not a prerelease, and
   `releases/latest/download/install.sh` declares
   `DEX_LENS_VERSION=0.1.15`.

## Remaining in this publication

None.

## Still not done here

- MCP registration in user config
- Tester invitation
- A second hand-edit of the repository `install.sh`
