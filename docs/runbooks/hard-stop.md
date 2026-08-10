# Hard-stop runbook

**Trigger:** verification is `Unknown`, `Unverified`, or `Recovery failed`.

**Owner:** adaptation safety owner.

**Actions:** disable further automation in the session; preserve the local
receipt; do not retry silently; escalate to the incident runbook.

**Evidence:** hard-stop state, recovery verification reference, and escalation
record.

**Exit criteria:** no automated continuation occurs until a recorded review
explicitly clears the path.

**Tabletop:** the deterministic M6 drill uses a synthetic `Recovery failed`
adverse event and records the stop.
