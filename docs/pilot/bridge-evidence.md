# Dex Lens Live Capability Bridge Evidence Pack

Status: LIVE URL PROVEN, PACKET PROOF PENDING. Local Lens-side proof rows are
marked passed only where automated tests prove them. Live rows are marked passed
only where the real `https://heydex.ai/catalogue/dex-lens/v2.json` catalogue was
fetched and verified.

Plain-English summary: the real signed Dex catalogue is now served from the
approved heydex.ai URL and Lens verifies it against Dave's pinned public key. The
remaining proof before any public "live" claim is the subscribed packet-level
egress run from the formal runner and design-owner sign-off on this evidence pack.

## What This Evidence Pack Is For

The section-6 proof demonstrates that Dex Lens can privately examine a person's AI
system, show a ranked shelf of relevant Dex capabilities, and produce a safe
portable brief without widening the adaptation boundary.

This document must not be used as a live-claim artifact until every row below has a
passing run attached.

## Current Proof State

| Criterion | Current state | Required final evidence |
|---|---|---|
| Fresh install makes no catalogue request | Passed locally in `tests/e2e/test_bridge_golden_path.py::test_section6_subscription_loop_parks_then_unsubscribes_to_zero_fetches` after unsubscribe returns the next run to zero fetches | Packet-level egress proof from the formal runner |
| Explicit consent performs one catalogue request | Passed locally in `tests/e2e/test_bridge_golden_path.py::test_section6_first_timer_sees_full_shelf_with_all_catalogue_aisles` with injected deterministic HTTP | subscribed-posture packet-level egress proof |
| Real catalogue URL is reachable | Passed live: `https://heydex.ai/catalogue/dex-lens/v2.json` returned 200, 17,714 bytes, and was byte-identical to the Core release asset | Attach the live-proof run artifact |
| Signed catalogue verifies locally | Passed live: Lens verified the Core release catalogue and the heydex.ai-served copy with `default_keyring()` | Attach the live-proof run artifact |
| Pinned public key matches Core signing secret | Passed live: the real Core-signed catalogue verifies against Lens's pinned `dex-core-lens-1` public key | Keep the tamper-refusal row attached so a mismatch would be a loud failure, not gate-on |
| Tampered catalogue fails closed | Passed locally in `tests/e2e/test_bridge_golden_path.py::test_section6_local_adversarial_catalogue_cases_fail_safely` | Formal adversarial run recorded here against the real Core-signed catalogue |
| Broken Core catalogue refuses release publication | NOT PASSED | Core release-pipeline failure proof for a deliberately broken catalogue entry |
| Local adversarial catalogue cases fail safely | Passed locally for tampered, replayed older, malformed/unsigned-equivalent, hostile inert content, unmet host prerequisites demoted/explained, and offline stale cache | Live sabotage run still needs the real Core-signed catalogue and formal runner |
| Minimal first-time host gets a shelf and brief | Passed live in `tests/e2e/test_bridge_golden_path.py::test_section6_live_golden_path_uses_real_heydex_catalogue` and `scripts/section6_live_bridge_proof.py` | Attach the live-proof run artifact |
| Customised Claude host gets a shelf and brief | Passed live in `tests/e2e/test_bridge_golden_path.py::test_section6_live_golden_path_uses_real_heydex_catalogue` and `scripts/section6_live_bridge_proof.py` | Attach the live-proof run artifact |
| Guided/export-assisted host gets a shelf and brief | Passed live in `tests/e2e/test_bridge_golden_path.py::test_section6_live_golden_path_uses_real_heydex_catalogue` and `scripts/section6_live_bridge_proof.py` | Attach the live-proof run artifact |
| Three briefs are host-appropriate | Passed live: minimal, customised, and guided/export briefs contain host-specific context and are non-identical | Attach the live-proof run artifact |
| Subscription loop across runs | Passed locally: subscribe, detect new version on next run, park suppresses the same shift, unsubscribe deletes consent and next run makes zero fetches | subscribed-posture packet-level egress proof |
| Public copy remains honest | Passing by inspection today | README/About/status still say designed or not connected until proof passes |
| Signing key exists | Passed by source inspection: `dex-core-lens-1` is pinned in Lens main after Dave returned the public key, and GitHub reports the expected Core secret name exists without exposing the secret value | Key-correspondence still requires the real signed-catalogue proof row above |
| Initial capability tranche exists | Passed live: the real catalogue carries Dave's approved six entries — Daily Plan, Week Plan, Process Meetings, Dex Doctor, Relationship Radar, Save Insight | Attach the live-proof run artifact |
| Live catalogue deploy | Passed live: heydex.ai serves the signed catalogue from the canonical URL | Attach byte-identity proof against the Core release asset |
| Public live claim remains held | Passing by inspection today: no README/About/status copy says the bridge is available | Design-owner sign-off, then Dave's final approval before public copy changes |

## Gates Not Yet Cleared

- Subscribed-posture packet-level egress: not passed until the formal runner attaches
  sanitized packet evidence for the subscribed one-GET posture and the unsubscribed
  zero-traffic posture.
- Design-owner sign-off: not passed until the completed evidence pack is reviewed.
