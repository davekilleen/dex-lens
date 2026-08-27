# Dex Lens diagnosis-engine publication checklist

**Status:** Dave approved publication on 2026-08-27. Executing.
**Public product becoming:** signed Lens v0.1.13
**Green candidate:** `572f2d8ac6f07df01ba1245e14771f07fbd66612`
**Implementation PR:** https://github.com/davekilleen/dex-lens/pull/46
**Design PR:** https://github.com/davekilleen/dex-lens/pull/45
**Mission Control:** davekilleen/dex-cards#99

The live `install.sh` in the repository is not hand-edited. The signed
release workflow renders the public installer from the signed manifest.

## Done

1. Dave approved going live.
2. Pull requests #45 and #46 marked ready for review.
3. The green candidate stack merged to `main`.
4. Product version bumped to `0.1.13` (`pyproject.toml`, package,
   `ENGINE_VERSION`, README, STATUS).

## Remaining in this publication

5. Dispatch `.github/workflows/release.yml` with `version=0.1.13` and
   `prerelease=false` so the public one-line install serves the engine.
6. Confirm the GitHub Release `v0.1.13` exists and
   `releases/latest/download/install.sh` is the signed v0.1.13 installer.

## Still not done here

- MCP registration in user config
- Tester invitation
- A second hand-edit of the repository `install.sh`
