# Key rotation runbook

**Trigger:** suspected credential exposure or an explicit key-rotation request.

**Owner:** host security owner.

**Actions:** stop the affected adapter; rotate through host-controlled tools;
invalidate the old key; preserve a metadata-only rotation receipt.

**Evidence:** adapter-disable record, old-key invalidation, and rotation receipt.

**Exit criteria:** the old key is rejected, no pilot data leaves the host, and
the adapter remains disabled until the review clears it.

**Tabletop:** the deterministic M6 drill uses synthetic credentials only.
