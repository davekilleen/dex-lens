# Dex Lens Live Capability Bridge Evidence Pack

Status: SECTION-6 PROOF PASSED, PUBLIC COPY HELD. Local Lens-side proof rows are
marked passed only where automated tests prove them. Live rows are marked passed
only where the real `https://heydex.ai/catalogue/dex-lens/v2.json` catalogue was
fetched and verified.

Plain-English summary: the real signed Dex catalogue is now served from the
approved heydex.ai URL and Lens verifies it against Dave's pinned public key. The
section-6 proof has passed; the remaining hold before any public "live" claim is
Dave's explicit approval to change public copy.

## What This Evidence Pack Is For

The section-6 proof demonstrates that Dex Lens can privately examine a person's AI
system, show a ranked shelf of relevant Dex capabilities, and produce a safe
portable brief without widening the adaptation boundary.

This document must not be used as a live-claim artifact until every row below has a
passing run attached.

## Current Proof State

| Criterion | Current state | Required final evidence |
|---|---|---|
| Fresh install makes no catalogue request | Passed live in `scripts/section6_live_bridge_proof.py`: after unsubscribe, a returning run made zero catalogue fetches | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Explicit consent performs one catalogue request | Passed live in `scripts/section6_live_bridge_proof.py`: the subscribed returning run made exactly one catalogue fetch | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Real catalogue URL is reachable | Passed live: `https://heydex.ai/catalogue/dex-lens/v2.json` returned 200, 17,714 bytes, and was byte-identical to the Core release asset | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Signed catalogue verifies locally | Passed live: Lens verified the Core release catalogue and the heydex.ai-served copy with `default_keyring()` | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Pinned public key matches Core signing secret | Passed live: the real Core-signed catalogue verifies against Lens's pinned `dex-core-lens-1` public key | Keep the tamper-refusal row attached so a mismatch would be a loud failure, not gate-on |
| Tampered catalogue fails closed | Passed live in `scripts/section6_live_bridge_proof.py`; passed locally in `tests/e2e/test_bridge_golden_path.py::test_section6_local_adversarial_catalogue_cases_fail_safely` | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Broken Core catalogue refuses release publication | Passed in Core PR #473: deliberately broken catalogue cases fail validation before signing and leave zero publishable artifacts | Core PR #473 merged on green CI |
| Local adversarial catalogue cases fail safely | Passed locally for tampered, replayed older, malformed/unsigned-equivalent, hostile inert content, unmet host prerequisites demoted/explained, and offline stale cache | Local proof merged in PR #15; live tamper refusal attached in PR #18 |
| Minimal first-time host gets a shelf and brief | Passed live in `tests/e2e/test_bridge_golden_path.py::test_section6_live_golden_path_uses_real_heydex_catalogue` and `scripts/section6_live_bridge_proof.py` | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Customised Claude host gets a shelf and brief | Passed live in `tests/e2e/test_bridge_golden_path.py::test_section6_live_golden_path_uses_real_heydex_catalogue` and `scripts/section6_live_bridge_proof.py` | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Guided/export-assisted host gets a shelf and brief | Passed live in `tests/e2e/test_bridge_golden_path.py::test_section6_live_golden_path_uses_real_heydex_catalogue` and `scripts/section6_live_bridge_proof.py` | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Three briefs are host-appropriate | Passed live: minimal, customised, and guided/export briefs contain host-specific context and are non-identical | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Subscription loop across runs | Passed live in `scripts/section6_live_bridge_proof.py`: subscribe, returning one-fetch prompt, park suppression, revoke, and unsubscribed zero-fetch posture | Attached in PR #18 live-proof run 31589662751, artifact 9138582059 |
| Public copy remains honest | Passing by inspection today | README/About/status still say designed or not connected until proof passes |
| Signing key exists | Passed by source inspection: `dex-core-lens-1` is pinned in Lens main after Dave returned the public key, and GitHub reports the expected Core secret name exists without exposing the secret value | Key-correspondence still requires the real signed-catalogue proof row above |
| Initial capability tranche exists | Passed live: the real catalogue carries Dave's approved six entries — Daily Plan, Week Plan, Process Meetings, Dex Doctor, Relationship Radar, Save Insight | Attached in PR #18 live-proof run |
| Live catalogue deploy | Passed live: heydex.ai serves the signed catalogue from the canonical URL | Attach byte-identity proof against the Core release asset |
| Public live claim remains held | Passing by inspection today: no README/About/status copy says the bridge is available | Design-owner sign-off, then Dave's final approval before public copy changes |

## Remaining Hold

- Public copy: held until Dave explicitly approves changing README/About/status copy to
  say the bridge is available. The proof passing does not approve that announcement.

## Evidence Notes

- `subscribed_prompt_rendered: false` in artifact 9138582059 is correct for this
  first live catalogue run. Only one catalogue version exists, so a returning subscriber
  has no newer version to look at or park yet; the look-or-park prompt path is proven in
  the local suite with synthetic version bumps.
