# Incident runbook

**Trigger:** severe privacy, consent, ownership, recovery, or control failure;
an `Unverified` outcome; or a `Recovery failed` event from adaptation or undo.

**Owner:** pilot incident owner.

**Actions:** stop the affected path immediately; contain the system; record the
event and the bounded evidence; preserve a safe receipt (or record that no
receipt could be proven); escalate for independent review. Never retry an
`Unverified` or `Recovery failed` operation automatically.

**Evidence:** incident record, stop receipt, containment check, runbook trigger
(`Unverified` or `Recovery failed` where applicable), and review decision. The
record contains references and states, never raw private data.

**Exit criteria:** the affected path remains stopped until review explicitly
clears it, the hard-stop state is preserved for the session, and the event is
recorded against the participant and contract.

**Tabletop:** the deterministic M6 drill injects a synthetic `Recovery failed`
event and records a passing stop-and-review result.
