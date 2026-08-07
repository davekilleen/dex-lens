"""The Claude Code deep adapter: a contained evidence collector (M-A, G1).

The first deep adapter — local, folder-based Claude Code (#350; macOS
target, Linux-testable). It is an evidence collector, not an agent:

- :mod:`.allowlist` — canonicalized real-path allowlist; every path
  resolved before any read; symlink/hardlink escapes, mount crossings, and
  denied paths refused with honest R2 exclusion records.
- :mod:`.snapshot` — immutable inspection snapshot taken at consent time;
  all reads come from the snapshot, never live disk; mid-inspection change
  detected by digest; ambiguity aborts and discards partials.
- :mod:`.secrets` — secret-shaped content redacted at collection; raw
  secret bytes never stored anywhere.
- :mod:`.collector` — bounded, deterministic evidence collection into the
  shared result envelope; inspected content is untrusted data and never
  interpreted as instructions.
- :mod:`.containment` — OS-level enforcement (Linux seccomp / macOS
  sandbox-exec) with runtime proof before any read; fail closed to the
  honest guided/export-assisted fallback.
- :mod:`.version_detection` — installation shape from file markers only;
  honest Unknown when unprovable.
- :mod:`.contract` — the shipped, versioned Host Adapter contract
  declaration (Diagnose-only, structurally).

The scan at the bottom is load-bearing (non-negotiable boundary 1):
importing this package verifies that no public callable it defines names a
mutating operation — the diagnosis side never holds a write capability.
"""

from capability_exchange.adapter.surface import assert_read_only_surface
from capability_exchange.adapters.claude_code import (
    allowlist,
    collector,
    contained,
    containment,
    contract,
    secrets,
    snapshot,
    version_detection,
)
from capability_exchange.adapters.claude_code.allowlist import (
    IGNORED_DIRECTORY_NAMES,
    AllowlistError,
    CanonicalAllowlist,
    PathDecision,
    PathVerdict,
    SurveyOutcome,
)
from capability_exchange.adapters.claude_code.collector import EvidenceCollector
from capability_exchange.adapters.claude_code.containment import (
    GUIDED_FALLBACK_MESSAGE,
    CollectionFailedError,
    CollectionRequest,
    ContainedCollection,
    ContainmentOutcome,
    ContainmentStrategy,
    ContainmentUnavailableError,
    LinuxStrategy,
    MacOSStrategy,
    TestStrategy,
    contained_inspection,
    default_strategy,
)
from capability_exchange.adapters.claude_code.contract import (
    CLAUDE_CODE_ADAPTER_ID,
    CLAUDE_CODE_CONTRACT_VERSION,
    CLAUDE_CODE_EVIDENCE_PROBES,
    GLOBALLY_DENIED_PATHS,
    claude_code_contract,
)
from capability_exchange.adapters.claude_code.secrets import (
    REDACTION_MARK,
    RedactionOutcome,
    contains_secret_shape,
    redact_secret_content,
)
from capability_exchange.adapters.claude_code.snapshot import (
    CollectionBounds,
    InspectionAbortedError,
    InspectionSnapshot,
    SnapshotEntry,
    SnapshotError,
    SnapshotMissError,
    take_snapshot,
)
from capability_exchange.adapters.claude_code.version_detection import (
    InstallationMarker,
    InstallationShape,
    detect_installation,
)

__all__ = [
    "CLAUDE_CODE_ADAPTER_ID",
    "CLAUDE_CODE_CONTRACT_VERSION",
    "CLAUDE_CODE_EVIDENCE_PROBES",
    "GLOBALLY_DENIED_PATHS",
    "GUIDED_FALLBACK_MESSAGE",
    "IGNORED_DIRECTORY_NAMES",
    "REDACTION_MARK",
    "AllowlistError",
    "CanonicalAllowlist",
    "CollectionBounds",
    "CollectionFailedError",
    "CollectionRequest",
    "ContainedCollection",
    "ContainmentOutcome",
    "ContainmentStrategy",
    "ContainmentUnavailableError",
    "EvidenceCollector",
    "InspectionAbortedError",
    "InspectionSnapshot",
    "InstallationMarker",
    "InstallationShape",
    "LinuxStrategy",
    "MacOSStrategy",
    "PathDecision",
    "PathVerdict",
    "RedactionOutcome",
    "SnapshotEntry",
    "SnapshotError",
    "SnapshotMissError",
    "SurveyOutcome",
    "TestStrategy",
    "claude_code_contract",
    "contained_inspection",
    "contains_secret_shape",
    "default_strategy",
    "detect_installation",
    "redact_secret_content",
    "take_snapshot",
    "version_detection",
]

# Load-bearing: no mutating entry point may exist on the diagnosis surface.
assert_read_only_surface(
    modules=(
        allowlist,
        collector,
        contained,
        containment,
        contract,
        secrets,
        snapshot,
        version_detection,
    )
)
