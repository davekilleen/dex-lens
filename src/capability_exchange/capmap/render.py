"""Plain-text/markdown rendering of the jobs-first Capability Map (M-D).

Collector/renderer split (Doctor pattern, HANDOFF 3.1, binding): this
renderer consumes the map's Finding objects exactly as the deterministic
collector derived them. It never re-derives an axis, a level, or a note —
every phrase below is a fixed wording for a value that already exists.

Rendering rules, all testable:

- **Jobs-first.** One section per confirmed job, in the map's canonical
  order, with that job's findings nested inside it. No flat system-wide
  finding list exists to render.
- **Honest unknowns.** An Unknown is reported as an unknown, in
  "we couldn't check X because Y" phrasing, and is never dressed up as
  anything reassuring. ``absent`` and ``not-assessed`` evidence never
  reads as passing (R2).
- **Non-judgmental language.** The words describe what the evidence showed
  and did not show for THIS job; nothing grades the person or their system.
- **Vocabulary-compliant.** The Section 1.5 "Avoid" terms appear nowhere in
  rendered output (scanned by test).
- **The Evidence Level is shown for every finding** (Section 1.5, binding).
- **Deterministic.** Same map in, byte-identical text out.
"""

from __future__ import annotations

from types import MappingProxyType

from capability_exchange.capmap.model import CapabilityMap, JobFindings
from capability_exchange.diagnosis.finding import (
    CapabilityState,
    Finding,
    SafetyBoundary,
)
from capability_exchange.diagnosis.foundations import FoundationCapability
from capability_exchange.evidence import EvidenceItem, EvidenceLevel, EvidenceState

__all__ = ["CAPABILITY_HEADINGS", "render_capability_map"]

#: Display headings for the eight Foundation Capabilities (#351 names).
CAPABILITY_HEADINGS: MappingProxyType[FoundationCapability, str] = MappingProxyType(
    {
        FoundationCapability.OWNERSHIP_PORTABILITY: "Ownership & Portability",
        FoundationCapability.PRIVACY_MINIMAL_DISCLOSURE: "Privacy & Minimal Disclosure",
        FoundationCapability.CONTEXT_ORIENTATION: "Context & Orientation",
        FoundationCapability.DURABLE_MEMORY_PROVENANCE: "Durable Memory & Provenance",
        FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL: "Scoped Agency & Human Control",
        FoundationCapability.SAFE_CHANGE_RECOVERY: "Safe Change & Recovery",
        FoundationCapability.HONEST_HEALTH_OBSERVABILITY: "Honest Health & Observability",
        FoundationCapability.COMPOUNDING_CORRECTABILITY: "Compounding & Correctability",
    }
)

#: Axis 1 wordings — descriptive of the evidence, never a grade.
_STATE_PHRASES: MappingProxyType[CapabilityState, str] = MappingProxyType(
    {
        CapabilityState.WORKING: (
            "working for this job, demonstrated by recent real examples in "
            "the evidence collected"
        ),
        CapabilityState.PARTIAL: (
            "partly demonstrated for this job: some evidence supports the "
            "outcome and some could not be relied on"
        ),
        CapabilityState.NOT_DEMONSTRATED: (
            "not demonstrated: the evidence we could collect showed no "
            "recent real example of this outcome for this job"
        ),
        CapabilityState.UNKNOWN: (
            "unknown: we couldn't assess this for this job — the reasons "
            "are listed below, and an unknown stays an unknown in this map"
        ),
    }
)

#: Axis 2 wordings — how the claim is known (Section 1.5, verbatim senses).
_LEVEL_PHRASES: MappingProxyType[EvidenceLevel, str] = MappingProxyType(
    {
        EvidenceLevel.VERIFIED: "verified — established by direct inspection",
        EvidenceLevel.SUPPORTED: "supported — based on material the person supplied",
        EvidenceLevel.REPORTED: "reported — based on the person's own account",
        EvidenceLevel.UNKNOWN: (
            "unknown — we couldn't establish this claim either way, and it "
            "is shown as unknown rather than as anything more reassuring"
        ),
    }
)

#: Axis 3 wordings — scoped to the assessed job, never a blanket claim.
_BOUNDARY_PHRASES: MappingProxyType[SafetyBoundary, str] = MappingProxyType(
    {
        SafetyBoundary.SAFE: (
            "within this job's limits on the evidence collected — scoped to "
            "this job only, never a blanket certification"
        ),
        SafetyBoundary.OVERBROAD: (
            "reaches beyond what this job needs, even where the capability works"
        ),
        SafetyBoundary.UNCLEAR: (
            "we couldn't confirm the boundary for this job from the "
            "available evidence, so it stays unclear rather than assumed"
        ),
    }
)


