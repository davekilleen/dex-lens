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
5. First `Release Dex Lens` dispatch (`33121192613`) failed at bind:
   the version field was not the exact `0.1.13` string.
6. Second dispatch (`33121336098`) on `23220d5` built and signed, then
   all four install-proof jobs failed: the offline wheelhouse did not
   vendor `mcp>=2.1.1,<3`, so `pip` could not install
   `capability-exchange` without PyPI.
7. `release/runtime-requirements.txt` now pins `mcp==2.1.1` and its
   closed transitive set. Offline `pip download --only-binary=:all:
   --no-deps` succeeds for `linux-x86_64` and `macos-arm64` at
   CPython 3.11–3.14. A release-contract test now fails if a declared
   application dependency is missing from that lock.

## Remaining in this publication

8. Land the wheelhouse lock on `main`, wait for CI, then dispatch
   `.github/workflows/release.yml` again with `version=0.1.13` and
   `prerelease=false`. Do not bump the product version: v0.1.13 was
   never published.
9. Confirm the GitHub Release `v0.1.13` exists and
   `releases/latest/download/install.sh` is the signed v0.1.13 installer.

## Still not done here

- MCP registration in user config
- Tester invitation
- A second hand-edit of the repository `install.sh`
