"""Deterministic candidate-job proposal from an adapter result envelope (M-C).

Rule-based heuristics over the observable local patterns an adapter
reported — recurring skill/workflow patterns, instruction files, tool
configuration, recent-activity shapes. Fully deterministic and fully local
(pilot posture D8): same envelope in, byte-identical proposals out; no
model call anywhere.

Every proposal is honestly marked **inferred** (R2): its evidence items
carry the ``inferred`` state — never ``observed``, because a proposed job
is a conclusion drawn *from* observations, not an observation — and its
rationale must say so in words. Inferences remain suggestions, never facts.

**Detection proposes; it never enrolls.** The strongest thing this module
can produce is an ``Inspection``-state draft
(:func:`to_inspection_job`) — local-only, editable, discardable, excluded
from every sharing surface. Nothing here can construct a
:class:`~capability_exchange.jobs.contract.SuccessContract`; that requires
the person's explicit confirmation call.

Fail closed: proposals derive only from healthy instruments carrying
directly ``observed`` evidence. A broken or could-not-check instrument
proposes nothing (instrument failure is never counted as signal), and
``absent`` / ``stale`` / ``conflicting`` / any other non-observed state
proposes nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import final

from pydantic import ConfigDict, Field, field_validator

from capability_exchange.adapter import AdapterResultEnvelope, InstrumentHealth, ProbeResult
from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.evidence import EvidenceItem, EvidenceState
from capability_exchange.jobs.contract import validate_contract_text, validate_job_id
from capability_exchange.jobs.inspection import InspectionJob

__all__ = [
    "CandidateJobProposal",
    "propose_candidate_jobs",
    "to_inspection_job",
]

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


@final
class CandidateJobProposal(InventoriedModel):
    """One proposed candidate job: an inference, honestly marked as one.

    Ephemeral data (G2: ``storage: none``, ``sharing: never``): a proposal
    exists only for the session that produced it, until the person keeps it
    as an ``Inspection``-state draft or lets it go.

    The schema enforces honest marking structurally: every evidence item
    must carry the R2 state ``inferred``, and the rationale must contain
    the word "inferred". A proposal presented as fact is unrepresentable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Stable kebab-case identity of the proposed candidate.
    candidate_id: str

    #: Short suggestion-phrased name for the candidate job.
    title: str

    #: Draft situation text the person can edit in ``Inspection``.
    draft_situation: str

    #: Draft desired-outcome text the person can edit in ``Inspection``.
    draft_desired_outcome: str

    #: Why this candidate was proposed — must say "inferred" in words.
    rationale: str

    #: R2 evidence for the inference. At least one item; every item must
    #: carry the ``inferred`` state (a proposal is never an observation).
    evidence: tuple[EvidenceItem, ...] = Field(min_length=1)

    @field_validator("candidate_id")
    @classmethod
    def _kebab_candidate_id(cls, value: str) -> str:
        if not _KEBAB_RE.match(value):
            raise ValueError(f"candidate_id {value!r} must be kebab-case")
        return value

    @field_validator("title")
    @classmethod
    def _title_text(cls, value: str) -> str:
        return validate_contract_text(value, "title")

    @field_validator("draft_situation")
    @classmethod
    def _situation_text(cls, value: str) -> str:
        return validate_contract_text(value, "draft_situation")

    @field_validator("draft_desired_outcome")
    @classmethod
    def _outcome_text(cls, value: str) -> str:
        return validate_contract_text(value, "draft_desired_outcome")

    @field_validator("rationale")
    @classmethod
    def _rationale_marks_inference(cls, value: str) -> str:
        validated = validate_contract_text(value, "rationale")
        if "inferred" not in validated.lower():
            raise ValueError(
                "rationale must say the proposal is inferred; inferences are "
                "suggestions, never presented as fact (R2)"
            )
        return validated

    @field_validator("evidence")
    @classmethod
    def _every_item_inferred(cls, value: tuple[EvidenceItem, ...]) -> tuple[EvidenceItem, ...]:
        for item in value:
            if item.state is not EvidenceState.INFERRED:
                raise ValueError(
                    f"proposal evidence carries state {item.state.value!r}; a "
                    f"candidate-job proposal is an inference and every item "
                    f"must be marked inferred, never presented as fact (R2)"
                )
        return value


# --------------------------------------------------------------------------
# The deterministic ruleset (data, not code paths)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ProposalRule:
    """One pattern → candidate mapping. Provider-neutral, keyed by probe id."""

    probe_id: str
    candidate_id: str
    title: str
    draft_situation: str
    draft_desired_outcome: str
    rationale: str


_HONESTY_TAIL = "a suggestion for you to confirm, edit, or discard - not a fact"

