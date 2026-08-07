"""Rendering rules for the jobs-first Capability Map (M-D renderer).

- Jobs-first structure: findings render nested under their job, in the
  map's canonical order.
- Honest unknowns: "we couldn't check X because Y"; an Unknown is never
  dressed as a pass.
- Vocabulary compliance: the HANDOFF Section 1.5 "Avoid" terms appear
  nowhere in rendered output.
- The Evidence Level is shown for every finding (Section 1.5, binding).
- The renderer consumes Finding objects; it never re-derives them.
"""

from __future__ import annotations

import re

from tests.capmap.conftest import (
    COLLECTED_AT,
    one_job_map,
    two_job_map,
    unknown_heavy_map,
)

from capability_exchange.capmap import CAPABILITY_HEADINGS, render_capability_map
from capability_exchange.capmap.render import _evidence_line  # rendering totality
from capability_exchange.diagnosis import CapabilityState
from capability_exchange.evidence import EvidenceItem, EvidenceState

#: HANDOFF Section 1.5 "Avoid" column, in full. None of these may appear in
#: rendered output (matched case-insensitively on word boundaries, with a
#: plural allowance so "features" cannot slip past "feature").
AVOID_TERMS = (
    "primitive",
    "feature",
    "component",
    "dex baseline",
    "maturity requirement",
    "role template",
    "dex catalogue",
    "feature checklist",
    "repair scan",
    "installer",
    "automatic optimization",
    "scorecard",
    "maturity score",
    "feature inventory",
    "confidence score",
    "assumed truth",
    "universal scanner",
    "compatible system",
    "assumed support",
    "prompt collection",
    "demonstration setup",
    "main-branch scan",
    "feature list",
    "migration",
    "silent repair",
    "bulk install",
    "telemetry event",
    "system export",
    "diagnostic upload",
    "consent banner",
    "bulk sharing",
    "sync",
    "automatic feedback",
    "opt-out sharing",
    "feature commitment",
    "automatic improvement",
    # and the aggregate framing #351 forbids outright:
    "maturity",
    "resemblance",
)

#: Words that would dress an Unknown up as a pass. None may appear in the
#: rendered section of a finding whose axes are unknown/unclear.
PASS_WORDS = ("working", "verified", "safe", "pass", "healthy", "ok", "good")


def _finding_sections(rendered: str) -> list[str]:
    """The per-finding blocks of a rendered map (split on ### headings)."""
    return re.split(r"\n### ", rendered)[1:]


class TestJobsFirstStructure:
    def test_jobs_render_in_canonical_order_with_findings_nested(self) -> None:
        rendered = render_capability_map(two_job_map())
        alpha = rendered.index("## Your job: alpha-job")
        beta = rendered.index("## Your job: beta-job")
        assert alpha < beta
        # every finding heading between the two job headings belongs to alpha
        first_job_block = rendered[alpha:beta]
        for heading in CAPABILITY_HEADINGS.values():
            assert f"### {heading}" in first_job_block

    def test_the_job_renders_in_the_persons_own_terms(self) -> None:
        map_ = one_job_map()
        rendered = render_capability_map(map_)
        job = map_.jobs[0].contract
        assert job.situation in rendered
        assert job.desired_outcome in rendered
        for signal in job.success_evidence:
            assert signal in rendered

    def test_every_finding_shows_its_evidence_level(self) -> None:
        rendered = render_capability_map(two_job_map())
        sections = _finding_sections(rendered)
        assert len(sections) == 16  # eight per job, two jobs
        for section in sections:
            assert "Evidence Level (how this is known):" in section

    def test_every_finding_shows_the_full_m_d_surface(self) -> None:
        rendered = render_capability_map(one_job_map())
        for section in _finding_sections(rendered):
            assert "Evidence this rests on:" in section
            assert "Boundary for this job:" in section
            assert "What this means in practice:" in section
            assert "Why this matters to this job:" in section
            assert "One useful next move:" in section

    def test_rendering_is_deterministic(self) -> None:
        assert render_capability_map(two_job_map()) == render_capability_map(
            two_job_map()
        )


class TestHonestUnknowns:
    def test_instrument_failure_renders_as_couldnt_check_because(self) -> None:
        rendered = render_capability_map(unknown_heavy_map())
        assert "we couldn't check" in rendered
        assert "because collection was prevented" in rendered
        assert "because the check ran into failure" in rendered

    def test_an_unknown_is_never_dressed_as_a_pass(self) -> None:
        """The verdict lines of an unknown finding (its three axes and its
        evidence) never carry a reassuring word."""
        map_ = unknown_heavy_map()
        rendered = render_capability_map(map_)
        (job,) = map_.jobs
        assert all(
            finding.capability_state is CapabilityState.UNKNOWN
            for finding in job.findings
        )
        verdict_prefixes = (
            "- What the evidence showed:",
            "- Evidence Level",
            "- Boundary for this job:",
        )
        verdict_lines = [
            line.lower()
            for line in rendered.splitlines()
            if line.startswith(verdict_prefixes)
        ]
        assert verdict_lines
        for line in verdict_lines:
            for word in PASS_WORDS:
                assert not re.search(rf"\b{word}\b", line), (word, line)

    def test_unknown_level_names_itself_unknown(self) -> None:
        rendered = render_capability_map(unknown_heavy_map())
        assert "unknown — we couldn't establish this claim either way" in rendered

    def test_absent_and_not_assessed_never_read_as_passing(self) -> None:
        for state in (EvidenceState.ABSENT, EvidenceState.NOT_ASSESSED):
            line = _evidence_line(
                EvidenceItem(
                    state=state, captured_at=COLLECTED_AT, reference="probe:x"
                )
            ).lower()
            assert "supports nothing" in line or "never counted" in line
            for word in PASS_WORDS:
                assert not re.search(rf"\b{word}\b", line), (word, line)

    def test_evidence_line_wording_is_total_over_the_r2_vocabulary(self) -> None:
        for state in EvidenceState:
            line = _evidence_line(
                EvidenceItem(
                    state=state, captured_at=COLLECTED_AT, reference="probe:x"
                )
            )
            assert line  # every state has an honest, distinct wording
            assert "probe:x" in line


class TestVocabularyCompliance:
    def test_no_avoid_term_appears_in_rendered_output(self) -> None:
        for map_ in (one_job_map(), two_job_map(), unknown_heavy_map()):
            rendered = render_capability_map(map_).lower()
            for term in AVOID_TERMS:
                pattern = rf"\b{re.escape(term)}s?\b"
                assert not re.search(pattern, rendered), term

    def test_no_avoid_term_appears_in_any_evidence_state_wording(self) -> None:
        for state in EvidenceState:
            line = _evidence_line(
                EvidenceItem(
                    state=state, captured_at=COLLECTED_AT, reference="probe:x"
                )
            ).lower()
            for term in AVOID_TERMS:
                assert not re.search(rf"\b{re.escape(term)}s?\b", line), (term, line)
