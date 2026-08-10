# Hard-stop runbook

**Trigger:** verification is `Unknown`/`Unverified`, an undo or receipt path
reports `Recovery failed`, or a transaction journal/recovery manifest cannot be
validated.

**Owner:** adaptation safety owner.

**Actions:** disable further automation in the session; preserve the local
receipt and journal references; do not retry silently; render the honest reason
to the person; escalate to the incident runbook. A missing receipt is itself a
failure, not a success.

**Evidence:** hard-stop state, `Unverified`/`Recovery failed` trigger,
recovery-verification reference, incident record, and escalation record.

**Exit criteria:** no automated continuation occurs until a recorded review
explicitly clears the path.

**Tabletop:** the deterministic M6 drill uses a synthetic `Recovery failed`
adverse event and records the stop.
