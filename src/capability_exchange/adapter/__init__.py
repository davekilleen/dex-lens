"""Module M-A contract layer: Host Adapter contract, result envelope, surface.

HANDOFF 2.3 M-A. Three pieces, all on the diagnosis side and therefore all
read-only by construction (non-negotiable boundary 1):

- :mod:`.contract` — the versioned Host Adapter contract. Diagnose-only by
  default; Adapt-capable is unrepresentable in M1 because the mutation
  contract it requires is forward-declared and unconstructable until M4.
- :mod:`.envelope` — the deterministic adapter result envelope, separate
  from any renderer, with the healthy / intentionally-off / broken /
  could-not-check instrument grammar (instrument health, not Evidence
  Level) and R2 evidence items.
- :mod:`.surface` — the model/UI-facing surface: read, preview, and
  bounded-status operations only.

The call at the bottom of this module is load-bearing: importing the
package structurally verifies that no public callable it defines names a
mutating operation. A future module that adds one breaks the import, not
just a test.
"""

from capability_exchange.adapter.contract import (
    AdaptCapableUnrepresentableError,
    AdapterContract,
    AdapterMode,
    ArchivePolicy,
    MutationContractRef,
    MutationContractUnavailableError,
    SymlinkPolicy,
    VersionDetectionMethod,
)
from capability_exchange.adapter.envelope import (
    DETAIL_MAX_LENGTH,
    FAILED_INSTRUMENT_HEALTHS,
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.adapter.surface import (
    MUTATING_NAME_TOKENS,
    PREVIEW_LIMIT_DEFAULT,
    PREVIEW_LIMIT_MAX,
    DiagnosisSurface,
    PreviewBoundError,
    ProbeNotFoundError,
    ReadOnlySurfaceViolation,
    assert_read_only_surface,
)

__all__ = [
    "DETAIL_MAX_LENGTH",
    "FAILED_INSTRUMENT_HEALTHS",
    "MUTATING_NAME_TOKENS",
    "PREVIEW_LIMIT_DEFAULT",
    "PREVIEW_LIMIT_MAX",
    "AdaptCapableUnrepresentableError",
    "AdapterContract",
    "AdapterMode",
    "AdapterResultEnvelope",
    "ArchivePolicy",
    "DiagnosisSurface",
    "InstrumentHealth",
    "MutationContractRef",
    "MutationContractUnavailableError",
    "PreviewBoundError",
    "ProbeNotFoundError",
    "ProbeResult",
    "ReadOnlySurfaceViolation",
    "SymlinkPolicy",
    "VersionDetectionMethod",
    "assert_read_only_surface",
]

# Non-negotiable boundary 1, enforced at import: the diagnosis surface
# exposes no mutating entry point. See surface.assert_read_only_surface.
assert_read_only_surface()
