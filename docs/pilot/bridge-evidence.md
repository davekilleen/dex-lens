# Dex Lens Live Capability Bridge Evidence Pack

Status: SECTION-6 PROOF PASSED; WAVE 2 AND WAVE 3 ACCEPTED LIVE (2026-08-13).
Wave 2 passed in PR #21 CI run 31620154658, artifact 9150895971. The complete
Wave 3 catalogue is proven by the exact-head `Section-6 live bridge proof (Linux)`
check on [PR #22](https://github.com/davekilleen/dex-lens/pull/22/checks); its
download is always named `section6-live-bridge-evidence`. This stable citation
follows the current PR head instead of freezing a superseded run number.
Live rows are marked passed only where the real
`https://heydex.ai/catalogue/dex-lens/v2.json` catalogue was fetched and verified.

Plain-English summary: the real signed Dex catalogue is served from the approved
heydex.ai URL and Lens verifies it against Dave's pinned public key. The live
file now contains all 55 capabilities across 11 jobs: Wave 2's everyday set plus
Wave 3's adoptable role packs and optional rooms. The public README and status
match that release. The final repository merge remains gated on independent
exact-head review.

## What This Evidence Pack Is For

The section-6 proof demonstrates that Dex Lens can privately examine a person's AI
system, show a ranked shelf of relevant Dex capabilities, and produce a safe
portable brief without widening the adaptation boundary.

This document must not be used as a live-claim artifact until every row below has a
passing run attached.

## Current Proof State

| Criterion | Current state | Required final evidence |
|---|---|---|
| Fresh install makes no catalogue request | Passed live in `scripts/section6_live_bridge_proof.py`: after unsubscribe, a returning run made zero catalogue fetches | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Explicit consent performs one catalogue request | Passed live in `scripts/section6_live_bridge_proof.py`: the subscribed returning run made exactly one catalogue fetch | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Real catalogue URL is reachable | Passed live: `https://heydex.ai/catalogue/dex-lens/v2.json` returned 200, 175,296 bytes, SHA-256 `37c100548062be01cad99718402492885ede722365e270898850bb4196863fce`, and was byte-identical to Core release v1.96.1 | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Signed catalogue verifies locally | Passed live: Lens verified Core release v1.96.1 and the heydex.ai-served copy with `default_keyring()` | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Pinned public key matches Core signing secret | Passed live: the real Core-signed catalogue verifies against Lens's pinned `dex-core-lens-1` public key | Keep the tamper-refusal row attached so a mismatch would be a loud failure, not gate-on |
| Exact release identity matches | Passed live: release, key, exact byte hash, catalogue version 3, 55-capability ordered ID set, and 11-job count all matched the release manifest | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Network evidence is complete | Passed live: packet capture was ready, exited cleanly, observed non-loopback egress, and required the capture drop counter to equal zero | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` records the run-specific counts |
| Tampered or mismatched catalogue fails closed | Passed live for signature tampering in `scripts/section6_live_bridge_proof.py`; exact-release mismatch is behaviorally tested and writes a structured failed receipt | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Broken Core catalogue refuses release publication | Passed in Core PR #507: malformed or duplicate public identifiers now fail before signing. Lens rejected v1.96.0's two underscore-bearing requirements before deployment; immutable correction v1.96.1 superseded it as catalogue version 3 | Core CI 31655118833 and macOS canary 31655118745 passed at the exact correction head |
| Local adversarial catalogue cases fail safely | Passed locally for tampered, replayed older, malformed/unsigned-equivalent, hostile inert content, unmet host prerequisites demoted/explained, and offline stale cache | Local proof merged in PR #15; fresh live tamper refusal attached in PR #21 |
| Minimal first-time host gets a shelf and brief | Passed live in the canonical `scripts/section6_live_bridge_proof.py` journey | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Customised Claude host gets a shelf and brief | Passed live in the canonical `scripts/section6_live_bridge_proof.py` journey | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Guided/export-assisted host gets a shelf and brief | Passed live in the canonical `scripts/section6_live_bridge_proof.py` journey | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Three briefs are host-appropriate | Passed live: minimal, customised, and guided/export briefs contain host-specific context and are non-identical | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Subscription loop across runs | Passed live in `scripts/section6_live_bridge_proof.py`: a subscriber last seen on version 2 fetched live version 3 once, saw the newer-version prompt, parked version 3, saw that prompt suppressed on the next one-fetch run, revoked, then made zero fetches on the next run | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Public copy remains honest | Passed by inspection: public copy says the bridge is live for the complete 55-capability catalogue and names both the everyday and role/optional sets | Reconciled in this PR with the exact live release identity |
| Signing key exists | Passed by source inspection: `dex-core-lens-1` is pinned in Lens main after Dave returned the public key, and GitHub reports the expected Core secret name exists without exposing the secret value | Key-correspondence still requires the real signed-catalogue proof row above |
| Wave 2 capability set exists | Passed live: the real catalogue carries the complete ordered set of 25 approved everyday capabilities and Lens renders all 25 for both deep host fixtures | Attached in PR #21 live-proof run 31620154658, artifact 9150895971 |
| Wave 3 capability set exists | Passed live: the real catalogue carries the exact 24 lifecycle / 5 room / 1 active Wave 3 partition, bringing the ordered total to 55; all 90 Wave 3 evidence records remain honestly `supported`, not `verified` | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Live catalogue deploy | Passed live: heydex.ai serves the signed v1.96.1 catalogue from the canonical URL and its bytes match the GitHub release | Current exact-head PR #22 check; artifact `section6-live-bridge-evidence` |
| Public live claim approved and shipped | Dave directly instructed this delivery to ship; README and status now match the live 55-capability catalogue | Exact live acceptance attached to PR #22; independent review remains the merge gate |

## Remaining Programme Work

- Pass independent exact-head release reviews, then merge this reconciliation
  without changing the proven release identity.

## Evidence Notes

- Core v1.96.0 remains an immutable historical release, but it was never deployed
  to the canonical Lens URL. Lens rejected its two malformed quarterly requirement
  IDs before publication; v1.96.1/catalogue version 3 is the deployed correction.
- The final receipt records `subscribed_prompt_rendered: true`,
  `parked_version: 3`, and `parked_prompt_suppressed: true`. It therefore proves
  the newer-version look-or-park path rather than merely exercising a subscriber
  who had already seen the current catalogue.
