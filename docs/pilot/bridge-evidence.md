# Dex Lens Live Capability Bridge Evidence Pack

Status: PREPARED, NOT PASSED for the live bridge. Local Lens-side proof rows
below are marked passed only where automated tests now prove them without the
real heydex.ai catalogue URL.

Plain-English summary: the local evidence harness is ready to prove the bridge
workflow, but the bridge is not live yet. The final proof still needs a real signed
Dex Core catalogue served from the canonical heydex.ai URL, plus the subscribed
packet-level egress run.

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
| Real catalogue URL is reachable | NOT PASSED | real heydex.ai catalogue URL fetch from `https://heydex.ai/catalogue/dex-lens/v2.json` |
| Signed catalogue verifies locally | Passed locally with signed deterministic fixtures in `tests/e2e/test_bridge_golden_path.py` | Real Core-signed catalogue verified by Lens |
| Tampered catalogue fails closed | Passed locally in `tests/e2e/test_bridge_golden_path.py::test_section6_local_adversarial_catalogue_cases_fail_safely` | Formal adversarial run recorded here against the real Core-signed catalogue |
| Broken Core catalogue refuses release publication | NOT PASSED | Core release-pipeline failure proof for a deliberately broken catalogue entry |
| Local adversarial catalogue cases fail safely | Passed locally for tampered, replayed older, malformed/unsigned-equivalent, hostile inert content, unmet host prerequisites demoted/explained, and offline stale cache | Live sabotage run still needs the real Core-signed catalogue and formal runner |
| Minimal first-time host gets a shelf and brief | Passed locally in `tests/e2e/test_bridge_golden_path.py::test_section6_local_golden_path_scaffold_covers_three_host_fixtures` | Repeat with real heydex.ai catalogue before live claim |
| Customised Claude host gets a shelf and brief | Passed locally in `tests/e2e/test_bridge_golden_path.py::test_section6_local_golden_path_scaffold_covers_three_host_fixtures` | Repeat with real heydex.ai catalogue before live claim |
| Guided/export-assisted host gets a shelf and brief | Passed locally in `tests/e2e/test_bridge_golden_path.py::test_section6_local_golden_path_scaffold_covers_three_host_fixtures` | Repeat with real heydex.ai catalogue before live claim |
| Three briefs are host-appropriate | Passed locally: minimal, customised, and guided/export briefs contain host-specific context and are non-identical | Evidence from the real signed catalogue run |
| Subscription loop across runs | Passed locally: subscribe, detect new version on next run, park suppresses the same shift, unsubscribe deletes consent and next run makes zero fetches | subscribed-posture packet-level egress proof |
| Public copy remains honest | Passing by inspection today | README/About/status still say designed or not connected until proof passes |
| Signing key exists | NOT PASSED | Dave signing-key ceremony completed and public key pinned |
| Initial capability tranche exists | NOT PASSED | Dave-approved initial tranche present in the real Core catalogue |
| Live catalogue deploy | NOT PASSED | heydex.ai serves the signed catalogue from the canonical URL |
| Release gate remains held | Passed by inspection today: no deploy, no release gate flip, no live claim in this worker | Dave signing-key ceremony, initial tranche, live proof, and release-gate approval completed before gate-on |

## Gates Not Yet Cleared

- Dave signing-key ceremony: not started here; private key material must never be
  pasted into chat.
- Initial capability tranche: not selected by Dave yet.
- Live catalogue deploy: not authorized here.
- Section-6 final run: not passed until the real signed catalogue is fetched from
  heydex.ai and the subscribed-posture packet-level egress proof is attached.
