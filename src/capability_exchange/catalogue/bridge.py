"""Local ranked shelf and portable brief rendering for catalogue v2.

This module consumes only already-verified catalogue data and the existing
Lens Capability Map. It does not fetch, transmit, subscribe, enroll, or apply
anything; the output is local guidance for the person's own AI system.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from capability_exchange.capmap.model import CapabilityMap
from capability_exchange.catalogue.v2 import (
    CapabilityCompatibilityV2,
    CatalogueCapabilityEntryV2,
    CatalogueV2,
    capability_availability_of,
    capability_class_fact_lines,
    capability_class_of,
    capability_is_active,
)
from capability_exchange.diagnosis.finding import CapabilityState, Finding
from capability_exchange.evidence import EvidenceLevel
from capability_exchange.jobs.contract import JobCadence, JobImportance

__all__ = [
    "RankedCapabilityMatch",
    "rank_capability_shelf",
    "render_portable_brief_markdown",
]


_EVIDENCE_SCORE: MappingProxyType[str, int] = MappingProxyType(
    {"verified": 15, "supported": 10, "reported": 5, "unknown": 0}
)
_EVIDENCE_RANK: MappingProxyType[str, int] = MappingProxyType(
    {"verified": 3, "supported": 2, "reported": 1, "unknown": 0}
)
_EVIDENCE_LANGUAGE: MappingProxyType[str, str] = MappingProxyType(
    {
        "verified": "verified - direct Dex evidence",
        "supported": "supported - Dex-supplied material",
        "reported": "reported - Dex team's account",
        "unknown": "unknown - not established either way",
    }
)
# The publisher's reviewed impact tier nudges ordering. It is deliberately
# smaller than every evidence, host, and gap term so a tier can break ties
# but can never substitute for evidence and compatibility checks.
_IMPACT_TIER_SCORE: MappingProxyType[str, int] = MappingProxyType(
    {"core": 8, "high": 6, "medium": 3, "niche": 1}
)
_GAP_SCORE: MappingProxyType[CapabilityState, int] = MappingProxyType(
    {
        CapabilityState.NOT_DEMONSTRATED: 50,
        CapabilityState.UNKNOWN: 40,
        CapabilityState.PARTIAL: 30,
        CapabilityState.WORKING: 5,
    }
)
_STATE_LANGUAGE: MappingProxyType[CapabilityState, str] = MappingProxyType(
    {
        CapabilityState.WORKING: "working",
        CapabilityState.PARTIAL: "partial",
        CapabilityState.NOT_DEMONSTRATED: "not demonstrated",
        CapabilityState.UNKNOWN: "unknown",
    }
)


@dataclass(frozen=True, slots=True)
class RankedCapabilityMatch:
    """One Dex catalogue entry ranked against the person's local diagnosis."""

    capability_id: str
    title: str
    score: int
    shelf_section: Literal["picked", "browse"]
    matched_job_ids: tuple[str, ...]
    matched_foundation_capabilities: tuple[str, ...]
    match_explanation: str
    gap_explanation: str
    evidence_explanation: str
    compatibility_explanation: str
    # Class fields survive ranking so a consumer can render an MCP server,
    # automation, or engine as what it is, and so a dormant or parked entry
    # is never mistaken for an available recommendation. Defaults keep the
    # legacy skill-only shape constructible unchanged.
    capability_class: str = "active-skill"
    availability: str = "active"


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    parts = value.split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _contract_allows(
    compatibility: CapabilityCompatibilityV2, lens_contract_version: str
) -> bool:
    current = _parse_semver(lens_contract_version)
    minimum = _parse_semver(compatibility.minimum_lens_contract)
    if current is None or minimum is None:
        return False
    return current >= minimum


def _max_catalogue_evidence_level(entry: CatalogueCapabilityEntryV2) -> str:
    return max((item.level for item in entry.evidence), key=lambda level: _EVIDENCE_RANK[level])


def _job_ids(capability_map: CapabilityMap) -> frozenset[str]:
    return frozenset(job.job_id for job in capability_map.jobs)


def _jobs_by_id(capability_map: CapabilityMap):
    return {job.job_id: job.contract for job in capability_map.jobs}


