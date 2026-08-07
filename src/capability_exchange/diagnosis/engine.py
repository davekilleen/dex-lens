"""The diagnosis engine: assess confirmed jobs against collected evidence (M-D).

:func:`assess` consumes ONLY confirmed Success Contracts and the approved
evidence scope (the adapter result envelope collected under it) — nothing
else exists as an input. An ``Inspection``-state job, or anything that is
not literally a confirmed :class:`SuccessContract`, is rejected outright
(R1: only user-confirmed jobs drive diagnosis).

Fully deterministic and fully local (pilot posture D8): same inputs in,
identical Capability Map out; no model call anywhere. Everything the engine
concludes beyond direct observation is a rule-based derivation, honestly
carried in the R2 states of the linked evidence.

How each finding is derived — branching only on the closed R2 vocabulary
plus the adapter's instrument grammar and the declared probe-id patterns
(:mod:`capability_exchange.diagnosis.foundations`):

- **Recent real examples, not presence.** Only outcome-class probes can
  ground ``Working``. Configuration/presence evidence is re-stated
  ``insufficient`` for the outcome claim unless a directly observed recent
  real example accompanies it — the presence of a skill, tool, integration,
  or configuration alone NEVER yields ``Working`` or ``Verified``.
- **Evidence Level is derived**, per finding, through the total R2 mapping
  over the linked evidence states (and re-checked structurally by the
  Finding schema).
- **Safety is scoped, never blanket.** ``safe`` requires boundary evidence
  plus a demonstrated outcome for THIS job; any observed beyond-the-job
  signal yields ``overbroad`` (a capability can be Working and Verified and
  still Overbroad); everything else stays ``unclear`` (fail closed).
- **Uncertainty stays visible.** Instrument failures, staleness, and
  configuration-only evidence each leave a note; they are never dropped.

Read-only diagnosis (non-negotiable boundary 1): this module holds no write
capability and no mutating entry point — it maps two in-memory values to a
third.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from capability_exchange.adapter import (
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
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
)
from capability_exchange.evidence import (
    CLAIM_SUPPORTING_STATES,
    EvidenceItem,
    EvidenceState,
    evidence_level,
)
from capability_exchange.jobs.contract import SuccessContract

__all__ = ["DiagnosisInputError", "assess"]


class DiagnosisInputError(Exception):
    """The engine was handed something other than its two lawful inputs.

    Diagnosis runs only against confirmed Success Contracts and the approved
    evidence scope. An ``Inspection``-state job, a mapping that merely looks
    like a contract, or an empty confirmation set is refused, never coerced.
    """


#: States that keep a ``working`` verdict honest: any linked assessment item
#: outside this set (degraded, failed, absent, withdrawn …) caps the
#: capability state at ``partial``.
_CLEAN_STATES = CLAIM_SUPPORTING_STATES


def _matches(patterns: tuple[str, ...], probe_id: str) -> bool:
    return any(pattern in probe_id for pattern in patterns)


def _failure_item(probe: ProbeResult, collected_at: datetime) -> EvidenceItem:
    """An instrument failure as R2 evidence: reported, never counted as success.

    ``could-not-check`` → ``blocked`` (collection prevented);
    ``broken`` → ``unverified`` (the check ran into failure; outcome uncertain).
    """
    state = (
        EvidenceState.BLOCKED
        if probe.health is InstrumentHealth.COULD_NOT_CHECK
        else EvidenceState.UNVERIFIED
    )
    return EvidenceItem(
        state=state, captured_at=collected_at, reference=f"probe:{probe.probe_id}"
    )


def _effective_items(probe: ProbeResult, *, now: datetime) -> tuple[EvidenceItem, ...]:
    """A healthy probe's items with source-age rules applied (R2 staleness)."""
    items: list[EvidenceItem] = []
    for item in probe.evidence:
        effective = item.effective_state(now=now)
        items.append(
            item if effective is item.state else item.model_copy(update={"state": effective})
        )
    return tuple(items)