def _evidence_line(item: EvidenceItem) -> str:
    """One honest line per evidence item, total over the R2 vocabulary.

    Instrument failure reads as "we couldn't check X because Y" — reported,
    never counted as success. ``absent`` / ``not-assessed`` never read as
    passing (R2).
    """
    captured = f"(captured {item.captured_at.isoformat()})"
    reference = item.reference
    phrases: dict[EvidenceState, str] = {
        EvidenceState.OBSERVED: f"observed by direct inspection — {reference} {captured}",
        EvidenceState.USER_REPORTED: f"the person's own account — {reference} {captured}",
        EvidenceState.INFERRED: (
            f"inferred — a derivation, not a direct observation — {reference} {captured}"
        ),
        EvidenceState.STALE: (
            f"stale — older than its freshness threshold, so it no longer "
            f"supports the claim — {reference} {captured}"
        ),
        EvidenceState.CONFLICTING: (
            f"conflicting — contradicted by other evidence, so it supports "
            f"nothing — {reference} {captured}"
        ),
        EvidenceState.ABSENT: (
            f"absent — we looked and verifiably found nothing at "
            f"{reference}; absence is reported, never counted either way "
            f"{captured}"
        ),
        EvidenceState.NOT_ASSESSED: (
            f"not assessed — {reference} was never evaluated, so it "
            f"supports nothing {captured}"
        ),
        EvidenceState.INSUFFICIENT: (
            f"insufficient for this outcome claim — {reference} shows "
            f"presence or configuration, and presence alone is not outcome "
            f"evidence {captured}"
        ),
        EvidenceState.BLOCKED: (
            f"we couldn't check {reference} because collection was "
            f"prevented {captured}"
        ),
        EvidenceState.UNVERIFIED: (
            f"we couldn't check {reference} because the check ran into "
            f"failure before reaching an answer {captured}"
        ),
        EvidenceState.WITHDRAWN: (
            f"withdrawn — the person retracted this, so it supports "
            f"nothing — {reference} {captured}"
        ),
    }
    return phrases[item.state]


def _render_finding(finding: Finding) -> list[str]:
    lines = [
        f"### {CAPABILITY_HEADINGS[finding.capability]}",
        "",
        f"- What the evidence showed: {_STATE_PHRASES[finding.capability_state]}.",
        f"- Evidence Level (how this is known): {_LEVEL_PHRASES[finding.evidence_level]}.",
        f"- Boundary for this job: {_BOUNDARY_PHRASES[finding.safety_boundary]}.",
    ]
    if finding.evidence:
        lines.append("- Evidence this rests on:")
        lines.extend(f"  - {_evidence_line(item)}" for item in finding.evidence)
    else:
        lines.append(
            "- Evidence this rests on: none — we couldn't collect anything "
            "bearing on this capability for this job."
        )
    if finding.uncertainty_notes:
        lines.append("- What stays uncertain, and why:")
        lines.extend(f"  - {note}" for note in finding.uncertainty_notes)
    lines.extend(
        [
            f"- What this means in practice: {finding.practical_implication}",
            f"- Why this matters to this job: {finding.why_it_matters}",
            f"- One useful next move: {finding.recommended_next_move}",
            "",
        ]
    )
    return lines


def _render_job(job: JobFindings) -> list[str]:
    contract = job.contract
    lines = [
        f"## Your job: {contract.job_id}",
        "",
        f"- Situation: {contract.situation}",
        f"- Desired outcome: {contract.desired_outcome}",
        "- Success evidence you named: " + "; ".join(contract.success_evidence),
        f"- You confirmed this job on {contract.confirmed_at.isoformat()}.",
        "",
    ]
    for finding in job.findings:
        lines.extend(_render_finding(finding))
    return lines


def render_capability_map(capability_map: CapabilityMap) -> str:
    """Render the jobs-first Capability Map as markdown text. Deterministic."""
    lines = [
        "# Capability Map",
        "",
        "Private to you, and organized around the jobs you confirmed — the",
        "findings for each capability sit inside the job they were assessed",
        "against, and nothing here is rolled up, ranked, or graded. Every",
        "finding shows its Evidence Level: how the claim is known. Where we",
        "couldn't check something, the map says so and says why — an unknown",
        "is never presented as reassurance.",
        "",
        f"Assessed at {capability_map.assessed_at.isoformat()}.",
        "",
    ]
    for job in capability_map.jobs:
        lines.extend(_render_job(job))
    lines.extend(
        [
            "---",
            "",
            "If anything above is wrong, you can correct it: a correction to",
            "supporting evidence is recorded as your own account (its Evidence",
            "Level is reported, never silently raised), and a corrected job",
            "definition returns to Inspection for you to confirm afresh.",
            "",
        ]
    )
    return "\n".join(lines)
