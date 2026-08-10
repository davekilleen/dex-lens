# Dex Lens risk register

Last updated: 2026-08-10

This is the lightweight register for risks that must stay visible until the
full R7 handoff pack exists. Every unresolved entry needs a named owner before
pilot sign-off.

| ID | Risk | Evidence | Impact | Current mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| RISK-MAC-SOCKET-CREATION | macOS Seatbelt blocks outbound connection, not socket creation, on GitHub macos-14 runners. | CI runs 31244515811, 31244792823, and 31244920768 showed AF_INET, AF_INET6, and AF_UNIX sockets were created under the shipped profile despite `(deny system-socket)`, while the runtime proof returned `connect-denied`, `write-open-denied`, and `exec-denied`. | The macOS containment story is asymmetric with Linux: no egress is enforced, but "no socket fd can exist" is not proven on the pilot platform. | `MacOSStrategy.availability()` now requires a fresh runtime tuple including `socket-denied`; otherwise the deep adapter is disabled before reads and the guided/export-assisted path is used. Keep `(deny system-socket)` plus `(deny network*)` and retain the direct egress probe. | Dave, pending D7 owner decision | Open |