def _findings_by_foundation(capability_map: CapabilityMap) -> dict[str, list[Finding]]:
    findings: dict[str, list[Finding]] = {}
    for job in capability_map.jobs:
        for finding in job.findings:
            findings.setdefault(finding.capability.value, []).append(finding)
    return findings


def _best_gap(findings: Iterable[Finding]) -> Finding | None:
    ordered = sorted(
        findings,
        key=lambda finding: (
            _GAP_SCORE[finding.capability_state],
            finding.evidence_level.rank(),
            finding.job_id,
            finding.capability.value,
        ),
        reverse=True,
    )
    return ordered[0] if ordered else None


def _is_gap_or_weak_evidence(finding: Finding) -> bool:
    return (
        finding.capability_state != CapabilityState.WORKING
        or finding.evidence_level != EvidenceLevel.VERIFIED
    )


def _join_or_none(values: Sequence[str], *, empty: str) -> str:
    return ", ".join(values) if values else empty


def _safe_markdown(value: str) -> str:
    escaped = html.escape(value, quote=False)
    return escaped.replace("```", "` ` `")


def _importance_score(importance: JobImportance) -> int:
    return {
        JobImportance.HIGH: 30,
        JobImportance.MEDIUM: 15,
        JobImportance.LOW: 5,
    }[importance]


def _cadence_score(cadence: JobCadence) -> int:
    return {
        JobCadence.DAILY: 25,
        JobCadence.WEEKLY: 20,
        JobCadence.MONTHLY: 12,
        JobCadence.ON_DEMAND: 10,
        JobCadence.IRREGULAR: 5,
    }[cadence]


