# Dex Lens diagnosis-engine publication checklist

**Status:** Published. Signed latest is v0.1.16.
**Public product:** signed Lens v0.1.16
**Published commit:** `0088b0cbbbf912694799762a1f4530d2e0b50be6`
**Release run:** https://github.com/davekilleen/dex-lens/actions/runs/34335528042
**GitHub Release:** https://github.com/davekilleen/dex-lens/releases/tag/v0.1.16
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

Nothing. All three steps completed 2026-09-09:

1. The v0.1.16 release preparation landed on `main` (PR #58, `e805bfc`,
   merged as `0088b0c`).
2. The `Release Dex Lens` dispatch (`34335528042`) on `0088b0c` succeeded
   and published GitHub Release `v0.1.16` with its six assets.
3. `releases/latest/download/install.sh` declares
   `DEX_LENS_VERSION=0.1.16` (verified by download).

## Still not done here

- MCP registration in user config
- Tester invitation
- A second hand-edit of the repository `install.sh`