def _assess_one(
    contract: SuccessContract,
    definition: FoundationDefinition,
    envelope: AdapterResultEnvelope,
    *,
    assessed_at: datetime,
) -> Finding:
    """One (confirmed job, Foundation Capability) finding. Deterministic."""
    outcome_items: list[EvidenceItem] = []
    configuration_items: list[EvidenceItem] = []
    boundary_items: list[EvidenceItem] = []
    overbroad_items: list[EvidenceItem] = []
    failure_items: list[EvidenceItem] = []
    failed_probe_lines: list[str] = []

    for probe in envelope.probes:
        # Role precedence is deterministic: an overbroad signal is never
        # laundered into a milder class, an outcome probe is never demoted
        # to configuration by an overlapping pattern.
        if _matches(definition.overbroad_probe_patterns, probe.probe_id):
            bucket = overbroad_items
        elif _matches(definition.outcome_probe_patterns, probe.probe_id):
            bucket = outcome_items
        elif _matches(definition.boundary_probe_patterns, probe.probe_id):
            bucket = boundary_items
        elif _matches(definition.configuration_probe_patterns, probe.probe_id):
            bucket = configuration_items
        else:
            # Evidence outside the declared observable-evidence patterns
            # grounds no finding (diagnosis never scans unrelated content).
            continue
        if probe.health is InstrumentHealth.HEALTHY:
            bucket.extend(_effective_items(probe, now=assessed_at))
        elif probe.health is InstrumentHealth.INTENTIONALLY_OFF:
            # Off by the person's own choice: honest absence, not failure.
            bucket.append(
                EvidenceItem(
                    state=EvidenceState.ABSENT,
                    captured_at=envelope.collected_at,
                    reference=f"probe:{probe.probe_id}",
                )
            )
        else:
            failure_items.append(_failure_item(probe, envelope.collected_at))
            failed_probe_lines.append(
                f"could not assess {probe.probe_id}: instrument {probe.health.value}"
            )

    directly_observed_outcome = any(
        item.state is EvidenceState.OBSERVED for item in outcome_items
    )
    if not directly_observed_outcome:
        # File exists is evidence of configuration, not proof of a job
        # outcome: without a directly observed recent real example, presence
        # evidence is insufficient for the outcome claim (never Working,
        # never Verified from presence alone).
        configuration_items = [
            (
                item.model_copy(update={"state": EvidenceState.INSUFFICIENT})
                if item.state in CLAIM_SUPPORTING_STATES
                else item
            )
            for item in configuration_items
        ]

    # --- Axis 1: Capability State (branches only on R2 states) -------------
    assessment_items = (*outcome_items, *configuration_items, *failure_items)
    outcome_supported = any(item.state in CLAIM_SUPPORTING_STATES for item in outcome_items)
    if outcome_supported and all(item.state in _CLEAN_STATES for item in assessment_items):
        capability_state = CapabilityState.WORKING
    elif outcome_supported:
        capability_state = CapabilityState.PARTIAL
    elif any(
        item.state is not EvidenceState.NOT_ASSESSED
        for item in (*outcome_items, *configuration_items)
    ):
        # Something was actually evaluated (including honest absence or
        # configuration-only presence) and no recent real example
        # demonstrated the outcome.
        capability_state = CapabilityState.NOT_DEMONSTRATED
    else:
        capability_state = CapabilityState.UNKNOWN

    # --- Axis 3: Safety Boundary (scoped to this job; fail closed) ---------
    overbroad_signal = any(
        item.state in CLAIM_SUPPORTING_STATES for item in overbroad_items
    )
    boundary_supported = any(
        item.state in CLAIM_SUPPORTING_STATES for item in boundary_items
    )
    if overbroad_signal:
        safety_boundary = SafetyBoundary.OVERBROAD
    elif boundary_supported and outcome_supported and not failure_items:
        safety_boundary = SafetyBoundary.SAFE
    else:
        safety_boundary = SafetyBoundary.UNCLEAR

    # --- Linked evidence and Axis 2: Evidence Level (derived, total) -------
    linked = tuple(
        sorted(
            (*assessment_items, *boundary_items, *overbroad_items),
            key=lambda item: (item.reference, item.state.value),
        )
    )
    level = evidence_level(item.state for item in linked)

    # --- Uncertainty stays visible -----------------------------------------
    notes = list(failed_probe_lines)
    if configuration_items and not directly_observed_outcome:
        notes.append(
            "configuration was observed, but no recent real example demonstrates "
            "this outcome; presence alone is not outcome evidence"
        )
    if any(item.state is EvidenceState.STALE for item in linked):
        notes.append(
            "some evidence is older than its freshness threshold and is labeled "
            "stale; it no longer supports the claim"
        )
    if not linked:
        notes.append(
            "no collected evidence bears on this capability for this job; it "
            "remains unknown, not assumed"
        )
    if overbroad_signal:
        notes.append(
            "observed behavior reaches beyond what this job requires; the "
            "boundary is overbroad for this job even where the capability works"
        )
    elif safety_boundary is SafetyBoundary.UNCLEAR:
        notes.append(
            "the safety boundary for this job could not be confirmed from the "
            "available evidence; it remains unclear, not assumed safe"
        )

    return Finding(
        capability=definition.capability,
        job_id=contract.job_id,
        capability_state=capability_state,
        evidence_level=level,
        safety_boundary=safety_boundary,
        evidence=linked,
        uncertainty_notes=tuple(sorted(set(notes))),
        practical_implication=definition.practical_implication,
        recommended_next_move=definition.next_moves[capability_state.value],
    )


