"""The runnable Host Adapter conformance suite (HANDOFF 5.4).

A Host Adapter ships only after passing this suite. It is runnable — not
prose — against **any** adapter via its declared contract and a small
driving surface (:class:`AdapterConformanceSubject`), and it is itself an
R7 handoff artifact. The M1 checks:

- **contract-declaration completeness** — roots, scope, denied paths,
  symlink/archive policy, probes, version detection, Diagnose-only vs
  Adapt-capable, all declared and coherent (G1);
- **zero-writes proof** — a full recursive identity capture (content
  digest, size, mode, mtime, directory entries, symlink targets) of the
  inspected tree before and after an entire inspection (G1);
- **snapshot semantics** — reads served from the consent-time capture,
  never live disk; un-captured paths refused (G1 item c);
- **result-envelope conformance** — R2 states, source age, non-raw
  references, instrument failure reported and never counted as success;
- **honest fallback** — containment unavailable ⇒ typed refusal with
  fallback guidance and zero reads/writes (G1 fail-closed).

The T1–T9 capability matrix for Adapt-capable adapters lands in M4; in M1
Adapt-capable is structurally unrepresentable, which the contract check
enforces.

Everything here is a test instrument on the diagnosis side: it never
mutates the inspected system (the zero-writes check proves the adapter did
not either); its own scratch trees live in a workspace the caller owns.
"""

from capability_exchange.conformance.checks import (
    CheckOutcome,
    CheckResult,
    check_contract_declaration_completeness,
    check_honest_fallback,
    check_result_envelope_conformance,
    check_snapshot_semantics,
)
from capability_exchange.conformance.registry import (
    UnknownAdapterError,
    conformance_subject_for,
    registered_adapter_ids,
)
from capability_exchange.conformance.runner import (
    ConformanceReport,
    format_report,
    run_conformance_suite,
)
from capability_exchange.conformance.subject import (
    AdapterConformanceSubject,
    SnapshotLike,
)

__all__ = [
    "AdapterConformanceSubject",
    "CheckOutcome",
    "CheckResult",
    "ConformanceReport",
    "SnapshotLike",
    "UnknownAdapterError",
    "check_contract_declaration_completeness",
    "check_honest_fallback",
    "check_result_envelope_conformance",
    "check_snapshot_semantics",
    "conformance_subject_for",
    "format_report",
    "registered_adapter_ids",
    "run_conformance_suite",
]
