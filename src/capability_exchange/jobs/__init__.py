"""Job Map / Success Contract engine (module M-C; #352, gates.md R1).

The propose-confirm flow, read-only end to end:

- :mod:`capability_exchange.jobs.propose` — deterministic, rule-based
  candidate-job proposal from an adapter result envelope; every proposal
  honestly marked ``inferred``. Detection proposes; it never enrolls.
- :mod:`capability_exchange.jobs.inspection` — the provisional R1
  ``Inspection`` state: local-only, editable, discardable, type-level
  excluded from every sharing, Card, export, and telemetry payload.
- :mod:`capability_exchange.jobs.contract` — the Success Contract schema.
  Confirmed contracts are the only input diagnosis may consume.

Everything in this package sits on the diagnosis side (non-negotiable
boundary 1): its only writes are the product's own local ``Inspection``-job
records, which are inventoried (G2) and verifiably deletable.
"""

from capability_exchange.jobs.contract import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)
from capability_exchange.jobs.inspection import (
    ConfirmedJobExport,
    CorruptJobRecordError,
    InspectionExclusionError,
    InspectionJob,
    InspectionJobStore,
    JobStoreError,
    resolve_export_request,
)
from capability_exchange.jobs.propose import (
    CandidateJobProposal,
    propose_candidate_jobs,
    to_inspection_job,
)

__all__ = [
    "CandidateJobProposal",
    "ConfirmedJobExport",
    "CorruptJobRecordError",
    "InspectionExclusionError",
    "InspectionJob",
    "InspectionJobStore",
    "JobBoundaries",
    "JobCadence",
    "JobImportance",
    "JobStoreError",
    "SuccessContract",
    "propose_candidate_jobs",
    "resolve_export_request",
    "to_inspection_job",
]
