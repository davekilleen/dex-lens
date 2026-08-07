"""Three-axis findings and the jobs-first Capability Map shapes (#351, #352).

Every finding carries EXACTLY three independent axes (#351 amendment,
authoritative):

- **Capability State** — Working / Partial / Not demonstrated / Unknown;
- **Evidence Level** — Verified / Supported / Reported / Unknown, derived
  through the total R2 mapping from the finding's linked evidence states
  (structurally enforced: a finding whose declared level disagrees with the
  mapping over its own evidence is unrepresentable);
- **Safety Boundary** — Safe / Overbroad / Unclear. ``Safe`` is scoped to
  the assessed job (every finding names its ``job_id``) and to the available
  evidence — never a blanket certification. A capability can be Working and
  Verified while still Overbroad.

**Never collapse the axes.** No aggregate, rank, or percentage field exists
in any schema here, every model is frozen with a closed field set
(``extra="forbid"``), and the schema test walks every field — including
nested models — to prove an aggregate is structurally unrepresentable, not
merely absent.

Alongside the axes, a finding links its R2 evidence items, keeps uncertainty
visible as notes, states one practical implication, and recommends exactly
one useful next move (a single bounded line: the field is singular by
construction).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import final

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.foundations import FoundationCapability
from capability_exchange.evidence import (
    CLAIM_SUPPORTING_STATES,
    EvidenceItem,
    EvidenceLevel,
    evidence_level,
)
from capability_exchange.jobs.contract import validate_contract_text, validate_job_id

__all__ = [
    "CapabilityMap",
    "CapabilityState",
    "Finding",
    "JobFindings",
    "SafetyBoundary",
]


class CapabilityState(StrEnum):
    """Closed axis vocabulary (#351): exactly these four states exist."""

    WORKING = "working"
    PARTIAL = "partial"
    NOT_DEMONSTRATED = "not-demonstrated"
    UNKNOWN = "unknown"


class SafetyBoundary(StrEnum):
    """Closed axis vocabulary (#351 amendment): exactly these three exist.

    ``safe`` is scoped to the assessed job and the available evidence; it is
    never a blanket certification of the whole system.
    """

    SAFE = "safe"
    OVERBROAD = "overbroad"
    UNCLEAR = "unclear"


@final
class Finding(InventoriedModel):
    """One Foundation Capability assessed against one confirmed job.

    Frozen, closed schema: the three axes plus linked evidence, uncertainty
    notes, one practical implication, and one recommended next move. There
    is no field for an aggregate, rank, or percentage, and ``extra="forbid"``
    means none can be attached.

    Structural honesty rules (validated, not advisory):

    - ``evidence_level`` must equal the total R2 mapping applied to the
      linked evidence items' states — the level is a derivation, never an
      assertion.
    - ``working`` and ``partial`` require at least one claim-supporting
      evidence item: a capability state above ``not-demonstrated`` with
      nothing supporting it is unrepresentable.
    - ``safe`` requires at least one claim-supporting evidence item: safety
      is scoped to available evidence, so an evidence-free ``safe`` is
      unrepresentable (fail closed to ``unclear`` upstream).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Which Foundation Capability this finding assesses (closed vocabulary).
    capability: FoundationCapability

    #: The confirmed job this finding is scoped to. ``safe`` never means
    #: more than "safe for this job, on this evidence".
    job_id: str

    #: Axis 1 — Capability State (closed vocabulary).
    capability_state: CapabilityState

    #: Axis 2 — Evidence Level, derived through the total R2 mapping.
    evidence_level: EvidenceLevel

    #: Axis 3 — Safety Boundary (closed vocabulary).
    safety_boundary: SafetyBoundary

    #: Linked R2 evidence items this finding rests on. May be empty only
    #: for an Unknown-level finding (nothing bore on the claim).
    evidence: tuple[EvidenceItem, ...] = ()

    #: Uncertainty stays visible: one bounded line per source of doubt.
    uncertainty_notes: tuple[str, ...] = ()

    #: Why this finding matters to the person's confirmed job.
    practical_implication: str

    #: Exactly one recommended next move (singular by construction).
    recommended_next_move: str

    @field_validator("job_id")
    @classmethod
    def _kebab_job_id(cls, value: str) -> str:
        return validate_job_id(value)

    @field_validator("uncertainty_notes")
    @classmethod
    def _bounded_notes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_contract_text(note, "uncertainty note") for note in value)

    @field_validator("practical_implication")
    @classmethod
    def _implication_text(cls, value: str) -> str:
        return validate_contract_text(value, "practical_implication")

    @field_validator("recommended_next_move")
    @classmethod
    def _next_move_text(cls, value: str) -> str:
        return validate_contract_text(value, "recommended_next_move")

    @model_validator(mode="after")
    def _axes_stay_honest(self) -> Finding:
        derived = evidence_level(item.state for item in self.evidence)
        if self.evidence_level is not derived:
            raise ValueError(
                f"evidence_level {self.evidence_level.value!r} does not equal the "
                f"total R2 mapping over the linked evidence ({derived.value!r}); "
                f"the Evidence Level is derived, never asserted"
            )
        has_support = any(item.state in CLAIM_SUPPORTING_STATES for item in self.evidence)
        if (
            self.capability_state in (CapabilityState.WORKING, CapabilityState.PARTIAL)
            and not has_support
        ):
            raise ValueError(
                f"capability_state {self.capability_state.value!r} requires at least "
                f"one claim-supporting evidence item; presence of nothing "
                f"demonstrates nothing"
            )
        if self.safety_boundary is SafetyBoundary.SAFE and not has_support:
            raise ValueError(
                "safety_boundary 'safe' requires claim-supporting evidence; safe is "
                "scoped to the assessed job and available evidence, never a blanket "
                "certification (fail closed to 'unclear')"
            )
        return self


@final
class JobFindings(InventoriedModel):
    """One confirmed job's findings: all eight Foundation Capabilities.

    The jobs-first Capability Map nests findings inside the job they are
    scoped to (#352). Exactly one finding per Foundation Capability, each
    naming this job — no capability silently missing, none doubled.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The confirmed job these findings are scoped to.
    job_id: str

    #: Exactly one finding per Foundation Capability (validated).
    findings: tuple[Finding, ...] = Field(min_length=1)

    @field_validator("job_id")
    @classmethod
    def _kebab_job_id(cls, value: str) -> str:
        return validate_job_id(value)

    @model_validator(mode="after")
    def _one_finding_per_capability_for_this_job(self) -> JobFindings:
        capabilities = [finding.capability for finding in self.findings]
        if set(capabilities) != set(FoundationCapability) or len(capabilities) != len(
            set(capabilities)
        ):
            raise ValueError(
                "a job's findings must cover exactly the eight Foundation "
                "Capabilities, one finding each"
            )
        for finding in self.findings:
            if finding.job_id != self.job_id:
                raise ValueError(
                    f"finding for {finding.capability.value!r} is scoped to job "
                    f"{finding.job_id!r}, not {self.job_id!r}; a finding never "
                    f"crosses between jobs"
                )
        return self


@final
class CapabilityMap(InventoriedModel):
    """The jobs-first Capability Map: findings nested per confirmed job.

    A private assessment of which relevant user jobs a system can fulfil,
    with the Evidence Level shown for every finding. Organized around the
    person's confirmed jobs — there is no system-level roll-up of any kind,
    and no field in which one could be expressed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: When the assessment ran (timezone-aware; naive is unverifiable).
    assessed_at: datetime

    #: One entry per confirmed job, canonically ordered by job id.
    jobs: tuple[JobFindings, ...] = Field(min_length=1)

    @field_validator("assessed_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "assessed_at must be timezone-aware; a naive timestamp is an "
                "unverifiable assessment time (fail closed)"
            )
        return value

    @field_validator("jobs")
    @classmethod
    def _unique_and_canonically_ordered(
        cls, value: tuple[JobFindings, ...]
    ) -> tuple[JobFindings, ...]:
        ids = [job.job_id for job in value]
        if len(set(ids)) != len(ids):
            raise ValueError("jobs contain duplicate job ids")
        return tuple(sorted(value, key=lambda job: job.job_id))
