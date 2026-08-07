"""Jobs-first Capability Map: model, renderer, and correction routes (M-D).

The Capability Map half of module M-D (#351, #352), on the binding
collector/renderer split (Doctor pattern, HANDOFF 3.1):

- :mod:`capability_exchange.capmap.model` — the map itself: Foundation
  Capability findings nested inside each confirmed job, never a flat
  system-wide list; no aggregate of any kind is representable.
- :mod:`capability_exchange.capmap.render` — deterministic plain-text/
  markdown rendering that consumes Finding objects and never re-derives
  them; unknowns stay honest ("we couldn't check X because Y").
- :mod:`capability_exchange.capmap.correct` — the person's correction
  routes: evidence corrections become new user-reported R2 items (capped
  at Reported, never a silent upgrade), and job-definition corrections
  re-enter the R1 ``Inspection`` confirmation flow.

Everything here sits on the diagnosis side (non-negotiable boundary 1):
read-only, no mutating entry point, nothing persisted or transmitted.
"""

from capability_exchange.capmap.correct import (
    CorrectionError,
    ReopenedJob,
    correct_supporting_evidence,
    reopen_job_definition,
)
from capability_exchange.capmap.model import CapabilityMap, JobFindings
from capability_exchange.capmap.render import CAPABILITY_HEADINGS, render_capability_map

__all__ = [
    "CAPABILITY_HEADINGS",
    "CapabilityMap",
    "CorrectionError",
    "JobFindings",
    "ReopenedJob",
    "correct_supporting_evidence",
    "render_capability_map",
    "reopen_job_definition",
]