def rank_capability_shelf(
    catalogue: CatalogueV2,
    capability_map: CapabilityMap,
    *,
    host_adapter: str,
    lens_contract_version: str,
) -> tuple[RankedCapabilityMatch, ...]:
    """Rank every verified catalogue entry against the local Capability Map.

    The shelf is intentionally uncapped: if the catalogue contains 300 entries,
    this function returns 300 matches in deterministic rank order.
    """
    confirmed_job_ids = _job_ids(capability_map)
    jobs_by_id = _jobs_by_id(capability_map)
    findings_by_foundation = _findings_by_foundation(capability_map)
    matches: list[RankedCapabilityMatch] = []

    for entry in catalogue.capabilities:
        exact_catalogue_job_matches = tuple(
            job_id for job_id in entry.jobs if job_id in confirmed_job_ids
        )
        # Host compatibility, contract floors, and foundation matching are
        # skill facts: only the legacy and enriched skill shapes carry a
        # compatibility block. The other classes rank on their common fields
        # and are rendered through their own facts below.
        compatibility = getattr(entry, "compatibility", None)
        matched_foundations = tuple(
            foundation
            for foundation in (
                compatibility.foundation_capabilities if compatibility is not None else ()
            )
            if foundation in findings_by_foundation
        )
        matching_findings = tuple(
            finding
            for foundation in matched_foundations
            for finding in findings_by_foundation[foundation]
            if _is_gap_or_weak_evidence(finding)
        )
        matched_jobs = tuple(sorted({finding.job_id for finding in matching_findings}))
        best_gap = _best_gap(
            matching_findings
        )
        host_ok = compatibility is not None and host_adapter in compatibility.host_adapters
        contract_ok = compatibility is not None and _contract_allows(
            compatibility, lens_contract_version
        )
        evidence_level = _max_catalogue_evidence_level(entry)
        is_active = capability_is_active(entry)
        # A dormant or parked capability validates and may be shown as a fact
        # about Dex, but it is never offered as an active match, however well
        # it scores.
        section: Literal["picked", "browse"] = (
            "picked" if matched_jobs and is_active else "browse"
        )
        job_weight = sum(
            _importance_score(jobs_by_id[job_id].importance)
            + _cadence_score(jobs_by_id[job_id].cadence)
            for job_id in matched_jobs
        )

        score = (
            (100 * len(matched_jobs))
            + job_weight
            + (20 * len(exact_catalogue_job_matches))
            + (25 if host_ok else 0)
            + (10 if contract_ok else 0)
            + _EVIDENCE_SCORE[evidence_level]
            + (_GAP_SCORE[best_gap.capability_state] if best_gap else 0)
            # The publisher's reviewed tier orders what is shown; it never
            # replaces the evidence and compatibility terms above.
            + _IMPACT_TIER_SCORE.get(getattr(entry, "impact_tier", None) or "", 0)
        )

        if matched_jobs:
            match_detail = (
                "a matched foundation capability is weak or gappy for "
                + _join_or_none(matched_jobs, empty="none")
                + "; matched foundation "
                + _join_or_none(matched_foundations, empty="none")
            )
            if exact_catalogue_job_matches:
                match_detail += (
                    "; exact catalogue job bonus "
                    + _join_or_none(exact_catalogue_job_matches, empty="none")
                )
        else:
            match_detail = (
                "no weak or gappy confirmed job shares a foundation; "
                "matched foundation "
                + _join_or_none(matched_foundations, empty="none")
            )
        if not is_active:
            # The availability wording replaces the picked/browse framing:
            # an explanation must never say "never offered as an active
            # match" and "picked because" in the same breath.
            match_explanation = (
                f"browse only - Dex lists this capability as "
                f"{capability_availability_of(entry)}, so it is never offered as "
                "an active match; " + match_detail
            )
        elif matched_jobs:
            match_explanation = "picked because " + match_detail
        else:
            match_explanation = "browse only - " + match_detail
        if best_gap is None:
            gap_explanation = "no matching diagnosis gap was found for this capability"
        else:
            gap_explanation = (
                f"{best_gap.capability.value} is "
                f"{_STATE_LANGUAGE[best_gap.capability_state]} for "
                f"{best_gap.job_id}; evidence level {best_gap.evidence_level.value}"
            )
        if compatibility is not None:
            compatibility_explanation = (
                f"host adapter {host_adapter} "
                f"{'is listed' if host_ok else 'is not listed'}; Lens contract "
                f"{lens_contract_version} "
                f"{'meets' if contract_ok else 'does not meet'} minimum "
                f"{compatibility.minimum_lens_contract}"
            )
        else:
            # A non-skill has no host compatibility block: it is adopted by
            # running Dex, and what Lens can honestly say about it is its
            # own published facts.
            facts = " ".join(capability_class_fact_lines(entry))
            compatibility_explanation = (
                "no host compatibility declaration: this is not a skill and is "
                "adopted by running Dex, not installed into this host. " + facts
            ).rstrip()
        matches.append(
            RankedCapabilityMatch(
                capability_id=entry.capability_id,
                title=entry.title,
                score=score,
                shelf_section=section,
                matched_job_ids=matched_jobs,
                matched_foundation_capabilities=matched_foundations,
                match_explanation=match_explanation,
                gap_explanation=gap_explanation,
                evidence_explanation=(
                    f"{_EVIDENCE_LANGUAGE[evidence_level]}: "
                    f"{entry.evidence[0].summary} Limitations: {entry.evidence[0].limitations}"
                ),
                compatibility_explanation=compatibility_explanation,
                capability_class=capability_class_of(entry),
                availability=capability_availability_of(entry),
            )
        )

    return tuple(
        sorted(
            matches,
            key=lambda match: (
                match.shelf_section != "picked",
                -match.score,
                match.title.casefold(),
                match.capability_id,
            ),
        )
    )


def _capability_by_id(catalogue: CatalogueV2, capability_id: str) -> CatalogueCapabilityEntryV2:
    for capability in catalogue.capabilities:
        if capability.capability_id == capability_id:
            return capability
    raise KeyError(f"catalogue has no capability {capability_id!r}")


def _match_by_id(
    shelf: Sequence[RankedCapabilityMatch], capability_id: str
) -> RankedCapabilityMatch:
    for match in shelf:
        if match.capability_id == capability_id:
            return match
    raise KeyError(f"ranked shelf has no capability {capability_id!r}")


