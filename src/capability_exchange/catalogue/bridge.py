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
from capability_exchange.catalogue.v2 import CatalogueCapabilityEntryV2, CatalogueV2
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


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    parts = value.split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _contract_allows(entry: CatalogueCapabilityEntryV2, lens_contract_version: str) -> bool:
    current = _parse_semver(lens_contract_version)
    minimum = _parse_semver(entry.compatibility.minimum_lens_contract)
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
        matched_foundations = tuple(
            foundation
            for foundation in entry.compatibility.foundation_capabilities
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
        host_ok = host_adapter in entry.compatibility.host_adapters
        contract_ok = _contract_allows(entry, lens_contract_version)
        evidence_level = _max_catalogue_evidence_level(entry)
        section: Literal["picked", "browse"] = "picked" if matched_jobs else "browse"
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
        )

        if matched_jobs:
            match_explanation = (
                "picked because a matched foundation capability is weak or gappy for "
                + _join_or_none(matched_jobs, empty="none")
                + "; matched foundation "
                + _join_or_none(matched_foundations, empty="none")
            )
            if exact_catalogue_job_matches:
                match_explanation += (
                    "; exact catalogue job bonus "
                    + _join_or_none(exact_catalogue_job_matches, empty="none")
                )
        else:
            match_explanation = (
                "browse only - no weak or gappy confirmed job shares a foundation; "
                "matched foundation "
                + _join_or_none(matched_foundations, empty="none")
            )
        if best_gap is None:
            gap_explanation = "no matching diagnosis gap was found for this capability"
        else:
            gap_explanation = (
                f"{best_gap.capability.value} is "
                f"{_STATE_LANGUAGE[best_gap.capability_state]} for "
                f"{best_gap.job_id}; evidence level {best_gap.evidence_level.value}"
            )
        compatibility_explanation = (
            f"host adapter {host_adapter} "
            f"{'is listed' if host_ok else 'is not listed'}; Lens contract "
            f"{lens_contract_version} "
            f"{'meets' if contract_ok else 'does not meet'} minimum "
            f"{entry.compatibility.minimum_lens_contract}"
        )
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
        f"## Portable Pattern: {_safe_markdown(capability.portable_brief.goal)}",
        "",
        "### Method Outline",
    ]
    lines.extend(f"- {_safe_markdown(step)}" for step in capability.portable_brief.method_outline)
    lines.extend(["", "### Verification Checklist"])
    lines.extend(
        f"- {_safe_markdown(item)}"
        for item in capability.portable_brief.verification_checklist
    )
    lines.extend(
        [
            "",
            "### Rollback Advice",
            "",
            f"- {_safe_markdown(capability.portable_brief.rollback_advice)}",
            "",
            "### Adaptation Notes",
        ]
    )
    lines.extend(["", "### Safety Notes"])
    lines.extend(f"- {_safe_markdown(note)}" for note in capability.portable_brief.safety_notes)
    lines.extend(
        [
            "",
            "Do not treat this brief as proof the capability is live in this system.",
            "Do not send private material to Dex from this brief.",
            "",
        ]
    )
    return "\n".join(lines)
