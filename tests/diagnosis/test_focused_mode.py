"""AnalysisMode.FOCUSED: the focus receipt and family-scoped packets.

Design: docs/superpowers/plans/2026-09-07-dex-lens-10x-experience.md, item 3.
Per the completion goal every guarantee here was observed failing first on the
unchanged tree: ``AnalysisMode.FOCUSED`` did not exist, so neither did the
focus receipt, the engine-derived member slice, the per-family coverage rule,
or the close-time refusal of a silent not-assessed selected member.

The founder's fixed requirement 1 is the spine: inside a selected family every
member capability is assessed one by one — no sampling, no silent
``not-assessed``.  The engine enforces it where enforcement is real: the
family-primary packet's receipt, the compare/close gates, and the identity
slice itself, which is derived from the signed family contract and never
host-supplied.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.diagnosis.test_real_comparer_guided_run import (
    RealComparerHarness,
    _bound,
)
from tests.diagnosis.test_significant_family_assessment import (
    _catalogue,
    _family,
    _fingerprint,
    _observation,
)

from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS
from capability_exchange.diagnosis.observations import ObservationKind
from capability_exchange.diagnosis.orchestrator import PrepareDiagnosisRequest
from capability_exchange.diagnosis.run import (
    DiagnosisStage,
    DiagnosisStateError,
    FocusReceipt,
    RequiredStep,
    canonical_json_digest,
)
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposalError,
    SpecialistRole,
)
from capability_exchange.diagnosis.work import (
    FOCUS_PRIMARY_ROLES,
    NORMAL_ROLES,
    AnalysisMode,
    WorkPacket,
    focus_primary_role,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

#: Distinct member slices so a three-family selection has a real union and
#: real out-of-slice identities left over.
_MEMBERS_BY_FAMILY: dict[str, list[str]] = {
    "meeting-follow-through": ["workflow-skill", "dex-work-mcp"],
    "backup-and-restore-confidence": ["dex-nightly-check"],
    "durable-work-memory": ["workflow-skill"],
    "proactive-health-and-recovery": ["parked-engine"],
    "living-people-company-context": ["dormant-helper"],
}

SELECTED = (
    "backup-and-restore-confidence",
    "durable-work-memory",
    "meeting-follow-through",
)
UNSELECTED = tuple(sorted(set(WOW_EXPECTATIONS) - set(SELECTED)))
#: The engine-derived identity slice: the union of the selected families'
#: signed member lists, sorted.
SELECTED_MEMBER_SLICE = ("dex-nightly-check", "dex-work-mcp", "workflow-skill")
OUT_OF_SLICE_ID = "parked-engine"

_VERDICT_REASON = (
    "Assessed one by one against Dex Core; nothing here is relevant to this "
    "synthetic system."
)


def _focused_catalogue():
    families = []
    for family_id in WOW_EXPECTATIONS:
        members = _MEMBERS_BY_FAMILY.get(family_id, ["workflow-skill"])
        families.append(
            _family(
                family_id,
                profile="filesystem",
                members=members,
                components=[
                    {"component_type": "capability", "capability_id": member}
                    for member in members
                ],
            )
        )
    return _catalogue(*families)


def _focused_fingerprint():
    return _fingerprint(_observation(ObservationKind.SKILL, "workflow-skill"))


def _harness(tmp_path: Path) -> RealComparerHarness:
    return RealComparerHarness(
        tmp_path,
        catalogue=_focused_catalogue(),
        fingerprint=_focused_fingerprint(),
    )


def _prepare(harness: RealComparerHarness, mode: AnalysisMode) -> str:
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=mode)
    )
    return prepared.run_id


def _focused_run_at_family_mapped(harness: RealComparerHarness) -> str:
    run_id = _prepare(harness, AnalysisMode.FOCUSED)
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)
    return run_id


def _focused_run_at_planned(harness: RealComparerHarness) -> str:
    run_id = _focused_run_at_family_mapped(harness)
    harness.engine.focus(run_id, SELECTED)
    harness.run_to(run_id, DiagnosisStage.ANALYSIS_PLANNED)
    return run_id


def _member_verdicts(
    packet: WorkPacket, members: tuple[str, ...]
) -> tuple[object, ...]:
    """One explicit, cheap, honest verdict per member — no sampling."""

    return tuple(
        _bound(
            packet,
            kind=ProposalKind.MAPPING,
            catalogue_id=member,
            disposition=Disposition.NOT_RELEVANT,
            evidence_ids=(packet.evidence_ids[0],),
            observation_ids=(),
            reason=_VERDICT_REASON,
        )
        for member in members
    )


def _verdicts_for_packet(packet: WorkPacket) -> tuple[object, ...]:
    """Cover every member of every selected family on its primary packet."""

    assigned = tuple(
        member
        for family_id in SELECTED
        if focus_primary_role(family_id) is packet.role
        for member in _MEMBERS_BY_FAMILY.get(family_id, ["workflow-skill"])
    )
    return _member_verdicts(packet, tuple(sorted(set(assigned))))


def _submit_covering_round(harness: RealComparerHarness, run_id: str) -> None:
    for packet in harness.engine.pending_work(run_id):
        harness.engine.submit_work(
            run_id, packet.packet_id, _verdicts_for_packet(packet)
        )
    sceptical = harness.engine.pending_work(run_id)
    for packet in sceptical:
        harness.engine.submit_work(run_id, packet.packet_id, ())


def _packet_with_role(
    harness: RealComparerHarness, run_id: str, role: SpecialistRole
) -> WorkPacket:
    return next(
        packet
        for packet in harness.engine.pending_work(run_id)
        if packet.role is role
    )


def test_the_primary_role_table_is_closed_over_the_manifest() -> None:
    assert set(FOCUS_PRIMARY_ROLES) == set(WOW_EXPECTATIONS)
    assert set(FOCUS_PRIMARY_ROLES.values()) <= set(NORMAL_ROLES)
    for family_id in WOW_EXPECTATIONS:
        assert focus_primary_role(family_id) is FOCUS_PRIMARY_ROLES[family_id]


def test_focused_queue_slices_identity_to_the_selected_member_union(
    tmp_path: Path,
) -> None:
    """Every packet's capability slice equals the engine-derived member union.

    Observed failing on the unchanged tree: AnalysisMode.FOCUSED did not
    exist, so only the all-identity GUIDED queue could be issued.
    """

    harness = _harness(tmp_path)
    run_id = _focused_run_at_planned(harness)

    packets = harness.engine.pending_work(run_id)
    assert packets
    for packet in packets:
        assert packet.capability_ids == SELECTED_MEMBER_SLICE
        assert packet.catalogue_ids == SELECTED_MEMBER_SLICE
        assert OUT_OF_SLICE_ID not in packet.capability_ids


def test_a_proposal_citing_an_out_of_slice_catalogue_id_is_refused_typed(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _focused_run_at_planned(harness)
    packet = _packet_with_role(
        harness, run_id, SpecialistRole.AUTOMATIONS_AND_LIVE_STATE
    )

    out_of_slice = _member_verdicts(packet, (OUT_OF_SLICE_ID,))
    with pytest.raises(SpecialistProposalError) as caught:
        harness.engine.submit_work(run_id, packet.packet_id, out_of_slice)
    # The typed refusal names the rule and never the inspected system.
    assert "retry" in str(caught.value)


def test_guided_queue_keeps_the_full_identity_universe(tmp_path: Path) -> None:
    """GUIDED stays the untouched all-families default."""

    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.GUIDED)
    harness.run_to(run_id, DiagnosisStage.ANALYSIS_PLANNED)

    packets = harness.engine.pending_work(run_id)
    assert packets
    for packet in packets:
        assert OUT_OF_SLICE_ID in packet.capability_ids
        assert len(packet.capability_ids) == 5


def test_focus_on_a_guided_run_is_refused_typed(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id = _prepare(harness, AnalysisMode.GUIDED)
    harness.run_to(run_id, DiagnosisStage.FAMILY_MAPPED)

    with pytest.raises(DiagnosisStateError, match="focused-analysis"):
        harness.engine.focus(run_id, SELECTED)


def test_a_family_receipt_missing_one_member_verdict_is_refused_insufficient(
    tmp_path: Path,
) -> None:
    """All-but-one coverage burns the bounded attempt; the retry then lands.

    Observed failing on the unchanged tree: no per-member coverage rule
    existed, so the undercovered response was accepted as completed.
    """

    harness = _harness(tmp_path)
    run_id = _focused_run_at_planned(harness)
    packet = _packet_with_role(
        harness, run_id, SpecialistRole.PEOPLE_AND_WORK_CONTINUITY
    )

    # meeting-follow-through has two members; cover only one of them.
    undercovered = _member_verdicts(packet, ("workflow-skill",))
    with pytest.raises(SpecialistProposalError, match="one retry remains") as caught:
        harness.engine.submit_work(run_id, packet.packet_id, undercovered)
    message = str(caught.value)
    assert "dex-work-mcp" not in message  # the count, never the content

    # The retry protocol fired: the packet is still pending and a complete
    # per-member response is accepted on the second bounded attempt.
    assert packet.packet_id in {
        item.packet_id for item in harness.engine.pending_work(run_id)
    }
    harness.engine.submit_work(
        run_id, packet.packet_id, _verdicts_for_packet(packet)
    )
    assert packet.packet_id not in {
        item.packet_id for item in harness.engine.pending_work(run_id)
    }


def test_advance_refuses_a_focused_run_with_a_silent_not_assessed_member(
    tmp_path: Path,
) -> None:
    """A selected-family member with no verdict blocks compare/close, typed.

    Observed failing on the unchanged tree: close had no per-selection
    coverage rule, so the run closed with the silent hole.
    """

    harness = _harness(tmp_path)
    run_id = _focused_run_at_planned(harness)

    for packet in harness.engine.pending_work(run_id):
        if packet.role is SpecialistRole.PEOPLE_AND_WORK_CONTINUITY:
            # Burn both bounded attempts under-covered: the packet ends
            # unresolved and dex-work-mcp never receives a verdict.
            for _attempt in range(2):
                with pytest.raises(SpecialistProposalError):
                    harness.engine.submit_work(
                        run_id,
                        packet.packet_id,
                        _member_verdicts(packet, ("workflow-skill",)),
                    )
        else:
            harness.engine.submit_work(
                run_id, packet.packet_id, _verdicts_for_packet(packet)
            )
    for packet in harness.engine.pending_work(run_id):
        harness.engine.submit_work(run_id, packet.packet_id, ())

    completed = harness.engine.advance(run_id)
    assert completed.stage is DiagnosisStage.ANALYSIS_COMPLETED

    with pytest.raises(DiagnosisStateError) as caught:
        harness.engine.advance(run_id)
    message = str(caught.value)
    assert "1" in message  # exactly one member is silently not-assessed
    assert "not-assessed" in message
    assert "dex-work-mcp" not in message  # the count, never the content


def test_unselected_family_members_are_not_demanded_and_the_run_closes(
    tmp_path: Path,
) -> None:
    """Coverage binds only the selection; the rest stays loudly not-assessed."""

    harness = _harness(tmp_path)
    run_id = _focused_run_at_planned(harness)
    _submit_covering_round(harness, run_id)

    closed = harness.run_to(run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED

    ledger = harness.engine.result(run_id).ledger
    entries = {item.catalogue_id: item for item in ledger.entries}
    for member in SELECTED_MEMBER_SLICE:
        assert entries[member].disposition is Disposition.NOT_RELEVANT
    # Unselected families' members were never demanded and stay honest.
    assert entries[OUT_OF_SLICE_ID].disposition is Disposition.NOT_ASSESSED
    assert entries["dormant-helper"].disposition is Disposition.NOT_ASSESSED


def test_focus_receipt_appears_in_status_and_survives_reopen(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _focused_run_at_family_mapped(harness)

    view = harness.engine.focus(run_id, SELECTED)
    assert view.focus is not None
    assert view.focus.selected_family_ids == SELECTED
    assert view.focus.unselected_family_ids == UNSELECTED

    harness.reopen()
    status = harness.engine.status(run_id)
    assert status.focus is not None
    assert status.focus.selected_family_ids == SELECTED
    assert status.focus.unselected_family_ids == UNSELECTED

    # An identical replay is a no-op; a different selection fails closed.
    harness.engine.focus(run_id, SELECTED)
    with pytest.raises(DiagnosisStateError, match="focus"):
        harness.engine.focus(run_id, SELECTED[:1])


def test_confirm_jobs_requires_the_focus_receipt_on_a_focused_run(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id = _focused_run_at_family_mapped(harness)

    with pytest.raises(DiagnosisStateError) as caught:
        harness.engine.advance(run_id)
    assert caught.value.required_step is RequiredStep.CONFIRM_FOCUS

    # Focus is only lawful in the window the family map opens.
    early = _prepare(harness, AnalysisMode.FOCUSED)
    harness.run_to(early, DiagnosisStage.CAPTURED)
    with pytest.raises(DiagnosisStateError):
        harness.engine.focus(early, SELECTED)


def test_a_tampered_focus_receipt_is_refused_typed(tmp_path: Path) -> None:
    """A stored receipt that no longer matches this run's family map fails
    closed on every surface that would consume it."""

    harness = _harness(tmp_path)
    run_id = _focused_run_at_family_mapped(harness)
    harness.engine.focus(run_id, SELECTED)

    stale_map_digest = "sha256:" + "0" * 64
    forged = FocusReceipt(
        run_id=run_id,
        family_map_digest=stale_map_digest,
        selected_family_ids=SELECTED,
        unselected_family_ids=UNSELECTED,
        focus_digest=canonical_json_digest(
            {
                "family_map_digest": stale_map_digest,
                "run_id": run_id,
                "selected_family_ids": list(SELECTED),
                "unselected_family_ids": list(UNSELECTED),
            }
        ),
        confirmed_at=NOW,
    )
    checkpoint = harness.run_store.load(run_id)
    digest = harness.engine._put("focus-receipt", forged.dump_for_storage())  # noqa: SLF001
    harness.run_store.save(
        checkpoint.model_copy(
            update={"artifact_digests": (*checkpoint.artifact_digests, digest)}
        )
    )

    with pytest.raises(DiagnosisStateError, match="focus receipt"):
        harness.engine.advance(run_id)
    # Status reports proved progress without crashing on the tampered record.
    assert harness.engine.status(run_id).focus is None


def test_a_swapped_selection_after_planning_refuses_the_stored_queue(
    tmp_path: Path,
) -> None:
    """The slice is recomputed on load: a receipt swapped for a different
    (internally valid) selection makes the stored queue refuse to resume."""

    harness = _harness(tmp_path)
    run_id = _focused_run_at_planned(harness)
    map_digest = canonical_json_digest(
        harness.engine.family_map(run_id).model_dump(mode="json")
    )

    swapped_selected = ("backup-and-restore-confidence",)
    swapped_unselected = tuple(
        sorted(set(WOW_EXPECTATIONS) - set(swapped_selected))
    )
    forged = FocusReceipt(
        run_id=run_id,
        family_map_digest=map_digest,
        selected_family_ids=swapped_selected,
        unselected_family_ids=swapped_unselected,
        focus_digest=canonical_json_digest(
            {
                "family_map_digest": map_digest,
                "run_id": run_id,
                "selected_family_ids": list(swapped_selected),
                "unselected_family_ids": list(swapped_unselected),
            }
        ),
        confirmed_at=NOW,
    )
    checkpoint = harness.run_store.load(run_id)
    digest = harness.engine._put("focus-receipt", forged.dump_for_storage())  # noqa: SLF001
    harness.run_store.save(
        checkpoint.model_copy(
            update={"artifact_digests": (*checkpoint.artifact_digests, digest)}
        )
    )

    with pytest.raises(DiagnosisStateError, match="stored specialist work queue"):
        harness.engine.pending_work(run_id)


def test_the_selection_reaches_the_ledger_and_the_decisions_section(
    tmp_path: Path,
) -> None:
    """Selected and explicitly-not-selected families survive to the report
    inputs, so design item 10's memory work has its record."""

    harness = _harness(tmp_path)
    run_id = _focused_run_at_planned(harness)
    _submit_covering_round(harness, run_id)
    harness.run_to(run_id, DiagnosisStage.CLOSED)

    result = harness.engine.result(run_id)
    assert result.ledger.focus_selected_family_ids == SELECTED
    assert result.ledger.focus_unselected_family_ids == UNSELECTED

    markdown = result.render_markdown()
    decisions = markdown.split("## What you decided", 1)[1]
    for family_id in SELECTED:
        assert family_id in decisions
    for family_id in UNSELECTED:
        assert family_id in decisions


def test_shipped_cli_focus_command_records_the_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from capability_exchange.diagnosis import cli

    harness = _harness(tmp_path)
    run_id = _focused_run_at_family_mapped(harness)
    monkeypatch.setattr(cli, "build_engine", lambda: harness.engine)

    arguments = ["focus", "--run", run_id]
    for family_id in SELECTED:
        arguments.extend(["--family", family_id])
    assert cli.diagnosis_main(arguments) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["focus"]["selected_family_ids"] == list(SELECTED)

    assert cli.diagnosis_main(["status", "--run", run_id, "--json"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["focus"]["selected_family_ids"] == list(SELECTED)
    assert status_payload["focus"]["unselected_family_ids"] == list(UNSELECTED)
