# Dex Lens diagnosis-engine publication checklist

**Status:** Prepared after draft pull request #46 went green. Not executed.
**Public product now:** signed Lens v0.1.12
**Proposed next version if Dave approves:** v0.1.13
**Candidate commit at green CI:** `572f2d8ac6f07df01ba1245e14771f07fbd66612`
**Draft PR:** https://github.com/davekilleen/dex-lens/pull/46
**Design PR:** https://github.com/davekilleen/dex-lens/pull/45
**Mission Control:** davekilleen/dex-cards#99

Do not merge, sign, dispatch the release workflow, register MCP, invite
testers, or change `install.sh` until Dave explicitly approves publication.

The release workflow itself refuses anything that is not `main`, a matching
`pyproject.toml` version, a clean tree, and the dedicated signing key.

## What the candidate is

The deterministic diagnosis engine: ledger-derived facts, receipt-backed
decisions, atomic run store, bounded specialists, CLI and read-only MCP,
skill text that follows the engine, and byte-identical golden replay.

## Dave-only publication steps

1. Read this checklist and `docs/STATUS.md`. Confirm you want v0.1.13.
2. Update the human-managed PR #46 body so it links the design, this plan,
   Mission Control, and the golden-replay proof. The agent cannot overwrite
   that description.
3. Merge design PR #45 and implementation PR #46 to `main` only if you want
   the candidate on the public branch.
4. On `main`, bump `pyproject.toml` from `0.1.12` to `0.1.13`, update
   `ENGINE_VERSION` if it should follow the product version, and refresh
   README / STATUS release claims. Do not edit the live installer in that
   same commit unless the signed-release job re-renders it.
5. Dispatch `.github/workflows/release.yml` with `version=0.1.13` and
   `prerelease=true` first if you want a tester URL that is not latest.
6. Only after a signed public-install rehearsal, flip prerelease off and
   point testers at the versioned URL.

## Explicitly not done here

- No merge to `main`
- No version bump
- No signing key use
- No `install.sh` change
- No MCP registration in user config
- No tester invitation
