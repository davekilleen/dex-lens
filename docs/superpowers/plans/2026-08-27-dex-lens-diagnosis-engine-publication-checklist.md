# Dex Lens diagnosis-engine publication checklist

**Status:** Published. Signed Lens v0.1.13 is latest.
**Public product:** signed Lens v0.1.13
**Published commit:** `5f6fee6af78356decade4417e64e58a7f5c6bfcf`
**Release run:** https://github.com/davekilleen/dex-lens/actions/runs/33122132016
**GitHub Release:** https://github.com/davekilleen/dex-lens/releases/tag/v0.1.13
**Implementation PR:** https://github.com/davekilleen/dex-lens/pull/46
**Design PR:** https://github.com/davekilleen/dex-lens/pull/45
**Wheelhouse lock PR:** https://github.com/davekilleen/dex-lens/pull/47
**Mission Control:** davekilleen/dex-cards#99

The live `install.sh` in the repository is not hand-edited. The signed
release workflow renders the public installer from the signed manifest.

## Done

1. Dave approved going live.
2. Pull requests #45 and #46 marked ready for review.
3. The green candidate stack merged to `main`.
4. Product version bumped to `0.1.13` (`pyproject.toml`, package,
   `ENGINE_VERSION`, README, STATUS).
5. First `Release Dex Lens` dispatch (`33121192613`) failed at bind:
   the version field was not the exact `0.1.13` string.
6. Second dispatch (`33121336098`) on `23220d5` built and signed, then
   all four install-proof jobs failed: the offline wheelhouse did not
   vendor `mcp>=2.1.1,<3`, so `pip` could not install
   `capability-exchange` without PyPI.
7. `release/runtime-requirements.txt` pinned `mcp==2.1.1` and its
   closed transitive set (PR #47, `5f6fee6`).
8. Third dispatch (`33122132016`) on `5f6fee6` succeeded: bind,
   contract checks, sign, all four install proofs (Ubuntu/macOS ×
   3.11/3.14), and publish.
9. GitHub Release `v0.1.13` exists, is not a prerelease, and
   `releases/latest/download/install.sh` declares
   `DEX_LENS_VERSION=0.1.13`.

## Remaining in this publication

None. Publication of the diagnosis engine is complete.

## Still not done here

- MCP registration in user config
- Tester invitation
- A second hand-edit of the repository `install.sh`
