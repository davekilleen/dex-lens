# Dex Lens Live Capability Bridge Evidence Pack

Status: PREPARED, NOT PASSED

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
| Fresh install makes no catalogue request | Prepared in automated tests | Packet-level egress proof from the formal runner |
| Explicit consent performs one catalogue request | Prepared in automated tests | subscribed-posture packet-level egress proof |
| Real catalogue URL is reachable | Not passed | real heydex.ai catalogue URL fetch from `https://heydex.ai/catalogue/dex-lens/v2.json` |
| Signed catalogue verifies locally | Prepared with local signed fixture | Real Core-signed catalogue verified by Lens |
| Tampered catalogue fails closed | Prepared with local signed fixture | Formal adversarial run recorded here |
| Minimal first-time host gets a shelf and brief | Prepared with local host fixture | Passing e2e run recorded here |
| Customised Claude host gets a shelf and brief | Prepared with local host fixture | Passing e2e run recorded here |
| Guided/export-assisted host gets a shelf and brief | Prepared with local host fixture | Passing e2e run recorded here |
| Public copy remains honest | Passing by inspection today | README/About/status still say designed or not connected until proof passes |
| Release gate remains held | Passing by inspection today | Dave signing-key ceremony and initial tranche decision completed before gate-on |

## Gates Not Yet Cleared

- Dave signing-key ceremony: not started here; private key material must never be
  pasted into chat.
- Initial capability tranche: not selected by Dave yet.
- Live catalogue deploy: not authorized here.
- Section-6 final run: not passed until the real signed catalogue is fetched from
  heydex.ai and the subscribed-posture packet-level egress proof is attached.
