# Withdrawal and deletion runbook

**Trigger:** a participant asks to withdraw or delete pilot evidence.

**Owner:** pilot data owner.

**Actions:** stop collection; mark consent withdrawn; delete receipts, caches,
and browser storage through the registered deletion paths; verify byte-level
absence; record the withdrawal without retaining private content.

**Evidence:** withdrawal record, deletion manifest, and byte-absence check.

**Exit criteria:** every controlled copy is absent and the participant receives
confirmation.  A failed deletion is an incident, not a warning.

For the optional hosted Capability Exchange path, the authenticated withdrawal
must echo the exact receipt id (when already known), manifest hash, and one-way
receipt binding. The local receipt authority lives only in
`hosted-contribution-receipts.json`, outside every inspected root, with mode
`0600`. It is created in a `submitting` state before egress so an interruption
cannot erase the authority needed to revoke a remotely accepted submission.
After an exact affirmative hosted withdrawal, the matching local authority is
deleted and absence is verified. The raw revocation token is never transmitted
or stored in that file.

An explicit contribution-candidate decline is a separate local suppression
record, not contribution content. `contribution-candidate-declines.json` lives
in the same app-storage boundary and contains only opaque candidate SHA-256
values plus its schema version. It is intentionally durable so a fresh session
does not repeat a declined offer. A request to clear that preference uses the
registered `delete-contribution-candidate-declines` path and verifies absence;
no proposal prose, sensitive category, timestamp, file reference or inspected
value exists in the file.

**Tabletop:** the deterministic M6 drill writes a synthetic canary receipt,
deletes it, and verifies that the path no longer exists.
