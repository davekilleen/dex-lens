"""Persona C: the non-lineage classification and the signed job axis.

Design: docs/superpowers/plans/2026-09-07-dex-lens-10x-experience.md, item 7
and section 4.  Per the completion goal every guarantee here was observed
failing first on the unchanged tree (commit 6051784): the non-lineage
threshold, the map's job rows, ``ProposalKind.JOB_COVERAGE``, the job-keyed
focus flow, the ledger job axis, and the ``reports check`` loan-framing rule
did not exist, so the fixture below rendered fourteen UNRESOLVED family rows
and nothing refused a "behind Dex" claim.

The honest product for someone who never installed Dex: when identity matching
yields nothing, the comparison happens on the signed JOB axis — kind-admitted
evidence or a loud priced Unknown per signed job, specialist verdicts only
through validated job-coverage proposals — and the report's framing is a loan,
never a delta.  No fuzzy name matcher anywhere: "embedding similarity is a
plausible guess wearing evidence's clothes" (the design's own words).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.diagnosis.test_real_comparer_guided_run import RealComparerHarness
from tests.diagnosis.test_significant_family_assessment import (
    _automation,
    _fingerprint,
    _job,
    _mcp,
    _observation,
    _parked_engine,
    _skill,
)
from tests.diagnosis.test_significant_family_assessment import (
    _family as _family_dict,
)

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.expectations import (
    NON_LINEAGE_FAMILY_ROW_REASON,
    WOW_EXPECTATIONS,
    build_family_map,
)
from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.diagnosis.orchestrator import PrepareDiagnosisRequest
from capability_exchange.diagnosis.report import (
    canonical_job_axis_block,
    job_axis_errors,
)
from capability_exchange.diagnosis.run import (
    DiagnosisStage,
    DiagnosisStateError,
    JobAxisState,
)
from capability_exchange.diagnosis.significant_families import (
    JOB_OBSERVATION_RULES,
    assess_job_axis,
    is_non_lineage,
)
from capability_exchange.diagnosis.specialists import (
    ProposalContext,
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    validate_proposal,
)
from capability_exchange.diagnosis.work import (
    FOCUS_JOB_PRIMARY_ROLES,
    NORMAL_ROLES,
    AnalysisMode,
    WorkPacket,
    focus_job_primary_role,
)

#: The eight signed jobs the live catalogue organises itself around.
SIGNED_JOBS: tuple[tuple[str, str], ...] = (
    ("capture-without-friction", "Capture Without Friction"),
    ("start-each-day-focused", "Start Each Day Focused"),
    ("track-people-and-relationships", "Track People & Relationships"),
    ("manage-tasks-reliably", "Manage Tasks Reliably"),
    ("reflect-and-improve-continuously", "Reflect & Improve Continuously"),
    ("keep-projects-on-track", "Keep Projects On Track"),
    ("track-career-growth", "Track Career Growth"),
    ("evolve-the-system-itself", "Evolve the System Itself"),
)

_JOBS_BY_CAPABILITY = {
    "workflow-skill": ["manage-tasks-reliably"],
    "dormant-helper": ["track-career-growth"],
    "dex-work-mcp": ["manage-tasks-reliably"],
    "dex-nightly-check": ["evolve-the-system-itself"],
    "parked-engine": ["evolve-the-system-itself"],
}

SELECTED_JOBS = ("evolve-the-system-itself", "start-each-day-focused")
#: Capabilities serving the selected jobs — the engine-derived job-keyed slice.
SELECTED_JOB_SLICE = ("dex-nightly-check", "parked-engine")


def _eight_job_catalogue() -> CatalogueV2:
    jobs = [
        {
            "job_id": job_id,
            "label": label,
            "description": f"Signed job fixture: {label}.",
            "confirmed_gap_signals": [f"{job_id} repeatedly fails"],
        }
        for job_id, label in SIGNED_JOBS
    ]
    # The shared capability helpers reference the synthetic taxonomy job, so
    # keep it signed too: the taxonomy is what the engine renders, and this
    # fixture proves the axis follows the signed list, not a hardcoded eight.
    jobs.append(_job())
    capabilities = [
        _skill("workflow-skill"),
        _skill("dormant-helper", availability="dormant"),
        _mcp(),
        _automation(),
        _parked_engine(),
    ]
    for entry in capabilities:
        entry["jobs"] = _JOBS_BY_CAPABILITY[entry["capability_id"]]
    families = [
        _family_dict(
            family_id,
            profile="filesystem",
            members=["workflow-skill"],
            components=[
                {"component_type": "capability", "capability_id": "workflow-skill"}
            ],
        )
        for family_id in WOW_EXPECTATIONS
    ]
    for family in families:
        family["jobs"] = ["manage-tasks-reliably"]
    return CatalogueV2.model_validate(
        {
            "jobs_taxonomy": jobs,
            "capabilities": capabilities,
            "capability_aliases": [
                {"alias": "work-mcp", "capability_id": "dex-work-mcp"},
                {"alias": "workflow-alias", "capability_id": "workflow-skill"},
            ],
            "capability_families": families,
            "portable_brief": {
                "format": "markdown",
                "audience": "the person's own AI system",
                "safety_boundary": "guidance only; it changes nothing",
            },
        }
    )


ALL_SIGNED_JOB_IDS = tuple(job_id for job_id, _label in SIGNED_JOBS) + (
    "keep-work-moving",
)


def _g_brain_fingerprint():
    """A personal operating system Dex was never installed on.

    No release record of Dex's, whatever capability names happen to coincide.
    """

    return _fingerprint(
        _observation(ObservationKind.SKILL, "g-brain-daily"),
        _observation(ObservationKind.AUTOMATION, "com.gbrain.morning-brief"),
        _observation(ObservationKind.HEALTH_CHECK, "gbrain-doctor"),
        _observation(ObservationKind.HOOK, "gbrain-capture-hook"),
        dex_installed=False,
    )


def _lineage_fingerprint():
    """A system Dex is genuinely installed on.

    Dex's own release record is what makes this a Dex install. This fixture
    used to stand in for one with nothing but a skill whose name matched a
    signed capability id — the fixture encoding the very inversion F8 records,
    which is how it went unnoticed for so long. The colliding name stays,
    because a real install has both and the two must not be confused.
    """

    return _fingerprint(
        _observation(ObservationKind.RELEASE, "dex-core"),
        _observation(ObservationKind.SKILL, "workflow-skill"),
        dex_installed=False,
    )


def _harness(tmp_path: Path, *, lineage: bool = False) -> RealComparerHarness:
    return RealComparerHarness(
        tmp_path,
        catalogue=_eight_job_catalogue(),
        fingerprint=_lineage_fingerprint() if lineage else _g_brain_fingerprint(),
    )


def _prepare(harness: RealComparerHarness, mode: AnalysisMode) -> str:
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=mode)
    )
    return prepared.run_id


def _job_proposal(
    packet: WorkPacket,
    *,
    job_id: str,
    job_coverage: JobAxisState,
    evidence_ids: tuple[str, ...],
    reason: str,
) -> SpecialistProposal:
    from capability_exchange.diagnosis.specialists import candidate_id_for

    return SpecialistProposal(
        role=packet.role,
        kind=ProposalKind.JOB_COVERAGE,
        run_id=packet.run_id,
        fingerprint_digest=packet.fingerprint_digest,
        catalogue_digest=packet.catalogue_digest,
        packet_id=packet.packet_id,
        packet_digest=packet.packet_digest,
        catalogue_id=job_id,
        capability_id=job_id,
        candidate_id=candidate_id_for(ProposalKind.JOB_COVERAGE, job_id, job_id),
        disposition=Disposition.NOT_ASSESSED,
        job_coverage=job_coverage,
        evidence_ids=evidence_ids,
        observation_ids=(),
        reason=reason,
    )


def _verdict_for_packet(
    packet: WorkPacket,
) -> tuple[SpecialistProposal, ...]:
    assigned = tuple(
        job_id
        for job_id in SELECTED_JOBS
        if focus_job_primary_role(job_id) is packet.role
    )
    verdicts = {
        "evolve-the-system-itself": (
            JobAxisState.SERVES,
            "A health check runs and writes proof; the cited evidence is the file.",
        ),
        "start-each-day-focused": (
            JobAxisState.DOES_NOT_SERVE,
            "The whole snapshot was searched; no morning routine exists — the "
            "cited evidence is the search.",
        ),
    }
    return tuple(
        _job_proposal(
            packet,
            job_id=job_id,
            job_coverage=verdicts[job_id][0],
            evidence_ids=(packet.evidence_ids[0],),
            reason=verdicts[job_id][1],
        )
        for job_id in assigned
    )


def _run_focused_to_planned(harness: RealComparerHarness) -> str:
    run_id = _prepare(harness, AnalysisMode.FOCUSED)
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)
    harness.engine.focus(run_id, SELECTED_JOBS)
    harness.run_to(run_id, DiagnosisStage.ANALYSIS_PLANNED)
    return run_id


def _submit_covering_round(harness: RealComparerHarness, run_id: str) -> None:
    for packet in harness.engine.pending_work(run_id):
        harness.engine.submit_work(run_id, packet.packet_id, _verdict_for_packet(packet))
    for packet in harness.engine.pending_work(run_id):
        harness.engine.submit_work(run_id, packet.packet_id, ())


# ---------------------------------------------------------------------------
# The deterministic threshold and the pass-1 job axis (design item 7 red test).
# ---------------------------------------------------------------------------


def test_zero_identity_match_map_renders_every_signed_job_row(tmp_path: Path) -> None:
    """The red test the design names: the map renders the signed job rows,
    each with admitted-kind evidence or a loud Unknown, instead of a wall of
    UNRESOLVED family rows.  Observed failing on the unchanged tree: FamilyMap
    had no ``non_lineage`` or ``job_rows`` fields at all."""

    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.GUIDED)
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)

    family_map = harness.engine.family_map(run_id)
    assert family_map.non_lineage is True
    assert family_map.inspected_release is None
    assert tuple(row.job_id for row in family_map.job_rows) == ALL_SIGNED_JOB_IDS
    for row in family_map.job_rows:
        assert row.reason
        if row.state is JobAxisState.SUPPORTED:
            assert row.evidence_references
        else:
            assert row.state is JobAxisState.UNKNOWN
            assert "could not tell" in row.reason
    # The admitted-kind rules did their work: the fixture's automation,
    # health-check, and hook observations each support their signed job.
    states = {row.job_id: row.state for row in family_map.job_rows}
    assert states["start-each-day-focused"] is JobAxisState.SUPPORTED
    assert states["evolve-the-system-itself"] is JobAxisState.SUPPORTED
    assert states["capture-without-friction"] is JobAxisState.SUPPORTED
    assert states["manage-tasks-reliably"] is JobAxisState.UNKNOWN
    # Every family row still exists (the equality gates hold) with the fixed
    # honest sentence — never a silent skip, never a wall of blame.
    assert tuple(row.family_id for row in family_map.rows) == WOW_EXPECTATIONS
    assert all(row.reason == NON_LINEAGE_FAMILY_ROW_REASON for row in family_map.rows)


def test_the_threshold_is_defeated_by_dex_s_own_release_record(tmp_path: Path) -> None:
    """Lineage runs keep the family axis, on evidence that Dex is installed.

    Renamed and re-aimed: this asserted that one signed-identity match of any
    kind defeated the threshold, which is the inversion AGENTS.md F8 records.
    A name collision is not evidence of Dex; Dex's release record is.
    """

    harness = _harness(tmp_path, lineage=True)
    run_id = _prepare(harness, AnalysisMode.GUIDED)
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)

    family_map = harness.engine.family_map(run_id)
    assert family_map.non_lineage is False
    assert family_map.job_rows == ()
    assert all(row.reason != NON_LINEAGE_FAMILY_ROW_REASON for row in family_map.rows)


def test_the_threshold_and_job_axis_are_pure_and_deterministic() -> None:
    catalogue = _eight_job_catalogue()
    fingerprint = _g_brain_fingerprint()

    assert is_non_lineage(fingerprint) is True
    assert is_non_lineage(_lineage_fingerprint()) is False
    # The collision on its own is not Dex: a person who never installed it can
    # own a skill by that name, and used to be misclassified for it.
    collision_only = _fingerprint(
        _observation(ObservationKind.SKILL, "workflow-skill"),
        dex_installed=False,
    )
    assert is_non_lineage(collision_only) is True
    # A dex-core release observation alone ties the system to Dex: no version
    # diff can be honest against "not Dex", so the classification is defeated.
    release = _fingerprint(_observation(ObservationKind.RELEASE, "dex-core"),
        dex_installed=False,
    )
    assert is_non_lineage(release) is False

    first = build_family_map(
        catalogue, fingerprint, catalogue_version=7, catalogue_sha256="a" * 64
    )
    second = build_family_map(
        catalogue, fingerprint, catalogue_version=7, catalogue_sha256="a" * 64
    )
    assert first == second
    assert json.dumps(first.model_dump(mode="json"), sort_keys=True) == json.dumps(
        second.model_dump(mode="json"), sort_keys=True
    )

    rows = assess_job_axis(catalogue, fingerprint)
    assert rows == assess_job_axis(catalogue, fingerprint)
    # Kind admission only — no identity ever bridges a job row.
    assert all(
        kind.value in {"hook", "automation", "health-check", "recovery-proof"}
        for kinds in JOB_OBSERVATION_RULES.values()
        for kind in kinds
    )


# ---------------------------------------------------------------------------
# JOB_COVERAGE proposal validation (design item 7 red test: refusals).
# ---------------------------------------------------------------------------


def _unbound_context(*, job_ids: tuple[str, ...]) -> ProposalContext:
    return ProposalContext(
        run_id="run:" + "a" * 16,
        fingerprint_digest="sha256:" + "b" * 64,
        catalogue_digest="sha256:" + "c" * 64,
        evidence_ids=("evidence:sha256:" + "d" * 64,),
        catalogue_ids=("workflow-skill",),
        capability_ids=("workflow-skill",),
        job_ids=job_ids,
    )


def _unbound_job_proposal(
    *,
    job_id: str = "evolve-the-system-itself",
    evidence: str = "evidence:sha256:" + "d" * 64,
) -> SpecialistProposal:
    return SpecialistProposal(
        role=SpecialistRole.AUTOMATIONS_AND_LIVE_STATE,
        kind=ProposalKind.JOB_COVERAGE,
        run_id="run:" + "a" * 16,
        fingerprint_digest="sha256:" + "b" * 64,
        catalogue_digest="sha256:" + "c" * 64,
        catalogue_id=job_id,
        capability_id=job_id,
        disposition=Disposition.NOT_ASSESSED,
        job_coverage=JobAxisState.SERVES,
        evidence_ids=(evidence,),
        reason="A health check runs on a schedule; the cited evidence shows it.",
    )


def test_a_job_coverage_proposal_naming_an_unknown_job_is_refused() -> None:
    context = _unbound_context(job_ids=("evolve-the-system-itself",))

    with pytest.raises(SpecialistProposalError, match="signed jobs"):
        validate_proposal(
            _unbound_job_proposal(job_id="invented-job"), context
        )


def test_a_job_coverage_proposal_citing_foreign_evidence_is_refused() -> None:
    context = _unbound_context(job_ids=("evolve-the-system-itself",))

    with pytest.raises(SpecialistProposalError, match="evidence"):
        validate_proposal(
            _unbound_job_proposal(evidence="evidence:sha256:" + "e" * 64), context
        )


def test_job_coverage_is_refused_outright_on_a_lineage_run() -> None:
    """Empty context job set = not a non-lineage run: the kind is unlawful."""

    context = _unbound_context(job_ids=())

    with pytest.raises(SpecialistProposalError, match="non-lineage"):
        validate_proposal(_unbound_job_proposal(), context)


def test_the_job_coverage_wire_shape_is_closed() -> None:
    good = _unbound_job_proposal()

    # The verdict is mandatory and closed.
    with pytest.raises(ValueError, match="job_coverage"):
        good.model_copy(update={"job_coverage": None})
    with pytest.raises(ValueError, match="closed verdict"):
        good.model_copy(update={"job_coverage": JobAxisState.SUPPORTED})
    # A job id rides in both identity fields; no capability mapping hides here.
    with pytest.raises(ValueError, match="one signed job id"):
        good.model_copy(update={"capability_id": "workflow-skill"})
    # A job-coverage claim never mints a catalogue disposition.
    with pytest.raises(ValueError, match="disposition"):
        good.model_copy(update={"disposition": Disposition.WORTH_BORROWING})
    # And no other kind may smuggle the field.
    with pytest.raises(ValueError, match="only valid on job-coverage"):
        good.model_copy(
            update={"kind": ProposalKind.MAPPING, "disposition": Disposition.NOT_ASSESSED}
        )


# ---------------------------------------------------------------------------
# FOCUSED on a non-lineage run: job-keyed slices and per-job coverage.
# ---------------------------------------------------------------------------


def test_the_job_primary_role_table_is_closed_over_the_signed_jobs() -> None:
    assert set(FOCUS_JOB_PRIMARY_ROLES) == {job_id for job_id, _label in SIGNED_JOBS}
    assert set(FOCUS_JOB_PRIMARY_ROLES.values()) <= set(NORMAL_ROLES)
    # A signed job outside the fixed table falls back deterministically.
    assert focus_job_primary_role("keep-work-moving") is SpecialistRole.WORKFLOW_SYNTHESIS


def test_focus_on_a_non_lineage_run_selects_jobs_and_slices_by_job(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.FOCUSED)
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)

    # A family id is not a lawful selection on the job axis.
    with pytest.raises(DiagnosisStateError, match="job map"):
        harness.engine.focus(run_id, ("meeting-follow-through",))

    view = harness.engine.focus(run_id, SELECTED_JOBS)
    assert view.focus is not None
    assert view.focus.selected_family_ids == tuple(sorted(SELECTED_JOBS))
    assert set(view.focus.unselected_family_ids) == set(ALL_SIGNED_JOB_IDS) - set(
        SELECTED_JOBS
    )

    harness.run_to(run_id, DiagnosisStage.ANALYSIS_PLANNED)
    packets = harness.engine.pending_work(run_id)
    assert packets
    for packet in packets:
        assert packet.capability_ids == SELECTED_JOB_SLICE
        assert packet.catalogue_ids == SELECTED_JOB_SLICE


def test_a_job_packet_without_its_coverage_verdict_is_refused_then_retried(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _run_focused_to_planned(harness)
    packet = next(
        item
        for item in harness.engine.pending_work(run_id)
        if item.role is SpecialistRole.AUTOMATIONS_AND_LIVE_STATE
    )

    with pytest.raises(SpecialistProposalError, match="one retry remains") as caught:
        harness.engine.submit_work(run_id, packet.packet_id, ())
    assert "evolve-the-system-itself" not in str(caught.value)  # count, not content

    harness.engine.submit_work(run_id, packet.packet_id, _verdict_for_packet(packet))
    assert packet.packet_id not in {
        item.packet_id for item in harness.engine.pending_work(run_id)
    }


def test_compare_refuses_a_selected_job_left_without_a_verdict(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id = _run_focused_to_planned(harness)

    for packet in harness.engine.pending_work(run_id):
        if packet.role is SpecialistRole.AUTOMATIONS_AND_LIVE_STATE:
            for _attempt in range(2):
                with pytest.raises(SpecialistProposalError):
                    harness.engine.submit_work(run_id, packet.packet_id, ())
        else:
            harness.engine.submit_work(
                run_id, packet.packet_id, _verdict_for_packet(packet)
            )
    for packet in harness.engine.pending_work(run_id):
        harness.engine.submit_work(run_id, packet.packet_id, ())

    completed = harness.engine.advance(run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED

    with pytest.raises(DiagnosisStateError) as caught:
        harness.engine.advance(run_id)
    message = str(caught.value)
    assert "job-coverage" in message
    assert "1" in message


def test_a_covered_focused_job_run_closes_with_verdicts_in_the_ledger(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _run_focused_to_planned(harness)
    _submit_covering_round(harness, run_id)
    closed = harness.run_to(run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED

    ledger = harness.engine.result(run_id).ledger
    rows = {row.job_id: row for row in ledger.job_axis}
    assert tuple(sorted(rows)) == tuple(sorted(ALL_SIGNED_JOB_IDS))
    assert rows["evolve-the-system-itself"].state is JobAxisState.SERVES
    assert rows["evolve-the-system-itself"].evidence_references
    assert rows["start-each-day-focused"].state is JobAxisState.DOES_NOT_SERVE
    assert rows["start-each-day-focused"].evidence_references  # absence cites the search
    # Unselected jobs keep their deterministic pass-1 rows: supported with
    # admitted evidence, or the loud Unknown — never silence.
    assert rows["capture-without-friction"].state is JobAxisState.SUPPORTED
    assert rows["manage-tasks-reliably"].state is JobAxisState.UNKNOWN
    # The loan framing is structural: nothing delta-shaped can coexist.
    assert ledger.version_distance is None


# ---------------------------------------------------------------------------
# The report: the job-axis block and the loan-framing check.
# ---------------------------------------------------------------------------


def _closed_non_lineage_result(tmp_path: Path):
    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.INVENTORY_ONLY)
    harness.run_to(run_id, DiagnosisStage.CLOSED)
    return harness.engine.result(run_id)


def test_the_rendered_report_carries_the_job_axis_and_passes_the_check(
    tmp_path: Path,
) -> None:
    result = _closed_non_lineage_result(tmp_path)
    markdown = result.render_markdown()

    block = canonical_job_axis_block(result.ledger)
    assert block.startswith("## What your system does about Dex's jobs")
    assert block in markdown
    for job_id in ALL_SIGNED_JOB_IDS:
        assert f"`{job_id}`" in block
    assert "### Signed job coverage" in markdown  # the appendix rows exist too
    assert job_axis_errors(markdown, result.ledger) == ()


def test_a_behind_dex_claim_on_a_non_lineage_run_is_refused(tmp_path: Path) -> None:
    """The design's loan-framing rule, mechanical: 'behind Dex' has nothing to
    cite when zero identities matched.  Observed failing on the unchanged
    tree: no rule existed and the doctored report passed ``reports check``'s
    ledger gates."""

    result = _closed_non_lineage_result(tmp_path)
    markdown = result.render_markdown()

    doctored = markdown + "\nYour setup is at least 3 releases behind Dex.\n"
    errors = job_axis_errors(doctored, result.ledger)
    assert errors
    assert any("loan" in error for error in errors)

    stripped = markdown.replace(canonical_job_axis_block(result.ledger), "")
    errors = job_axis_errors(stripped, result.ledger)
    assert errors
    assert any("What your system does about Dex's jobs" in error for error in errors)


def test_lineage_reports_owe_nothing_to_the_job_axis_check(tmp_path: Path) -> None:
    harness = _harness(tmp_path, lineage=True)
    run_id = _prepare(harness, AnalysisMode.INVENTORY_ONLY)
    harness.run_to(run_id, DiagnosisStage.CLOSED)
    result = harness.engine.result(run_id)

    assert result.ledger.job_axis == ()
    markdown = result.render_markdown()
    assert "## What your system does about Dex's jobs" not in markdown
    # The rule is scoped to non-lineage ledgers: a lineage run may honestly
    # speak in release deltas, so even a delta-shaped sentence owes nothing.
    assert job_axis_errors(markdown + "\nbehind Dex\n", result.ledger) == ()


def test_two_closed_runs_over_the_same_inputs_agree_byte_for_byte(
    tmp_path: Path,
) -> None:
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    first = _closed_non_lineage_result(tmp_path / "one")
    second = _closed_non_lineage_result(tmp_path / "two")

    assert first.ledger_json() == second.ledger_json()
    assert canonical_job_axis_block(first.ledger) == canonical_job_axis_block(
        second.ledger
    )