_RULES: tuple[_ProposalRule, ...] = (
    _ProposalRule(
        probe_id="skills-present",
        candidate_id="recurring-skill-workflows",
        title="Possible job: run your recurring skill-based workflows",
        draft_situation=(
            "You appear to run repeated workflows through saved skills in your system"
        ),
        draft_desired_outcome=(
            "Your recurring workflows run dependably whenever you need them"
        ),
        rationale=(
            f"inferred from skill definitions observed in the approved scope; {_HONESTY_TAIL}"
        ),
    ),
    _ProposalRule(
        probe_id="instructions-present",
        candidate_id="instruction-guided-work",
        title="Possible job: keep your standing instructions working for you",
        draft_situation=(
            "You appear to steer your system with standing instruction files"
        ),
        draft_desired_outcome=(
            "Your system consistently honors the instructions you maintain"
        ),
        rationale=(
            f"inferred from instruction files observed in the approved scope; {_HONESTY_TAIL}"
        ),
    ),
    _ProposalRule(
        probe_id="settings-present",
        candidate_id="tool-configuration-upkeep",
        title="Possible job: keep your tool configuration intentional",
        draft_situation=(
            "You appear to maintain tool configuration files for your system"
        ),
        draft_desired_outcome=(
            "Your tool configuration stays understood, intentional, and current"
        ),
        rationale=(
            f"inferred from tool configuration observed in the approved scope; {_HONESTY_TAIL}"
        ),
    ),
    _ProposalRule(
        # No M1 probe emits this id yet; the rule exists so later adapters
        # reporting recent-activity shapes feed the same deterministic path.
        probe_id="recent-activity",
        candidate_id="recent-activity-follow-through",
        title="Possible job: finish the work you keep returning to",
        draft_situation=(
            "Your recent activity appears to include work you return to repeatedly"
        ),
        draft_desired_outcome=(
            "The work you return to repeatedly reaches a dependable outcome"
        ),
        rationale=(
            f"inferred from recent-activity shapes observed in the approved scope; "
            f"{_HONESTY_TAIL}"
        ),
    ),
)

_RULES_BY_PROBE: dict[str, _ProposalRule] = {rule.probe_id: rule for rule in _RULES}


def _observed_items(probe: ProbeResult) -> tuple[EvidenceItem, ...]:
    """Directly observed evidence from a healthy instrument; else nothing.

    Instrument failure is never counted as signal, and no state other than
    ``observed`` (not ``absent``, not ``stale``, not ``conflicting``, not
    even ``user-reported``) grounds an automatic proposal.
    """
    if probe.health is not InstrumentHealth.HEALTHY:
        return ()
    return tuple(item for item in probe.evidence if item.state is EvidenceState.OBSERVED)


def propose_candidate_jobs(
    envelope: AdapterResultEnvelope,
) -> tuple[CandidateJobProposal, ...]:
    """Propose candidate jobs from one result envelope. Deterministic.

    Same envelope in, identical proposals out — proposals are ordered by
    ``candidate_id`` and derive only from the envelope's contents. Every
    proposal's evidence is marked ``inferred`` and points at the source
    observation's existing non-raw reference (no new reference material is
    derived from content).
    """
    proposals: list[CandidateJobProposal] = []
    for probe in envelope.probes:
        rule = _RULES_BY_PROBE.get(probe.probe_id)
        if rule is None:
            continue
        observed = _observed_items(probe)
        if not observed:
            continue
        proposals.append(
            CandidateJobProposal(
                candidate_id=rule.candidate_id,
                title=rule.title,
                draft_situation=rule.draft_situation,
                draft_desired_outcome=rule.draft_desired_outcome,
                rationale=rule.rationale,
                evidence=tuple(
                    EvidenceItem(
                        state=EvidenceState.INFERRED,
                        captured_at=envelope.collected_at,
                        reference=source.reference,
                    )
                    for source in observed
                ),
            )
        )
    return tuple(sorted(proposals, key=lambda proposal: proposal.candidate_id))


def to_inspection_job(
    proposal: CandidateJobProposal, *, created_at: datetime
) -> InspectionJob:
    """Keep a proposal as an ``Inspection``-state draft. Never enrolls.

    The result is the provisional draft type: local-only, editable,
    discardable, type-level excluded from every sharing surface. What
    carries over from the proposal's evidence is references only — the
    ephemeral evidence items themselves are never persisted (G2).
    """
    seen: set[str] = set()
    references: list[str] = []
    for item in proposal.evidence:
        if item.reference not in seen:
            seen.add(item.reference)
            references.append(item.reference)
    return InspectionJob(
        job_id=validate_job_id(proposal.candidate_id),
        title=proposal.title,
        situation=proposal.draft_situation,
        desired_outcome=proposal.draft_desired_outcome,
        evidence_references=tuple(references),
        created_at=created_at,
    )