def render_portable_brief_markdown(
    catalogue: CatalogueV2,
    capability_map: CapabilityMap,
    shelf: Sequence[RankedCapabilityMatch],
    *,
    selected_capability_id: str,
    selected_job_id: str,
) -> str:
    """Render a safe Markdown brief for the person's own AI system.

    Catalogue prose is escaped for Markdown/HTML display, and every brief
    repeats the local-only boundary so the text cannot be mistaken for
    permission to mutate the person's system.
    """
    capability = _capability_by_id(catalogue, selected_capability_id)
    match = _match_by_id(shelf, selected_capability_id)
    job = capability_map.job(selected_job_id).contract
    brief = getattr(capability, "portable_brief", None)
    if brief is None:
        # Only a skill carries a portable rebuild brief. For an MCP server,
        # an automation, or a system engine the honest brief states what the
        # entry is and what Dex publishes about it, never fabricated steps.
        lines = [
            f"# Not a rebuildable skill: {_safe_markdown(capability.title)}",
            "",
            f"Audience: {catalogue.portable_brief.audience}",
            f"Safety boundary: {_safe_markdown(catalogue.portable_brief.safety_boundary)}",
            "",
            (
                "This is guidance only. It does not grant permission to read, write, "
                "send, or install anything."
            ),
            "",
            f"This Dex capability is a **{capability_class_of(capability)}**"
            f" (availability: {capability_availability_of(capability)}), so it has "
            "no portable rebuild brief: it is adopted by running Dex, not "
            "recreated from a description in another system.",
            "",
            "## What Dex publishes about it",
            "",
        ]
        lines.extend(
            f"- {_safe_markdown(fact)}" for fact in capability_class_fact_lines(capability)
        )
        lines.extend(
            [
                "",
                "## Capability Summary",
                "",
                f"> {_safe_markdown(capability.summary)}",
                "",
                "Do not treat this brief as proof the capability is live in this system.",
                "Do not send private material to Dex from this brief.",
                "",
            ]
        )
        return "\n".join(lines)
    lines = [
        f"# Portable Brief: {_safe_markdown(capability.title)}",
        "",
        f"Audience: {catalogue.portable_brief.audience}",
        f"Safety boundary: {_safe_markdown(catalogue.portable_brief.safety_boundary)}",
        "",
        (
            "This is guidance only. It does not grant permission to read, write, "
            "send, or install anything."
        ),
        "",
    ]
    availability = capability_availability_of(capability)
    if availability != "active":
        # A dormant skill still validates and its pattern is real, but this
        # renderer feeds the concierge journey for any shelf selection, so
        # the brief must carry the same not-on-offer framing the agent brief
        # does — never read as an adoptable recommendation.
        lines.extend(
            [
                f"Dex lists this skill as **{availability}**: it is not currently "
                "on offer, and it must not be read as an available "
                "recommendation. The pattern below is described as history, "
                "not as a suggestion.",
                "",
            ]
        )
    lines.extend([
        f"## Selected Job: {_safe_markdown(job.job_id)}",
        "",
        f"- Situation: {_safe_markdown(job.situation)}",
        f"- Desired outcome: {_safe_markdown(job.desired_outcome)}",
        "- Success evidence: " + "; ".join(_safe_markdown(item) for item in job.success_evidence),
        "",
        "## Why This Capability Matched",
        "",
        f"- {match.match_explanation}",
        f"- {match.gap_explanation}",
        f"- {match.evidence_explanation}",
        f"- {match.compatibility_explanation}",
        "",
        "## Capability Summary",
        "",
        f"> {_safe_markdown(capability.summary)}",
        "",
        f"## Portable Pattern: {_safe_markdown(brief.goal)}",
        "",
        "### Method Outline",
    ])
    lines.extend(f"- {_safe_markdown(step)}" for step in brief.method_outline)
    lines.extend(["", "### Verification Checklist"])
    lines.extend(
        f"- {_safe_markdown(item)}"
        for item in brief.verification_checklist
    )
    lines.extend(
        [
            "",
            "### Rollback Advice",
            "",
            f"- {_safe_markdown(brief.rollback_advice)}",
            "",
            "### Safety Notes",
        ]
    )
    lines.extend(f"- {_safe_markdown(note)}" for note in brief.safety_notes)
    lines.extend(
        [
            "",
            "Do not treat this brief as proof the capability is live in this system.",
            "Do not send private material to Dex from this brief.",
            "",
        ]
    )
    return "\n".join(lines)
