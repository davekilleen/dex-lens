"""Diagnosis engine and Capability Map (module M-D; #351, #352).

Read-only diagnosis of the eight Foundation Capabilities against the
person's confirmed Success Contracts and the approved evidence scope:

- :mod:`capability_exchange.diagnosis.foundations` — the eight Foundation
  Capabilities encoded as data (user job, observable evidence, safety
  boundary, negative rules).
- :mod:`capability_exchange.diagnosis.finding` — three-axis findings
  (Capability State / Evidence Level / Safety Boundary); an aggregate is
  structurally unrepresentable.
- :mod:`capability_exchange.diagnosis.engine` — the deterministic
  :func:`~capability_exchange.diagnosis.engine.assess` entry point.
- :mod:`capability_exchange.diagnosis.orchestrator` — the durable
  :class:`~capability_exchange.diagnosis.orchestrator.DeterministicDiagnosisEngine`.

The jobs-first Capability Map that nests these findings per confirmed job,
its plain-text renderer, and the person's correction routes live in
:mod:`capability_exchange.capmap` (module M-D renderer side).

Everything here sits on the diagnosis side (non-negotiable boundary 1):
no module in this package holds a write capability or a mutating entry
point, and nothing here persists or transmits anything.
"""

from capability_exchange.diagnosis.engine import DiagnosisInputError, assess
from capability_exchange.diagnosis.finding import (
    CapabilityState,
    Finding,
    SafetyBoundary,
)
from capability_exchange.diagnosis.foundations import (
    FOUNDATION_DEFINITIONS,
    FoundationCapability,
    FoundationDefinition,
    NegativeRule,
    definition_for,
    negative_rule_ids,
)

__all__ = [
    "FOUNDATION_DEFINITIONS",
    "CapabilityState",
    "DeterministicDiagnosisEngine",
    "DiagnosisInputError",
    "Finding",
    "FoundationCapability",
    "FoundationDefinition",
    "NegativeRule",
    "SafetyBoundary",
    "assess",
    "definition_for",
    "negative_rule_ids",
]


def __getattr__(name: str) -> object:
    """Export the orchestrator without importing it at package import time."""

    if name == "DeterministicDiagnosisEngine":
        from capability_exchange.diagnosis.orchestrator import DeterministicDiagnosisEngine

        return DeterministicDiagnosisEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
