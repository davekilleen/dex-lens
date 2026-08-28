"""Dex Capability Exchange (working name "Outward Dex").

A standalone, local-first product that privately diagnoses a person's
existing personal AI system at the user-job level — read-only, with
nothing shared by default and no migration to Dex ever required.

The diagnosis side never holds a write capability. Every module added to
this package on the diagnosis path must preserve that invariant at the
OS-capability level (G1), not merely by convention.
"""

__version__ = "0.1.14"

# Standing posture of the diagnosis side (non-negotiable boundary 1):
# diagnosis is read-only at the operating-system capability level.
# No module on the diagnosis path may expose a mutating entry point.
DIAGNOSIS_READ_ONLY = True

__all__ = ["DIAGNOSIS_READ_ONLY", "__version__"]
