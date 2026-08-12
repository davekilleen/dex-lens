# Dex Lens Live Capability Bridge Evidence Pack

Status: SECTION-6 PROOF PASSED; PUBLIC AVAILABILITY CLAIM APPROVED BY DAVE
(2026-08-12). The Wave 2 catalogue is live and Lens accepted its exact signed
release in PR #21 CI run 31618570194, artifact 9150282037. Local Lens-side proof
rows are marked passed only where automated tests prove them. Live rows are
marked passed only where the real
`https://heydex.ai/catalogue/dex-lens/v2.json` catalogue was fetched and verified.

Plain-English summary: the real signed Dex catalogue is served from the approved
heydex.ai URL and Lens verifies it against Dave's pinned public key. The
section-6 proof has passed, Dave approved the public availability wording, and
the public README/status now accurately records all 25 approved everyday capabilities
in the shipped Wave 2 catalogue.

## What This Evidence Pack Is For

The section-6 proof demonstrates that Dex Lens can privately examine a person's AI
system, show a ranked shelf of relevant Dex capabilities, and produce a safe
portable brief without widening the adaptation boundary.

This document must not be used as a live-claim artifact until every row below has a
passing run attached.

## Current Proof State

| Criterion | Current state | Required final evidence |
|---|---|---|
| Fresh install makes no catalogue request | Passed live in `scripts/section6_live_bridge_proof.py`: after unsubscribe, a returning run made zero catalogue fetches | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Explicit consent performs one catalogue request | Passed live in `scripts/section6_live_bridge_proof.py`: the subscribed returning run made exactly one catalogue fetch | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Real catalogue URL is reachable | Passed live: `https://heydex.ai/catalogue/dex-lens/v2.json` returned 200, 83,995 bytes, SHA-256 `79f3c2271f315493fb1f13b11e809e7899562c8a9aebb71cb9ff78d1b7cd89c6`, and was byte-identical to Core release v1.95.2 | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Signed catalogue verifies locally | Passed live: Lens verified Core release v1.95.2 and the heydex.ai-served copy with `default_keyring()` | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Pinned public key matches Core signing secret | Passed live: the real Core-signed catalogue verifies against Lens's pinned `dex-core-lens-1` public key | Keep the tamper-refusal row attached so a mismatch would be a loud failure, not gate-on |
| Exact release identity matches | Passed live: release, key, exact byte hash, catalogue version, 25-capability ordered ID set, and 9-job count all matched the release manifest | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Tampered or mismatched catalogue fails closed | Passed live for signature tampering in `scripts/section6_live_bridge_proof.py`; exact-release mismatch is behaviorally tested and writes a structured failed receipt | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Broken Core catalogue refuses release publication | Passed in Core PR #473: deliberately broken catalogue cases fail validation before signing and leave zero publishable artifacts | Core PR #473 merged on green CI |
| Local adversarial catalogue cases fail safely | Passed locally for tampered, replayed older, malformed/unsigned-equivalent, hostile inert content, unmet host prerequisites demoted/explained, and offline stale cache | Local proof merged in PR #15; fresh live tamper refusal attached in PR #21 |
| Minimal first-time host gets a shelf and brief | Passed live in the canonical `scripts/section6_live_bridge_proof.py` journey | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Customised Claude host gets a shelf and brief | Passed live in the canonical `scripts/section6_live_bridge_proof.py` journey | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Guided/export-assisted host gets a shelf and brief | Passed live in the canonical `scripts/section6_live_bridge_proof.py` journey | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Three briefs are host-appropriate | Passed live: minimal, customised, and guided/export briefs contain host-specific context and are non-identical | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Subscription loop across runs | Passed live in `scripts/section6_live_bridge_proof.py`: subscribe, returning one-fetch prompt, park suppression, revoke, and unsubscribed zero-fetch posture | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Public copy remains honest | Passed by inspection: public copy says the bridge is available for all 25 approved everyday capabilities in Wave 2 and identifies role packs/optional capabilities as next | Reconciled in PR #21 with the exact live proof |
| Signing key exists | Passed by source inspection: `dex-core-lens-1` is pinned in Lens main after Dave returned the public key, and GitHub reports the expected Core secret name exists without exposing the secret value | Key-correspondence still requires the real signed-catalogue proof row above |
| Wave 2 capability set exists | Passed live: the real catalogue carries the complete ordered set of 25 approved everyday capabilities and Lens renders all 25 for both deep host fixtures | Attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Live catalogue deploy | Passed live: heydex.ai serves the signed catalogue from the canonical URL | Byte-identity proof attached in PR #21 live-proof run 31618570194, artifact 9150282037 |
| Public live claim approved and shipped | Passed after Dave approved the public availability claim; README and status copy now match the live 25-capability Wave 2 catalogue | Wave 2 catalogue is live; exact Lens acceptance attached to PR #21 |

## Remaining Programme Work

- Wave 3 is next: adoptable role-pack and optional capabilities must keep the same
  evidence bar, with runtime-path-only entries labelled at the lower support level.

## Evidence Notes

- `subscribed_prompt_rendered: false` in artifact 9150282037 is correct. The current
  public catalogue is version 1, so a returning subscriber has no newer version to look
  at or park yet; the look-or-park prompt path is proven in the local suite with
  synthetic version bumps.
