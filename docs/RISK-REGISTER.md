# Dex Lens risk register

Last updated: 2026-08-08

This is the lightweight register for risks that must stay visible until the
full R7 handoff pack exists. Every unresolved entry needs a named owner before
pilot sign-off.

| ID | Risk | Evidence | Impact | Current mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| RISK-MAC-SOCKET-CREATION | macOS Seatbelt blocks outbound connection, not socket creation, on GitHub macos-14 runners. | CI runs 31244515811, 31244792823, and 31244920768 showed AF_INET, AF_INET6, and AF_UNIX sockets were created under the shipped profile despite `(deny system-socket)`, while the runtime proof returned `connect-denied`, `write-open-denied`, and `exec-denied`. | The macOS containment story is asymmetric with Linux: no egress is enforced, but "no socket fd can exist" is not proven on the pilot platform. | Keep `(deny system-socket)` plus `(deny network*)`; run a macOS egress probe that fails if connect succeeds or reaches the network; state the asymmetry in architecture/status docs. If Dave rejects this residual risk, Mac deep inspection must fall back to guided/export-assisted mode until a stronger Seatbelt rule is proven. | Dave, pending D7 owner decision | Open |
