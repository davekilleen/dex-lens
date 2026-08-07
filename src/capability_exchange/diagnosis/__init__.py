"""Diagnosis engine and Capability Map (module M-D; #351, #352).

Read-only diagnosis of the eight Foundation Capabilities against the
person's confirmed Success Contracts and the approved evidence scope:

- :mod:`capability_exchange.diagnosis.foundations` — the eight Foundation
  Capabilities encoded as data (user job, observable evidence, safety
  boundary, negative rules).
- :mod:`capability_exchange.diagnosis.finding` — three-axis findings
  (Capability State / Evidence Level / Safety Boundary) and the jobs-first
  Capability Map shapes; an aggregate is structurally unrepresentable.
- :mod:`capability_exchange.diagnosis.engine` — the deterministic
  :func:`~capability_exchange.diagnosis.engine.assess` entry point.

Everything here sits on the diagnosis side (non-negotiable boundary 1):
no module in this package holds a write capability or a mutating entry
point, and nothing here persists or transmits anything.
"""

from capability_exchange.diagnosis.engine import DiagnosisInputError, assess
from capability_exchange.diagnosis.finding import (
    CapabilityMap,
    CapabilityState,
    Finding,
    JobFindings,
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
    "CapabilityMap",
    "CapabilityState",
    "DiagnosisInputError",
    "Finding",
    "FoundationCapability",
    "FoundationDefinition",
    "JobFindings",
    "NegativeRule",
    "SafetyBoundary",
    "assess",
    "definition_for",
    "negative_rule_ids",
]
