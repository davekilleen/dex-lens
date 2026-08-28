# Dex Lens diagnosis-engine publication checklist

**Status:** Dave approved publication of chat-native approval on 2026-08-28.
**Public product becoming:** signed Lens v0.1.14
**Chat-approve PR:** https://github.com/davekilleen/dex-lens/pull/49
**Previous public release:** https://github.com/davekilleen/dex-lens/releases/tag/v0.1.13
**Mission Control:** davekilleen/dex-cards#99

The live `install.sh` in the repository is not hand-edited. The signed
release workflow renders the public installer from the signed manifest.

## Done

1. Signed Lens v0.1.13 published (run `33122132016`).
2. First real vault dogfood died on the local approval page.
3. Chat-native `diagnosis approve` landed on `main` (PR #49, `2c4a68d`).
4. Product version bumped to `0.1.14`.

## Remaining in this publication

5. Dispatch `.github/workflows/release.yml` with `version=0.1.14` and
   `prerelease=false`.
6. Confirm the GitHub Release `v0.1.14` exists and
   `releases/latest/download/install.sh` declares
   `DEX_LENS_VERSION=0.1.14`.

## Still not done here

- MCP registration in user config
- Tester invitation
- A second hand-edit of the repository `install.sh`