def _require_confirmed_contracts(
    confirmed_contracts: Iterable[object],
) -> tuple[SuccessContract, ...]:
    """Exactly confirmed Success Contracts, or refuse. Never coerces."""
    contracts: list[SuccessContract] = []
    for candidate in confirmed_contracts:
        if type(candidate) is not SuccessContract:
            raise DiagnosisInputError(
                f"diagnosis consumes only confirmed Success Contracts; got "
                f"{type(candidate).__name__} (an Inspection-state job or any "
                f"other input is rejected, never coerced — R1)"
            )
        if candidate.lifecycle != "diagnosis":
            raise DiagnosisInputError(
                "diagnosis consumes only contracts in the 'diagnosis' lifecycle"
            )
        contracts.append(candidate)
    if not contracts:
        raise DiagnosisInputError(
            "diagnosis runs only against confirmed Success Contracts; with none "
            "confirmed there is nothing to assess (detection proposes, the "
            "person confirms — no contract, no diagnosis)"
        )
    ids = [contract.job_id for contract in contracts]
    if len(set(ids)) != len(ids):
        raise DiagnosisInputError("confirmed contracts contain duplicate job ids")
    return tuple(sorted(contracts, key=lambda contract: contract.job_id))


def assess(
    confirmed_contracts: Iterable[object],
    envelope: AdapterResultEnvelope,
    *,
    assessed_at: datetime | None = None,
) -> CapabilityMap:
    """Assess every confirmed job against the approved-scope evidence.

    Inputs — the only two that exist:

    - ``confirmed_contracts``: confirmed :class:`SuccessContract` values.
      Anything else (an ``Inspection``-state job, a lookalike mapping, an
      empty set) raises :class:`DiagnosisInputError`.
    - ``envelope``: the deterministic collector output gathered under the
      approved evidence scope.

    ``assessed_at`` defaults to the envelope's collection time, keeping the
    default fully deterministic; pass a later moment to let freshness rules
    degrade aging evidence to ``stale``.

    Returns the jobs-first :class:`CapabilityMap`: per confirmed job, one
    three-axis finding for each of the eight Foundation Capabilities.
    """
    if not isinstance(envelope, AdapterResultEnvelope):
        raise DiagnosisInputError(
            "diagnosis assesses evidence from an adapter result envelope "
            "collected under the approved scope; nothing else is readable"
        )
    contracts = _require_confirmed_contracts(confirmed_contracts)
    moment = envelope.collected_at if assessed_at is None else assessed_at

    jobs = tuple(
        JobFindings(
            job_id=contract.job_id,
            findings=tuple(
                _assess_one(
                    contract,
                    FOUNDATION_DEFINITIONS[capability],
                    envelope,
                    assessed_at=moment,
                )
                for capability in FoundationCapability
            ),
        )
        for contract in contracts
    )
    return CapabilityMap(assessed_at=moment, jobs=jobs)
