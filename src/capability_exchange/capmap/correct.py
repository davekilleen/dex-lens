"""Person-driven corrections to the Capability Map (M-D; #352, R1, R2).

The person can correct both halves of what the map rests on:

- **Supporting evidence** — :func:`correct_supporting_evidence` routes the
  correction back as a NEW user-reported R2 evidence item on the named
  finding. The person's account is recorded honestly as their account: the
  item's state is ``user-reported`` by construction (the function accepts
  no state), so through the total R2 mapping its own contribution to the
  Evidence Level caps at Reported. A correction NEVER silently upgrades an
  Evidence Level: the only movement it can cause is Unknown → Reported —
  which is the mapping recording that the person's account now exists —
  and any movement at all is announced in a visible uncertainty note. An
  upgrade past Reported is refused outright (fail closed).
- **The job definition** — :func:`reopen_job_definition` takes the job OUT
  of the map and back into the provisional R1 ``Inspection`` state as an
  editable draft. Nothing here can mint a confirmed
  :class:`~capability_exchange.jobs.contract.SuccessContract`: the draft
  re-enters the confirmation flow and only the person's explicit
  :meth:`~capability_exchange.jobs.inspection.InspectionJobStore.confirm`
  call exits ``Inspection``. The job's findings are dropped with it —
  findings assessed against a definition the person just corrected are no
  longer findings about anything confirmed.

Read-only module: it maps in-memory values to new in-memory values and
holds no write capability (non-negotiable boundary 1). Persisting the
reopened draft is the job store's business, through the G2 boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from capability_exchange.capmap.model import CapabilityMap, JobFindings
from capability_exchange.diagnosis.finding import Finding
from capability_exchange.diagnosis.foundations import FoundationCapability
from capability_exchange.evidence import (
    EvidenceItem,
    EvidenceLevel,
    EvidenceState,
    evidence_level,
)
from capability_exchange.jobs.contract import (
    CONTRACT_TEXT_MAX_LENGTH,
    validate_contract_text,
)
from capability_exchange.jobs.inspection import InspectionJob

__all__ = [
    "CorrectionError",
    "ReopenedJob",
    "correct_supporting_evidence",
    "reopen_job_definition",
]


class CorrectionError(Exception):
    """A correction was refused. The message says why, honestly."""


#: Prefix for the non-raw reference a correction item carries.
_CORRECTION_REFERENCE_PREFIX = "user-correction:"

#: Visible note prefix carrying the person's account on the finding.
_ACCOUNT_NOTE_PREFIX = "the person's correction, in their words: "


def _find_job(capability_map: CapabilityMap, job_id: str) -> JobFindings:
    for job in capability_map.jobs:
        if job.job_id == job_id:
            return job
    raise CorrectionError(
        f"the Capability Map has no confirmed job {job_id!r}; corrections "
        f"apply only to what the map actually shows"
    )


def correct_supporting_evidence(
    capability_map: CapabilityMap,
    *,
    job_id: str,
    capability: FoundationCapability,
    account: str,
    corrected_at: datetime,
) -> CapabilityMap:
    """Route the person's evidence correction back as a user-reported item.

    Returns a new map in which the named finding carries one additional
    R2 evidence item in the ``user-reported`` state (the only state this
    function can produce) plus visible notes recording the correction and
    the person's account. The finding's Evidence Level is re-derived
    through the total R2 mapping; the capability state and safety boundary
    are untouched — re-deriving those axes is the diagnosis engine's job
    on the next assessment, never a side effect of a correction.
    """
    if not isinstance(capability, FoundationCapability):
        raise CorrectionError(
            "a correction names one of the eight Foundation Capabilities; "
            "nothing else is correctable"
        )
    account_text = validate_contract_text(account, "correction account")
    if len(_ACCOUNT_NOTE_PREFIX) + len(account_text) > CONTRACT_TEXT_MAX_LENGTH:
        raise CorrectionError(
            f"the correction account is too long to stay a bounded visible "
            f"note; keep it within "
            f"{CONTRACT_TEXT_MAX_LENGTH - len(_ACCOUNT_NOTE_PREFIX)} characters"
        )

    job = _find_job(capability_map, job_id)
    target: Finding | None = None
    for finding in job.findings:
        if finding.capability is capability:
            target = finding
            break
    if target is None:  # unreachable: JobFindings always carries all eight
        raise CorrectionError(
            f"no finding for {capability.value!r} exists on job {job_id!r}"
        )

    correction_item = EvidenceItem(
        state=EvidenceState.USER_REPORTED,
        captured_at=corrected_at,
        reference=f"{_CORRECTION_REFERENCE_PREFIX}{job_id}/{capability.value}",
    )
    evidence = tuple(
        sorted(
            (*target.evidence, correction_item),
            key=lambda item: (item.reference, item.state.value),
        )
    )
    derived = evidence_level(item.state for item in evidence)

    # A correction never silently upgrades an Evidence Level. The person's
    # account can at most register as Reported; anything stronger would be
    # the correction manufacturing verification, so it is refused outright.
    if derived.rank() > max(target.evidence_level.rank(), EvidenceLevel.REPORTED.rank()):
        raise CorrectionError(
            f"refusing a correction that would raise the Evidence Level from "
            f"{target.evidence_level.value!r} to {derived.value!r}; a person's "
            f"account is recorded as reported, never as stronger verification"
        )

    notes = set(target.uncertainty_notes)
    notes.add(f"{_ACCOUNT_NOTE_PREFIX}{account_text}")
    notes.add(
        "the person corrected the supporting evidence here; their account "
        "is recorded as reported evidence, never as direct inspection"
    )
    if derived is not target.evidence_level:
        notes.add(
            f"this correction moved the Evidence Level from "
            f"{target.evidence_level.value} to {derived.value} — the level "
            f"now records that the person's own account exists, nothing more"
        )

    corrected = Finding(
        capability=target.capability,
        job_id=target.job_id,
        capability_state=target.capability_state,
        evidence_level=derived,
        safety_boundary=target.safety_boundary,
        evidence=evidence,
        uncertainty_notes=tuple(sorted(notes)),
        practical_implication=target.practical_implication,
        why_it_matters=target.why_it_matters,
        recommended_next_move=target.recommended_next_move,
    )
    corrected_job = JobFindings(
        contract=job.contract,
        findings=tuple(
            corrected if finding.capability is capability else finding
            for finding in job.findings
        ),
    )
    return CapabilityMap(
        assessed_at=capability_map.assessed_at,
        jobs=tuple(
            corrected_job if entry.job_id == job_id else entry
            for entry in capability_map.jobs
        ),
    )


@dataclass(frozen=True, slots=True)
class ReopenedJob:
    """The result of correcting a job definition: back to ``Inspection``.

    ``draft`` is the editable, discardable ``Inspection``-state draft that
    must be explicitly re-confirmed before it can drive diagnosis again
    (R1). ``remaining_map`` is the Capability Map without the reopened job,
    or ``None`` when it was the only job — a map with nothing confirmed in
    it does not exist.
    """

    draft: InspectionJob
    remaining_map: CapabilityMap | None


def reopen_job_definition(
    capability_map: CapabilityMap,
    *,
    job_id: str,
    reopened_at: datetime,
    title: str | None = None,
    situation: str | None = None,
    desired_outcome: str | None = None,
) -> ReopenedJob:
    """Correct a job definition: the job re-enters the R1 confirmation flow.

    The person's edits land on an ``Inspection``-state draft seeded from
    the confirmed contract they are correcting; unedited text carries over
    for them to review. The draft keeps non-raw references to the evidence
    the dropped findings rested on, so the trail stays inspectable without
    persisting any evidence content (G2). Only an explicit confirmation
    call on the job store turns the draft back into a Success Contract.
    """
    job = _find_job(capability_map, job_id)
    contract = job.contract

    references: list[str] = []
    seen: set[str] = set()
    for finding in job.findings:
        for item in finding.evidence:
            if item.reference not in seen:
                seen.add(item.reference)
                references.append(item.reference)

    draft = InspectionJob(
        job_id=contract.job_id,
        title=(
            title
            if title is not None
            else f"Corrected job: {contract.job_id.replace('-', ' ')}"
        ),
        situation=contract.situation if situation is None else situation,
        desired_outcome=(
            contract.desired_outcome if desired_outcome is None else desired_outcome
        ),
        evidence_references=tuple(references),
        created_at=reopened_at,
    )

    remaining = tuple(entry for entry in capability_map.jobs if entry.job_id != job_id)
    remaining_map = (
        CapabilityMap(assessed_at=capability_map.assessed_at, jobs=remaining)
        if remaining
        else None
    )
    return ReopenedJob(draft=draft, remaining_map=remaining_map)
