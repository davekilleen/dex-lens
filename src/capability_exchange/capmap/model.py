"""The jobs-first Capability Map model (module M-D renderer side; #352).

A Capability Map is a private assessment of which relevant user jobs a
system can fulfil, with the Evidence Level shown for every finding. It is
organized around the person's confirmed jobs: Foundation Capability
findings nest INSIDE the job they were assessed against — there is no flat
system-wide finding list, and no field in which one could be expressed.

Collector/renderer split (Doctor pattern, HANDOFF 3.1, binding): the
diagnosis engine (the deterministic collector) derives every
:class:`~capability_exchange.diagnosis.finding.Finding` and assembles this
map; the renderer (:mod:`capability_exchange.capmap.render`) consumes the
Finding objects as-is and never re-derives an axis, a level, or a note.

Per finding the map carries: linked evidence, visible uncertainty, the
safety boundary, one practical implication, why the capability matters to
this job, and exactly one useful next move — all fields of
:class:`~capability_exchange.diagnosis.finding.Finding` itself.

No aggregate anything: no roll-up, rank, or percentage field exists in any
model here, every model is frozen with a closed field set
(``extra="forbid"``), and the unrepresentability schema test walks this
whole tree to prove an aggregate is structurally impossible, not merely
absent.

R1 tie-in: each job entry embeds the confirmed
:class:`~capability_exchange.jobs.contract.SuccessContract` itself. An
``Inspection``-state draft is a distinct type with different required
fields and fails validation outright — a map entry for an unconfirmed job
is unrepresentable, not filtered.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self, final

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.diagnosis.finding import Finding
from capability_exchange.diagnosis.foundations import FoundationCapability
from capability_exchange.jobs.contract import SuccessContract

__all__ = ["CapabilityMap", "JobFindings"]


@final
class JobFindings(InventoriedModel):
    """One confirmed job with its findings nested inside it.

    Embeds the confirmed Success Contract the findings were assessed
    against, so the rendered map can show the job in the person's own
    terms. Exactly one finding per Foundation Capability, each scoped to
    this job — no capability silently missing, none doubled, none borrowed
    from another job.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The confirmed job these findings are scoped to. Only a confirmed
    #: :class:`SuccessContract` is representable here (R1).
    contract: SuccessContract

    #: Exactly one finding per Foundation Capability (validated).
    findings: tuple[Finding, ...] = Field(min_length=1)

    @property
    def job_id(self) -> str:
        """The confirmed job's identity (from its Success Contract)."""
        return self.contract.job_id

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: object
    ) -> JobFindings:
        # model_construct skips validation by design; "a map entry for an
        # unconfirmed job is unrepresentable" (R1) must hold on that route
        # too, or an Inspection draft could impersonate a confirmed job.
        entry = super().model_construct(_fields_set, **values)  # type: ignore[arg-type]
        entry._assert_confirmed_shape()
        return entry

    def model_copy(self, *, update: dict[str, object] | None = None, deep: bool = False) -> Self:
        # model_copy also skips validation; a contract swap refuses too.
        copied = super().model_copy(update=update, deep=deep)  # type: ignore[arg-type]
        copied._assert_confirmed_shape()
        return copied

    def _assert_confirmed_shape(self) -> None:
        contract = self.__dict__.get("contract")
        findings = self.__dict__.get("findings")
        if type(contract) is not SuccessContract:
            raise ValueError(
                "a JobFindings entry embeds a confirmed SuccessContract only; "
                "an Inspection-state draft is unrepresentable here on every "
                "construction route (R1)"
            )
        if not isinstance(findings, tuple) or any(
            type(finding) is not Finding for finding in findings
        ):
            raise ValueError("a JobFindings entry holds Finding values only")
        self._one_finding_per_capability_for_this_job()

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
            if finding.job_id != self.contract.job_id:
                raise ValueError(
                    f"finding for {finding.capability.value!r} is scoped to job "
                    f"{finding.job_id!r}, not {self.contract.job_id!r}; a finding "
                    f"never crosses between jobs"
                )
        return self


@final
class CapabilityMap(InventoriedModel):
    """The jobs-first Capability Map: findings nested per confirmed job.

    Organized around the person's confirmed jobs — never a flat
    system-wide finding list, and never a system-level roll-up of any
    kind. The Evidence Level is shown for every finding.
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

    @classmethod
    def model_construct(
        cls, _fields_set: set[str] | None = None, **values: object
    ) -> CapabilityMap:
        # model_construct skips validation by design; the map's jobs-first
        # shape must hold on that route too (R1: confirmed entries only).
        built = super().model_construct(_fields_set, **values)  # type: ignore[arg-type]
        built._assert_jobs_are_job_findings()
        return built

    def model_copy(self, *, update: dict[str, object] | None = None, deep: bool = False) -> Self:
        # model_copy also skips validation; a jobs swap refuses the same way.
        copied = super().model_copy(update=update, deep=deep)  # type: ignore[arg-type]
        copied._assert_jobs_are_job_findings()
        return copied

    def _assert_jobs_are_job_findings(self) -> None:
        jobs = self.__dict__.get("jobs")
        if (
            not isinstance(jobs, tuple)
            or not jobs
            or any(type(entry) is not JobFindings for entry in jobs)
        ):
            raise ValueError(
                "a CapabilityMap holds JobFindings entries only — one per "
                "confirmed job; nothing else is representable on any "
                "construction route (R1)"
            )

    def job(self, job_id: str) -> JobFindings:
        """The entry for one confirmed job, or a refusal naming no contents."""
        for entry in self.jobs:
            if entry.job_id == job_id:
                return entry
        raise KeyError(f"the Capability Map has no confirmed job {job_id!r}")
