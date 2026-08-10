# Withdrawal and deletion runbook

**Trigger:** a participant asks to withdraw or delete pilot evidence.

**Owner:** pilot data owner.

**Actions:** stop collection; mark consent withdrawn; delete receipts, caches,
and browser storage through the registered deletion paths; verify byte-level
absence; record the withdrawal without retaining private content.

**Evidence:** withdrawal record, deletion manifest, and byte-absence check.

**Exit criteria:** every controlled copy is absent and the participant receives
confirmation.  A failed deletion is an incident, not a warning.

**Tabletop:** the deterministic M6 drill writes a synthetic canary receipt,
deletes it, and verifies that the path no longer exists.
