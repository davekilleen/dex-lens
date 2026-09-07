"""The authorship axis through the real shipped engine surfaces.

A pure stock-Dex vault must never hear its own vendor's files praised back as
personal strengths: the strength proposal is refused at submit with a typed
error, the closed report's strengths section says plainly that nothing beyond
stock Dex cleared the bar, and the engine-owned unique-to-you list carries
exactly the authored, catalogue-unmatched items.  All fixtures are invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.diagnosis.test_real_comparer_guided_run import (
    NOW,
    RealComparerHarness,
    _bound,
)

from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    observation_id_for,
    observation_key_for,
)
from capability_exchange.diagnosis.orchestrator import PrepareDiagnosisRequest
from capability_exchange.diagnosis.run import DiagnosisStage
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposalError,
    SpecialistRole,
    mint_evidence_token,
)
from capability_exchange.diagnosis.work import AnalysisMode, WorkPacket
from capability_exchange.evidence import EvidenceItem, EvidenceState

HONEST_EMPTY_STRENGTHS = "Nothing beyond stock Dex cleared the strength bar."

_STOCK_ITEMS = (
    (ObservationKind.SKILL, "workflow-skill"),
    (ObservationKind.SKILL, "dormant-helper"),
    (ObservationKind.MCP_SERVER, "dex-work-mcp"),
    (ObservationKind.MCP_TOOL, "dex-work-mcp.create_task"),
    (ObservationKind.AUTOMATION, "dex-nightly-check"),
)
_AUTHORED_ITEMS = (
    (ObservationKind.SKILL, "weekly-ledger"),
    (ObservationKind.AUTOMATION, "morning-pulse"),
)


def _observation(kind: ObservationKind, identity: str) -> Observation:
    return Observation(
        kind=kind,
        identity=identity,
        label=identity,
        operational_state=OperationalState.IMPLEMENTED,
        evidence=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=NOW,
            reference=f"file-token:{identity}.md",
        ),
        provenance={
            "source_id": f"scope:{identity}",
            "source_class": "vault-authored",
            "scope_reference": "scope:sha256:" + "c" * 64,
            "relative_reference": f"synthetic/{identity}.md",
        },
    )


def _vault(*items: tuple[ObservationKind, str]) -> EvidenceFingerprint:
    return EvidenceFingerprint(
        adapter_id="invented-local-adapter",
        collected_at=NOW,
        observations=tuple(_observation(kind, identity) for kind, identity in items),
    )


def _citation_for(
    packet: WorkPacket,
    fingerprint: EvidenceFingerprint,
    identity: str,
) -> tuple[str, str]:
    """The engine-minted (observation_id, evidence token) for one observation."""

    observation = next(
        item for item in fingerprint.observations if item.identity == identity
    )
    token = mint_evidence_token(
        run_id=packet.run_id,
        fingerprint_digest=packet.fingerprint_digest,
        observation_key=observation_key_for(observation),
    )
    return observation_id_for(observation), token


def _strength_proposal(
    packet: WorkPacket,
    fingerprint: EvidenceFingerprint,
    identity: str,
) -> object:
    observation_id, token = _citation_for(packet, fingerprint, identity)
    return _bound(
        packet,
        kind=ProposalKind.STRENGTH,
        catalogue_id="workflow-skill",
        disposition=Disposition.STRONG_HERE,
        evidence_ids=(token,),
        observation_ids=(observation_id,),
        reason="This invented file reads impressively and closes its loop.",
    )


def _drive_guided_run(
    harness: RealComparerHarness,
    *,
    strength_citing: str | None,
    expect_refusal: bool,
) -> str:
    """Run guided analysis, steering only the strength packet's proposals."""

    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(
            roots=(harness.root,), analysis_mode=AnalysisMode.GUIDED
        )
    )
    harness.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    fingerprint = harness.collector.fingerprint
    refused_once = False
    while True:
        packet = harness.engine.work(prepared.run_id)
        if packet is None:
            break
        if (
            packet.role is SpecialistRole.STRENGTH_AND_RECIPROCAL
            and strength_citing is not None
            and not refused_once
        ):
            proposal = _strength_proposal(packet, fingerprint, strength_citing)
            if expect_refusal:
                refused_once = True
                with pytest.raises(SpecialistProposalError, match="rejected"):
                    harness.engine.submit_work(
                        prepared.run_id, packet.packet_id, (proposal,)
                    )
                # The retry is the honest empty answer.
                harness.engine.submit_work(prepared.run_id, packet.packet_id, ())
            else:
                refused_once = True
                harness.engine.submit_work(
                    prepared.run_id, packet.packet_id, (proposal,)
                )
            continue
        harness.engine.submit_work(prepared.run_id, packet.packet_id, ())
    closed = harness.run_to(prepared.run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED
    return prepared.run_id


def test_pure_stock_vault_strength_is_refused_and_report_stays_honest(
    tmp_path: Path,
) -> None:
    harness = RealComparerHarness(tmp_path, fingerprint=_vault(*_STOCK_ITEMS))
    run_id = _drive_guided_run(
        harness, strength_citing="workflow-skill", expect_refusal=True
    )

    result = harness.engine.result(run_id)
    assert result.ledger.strengths == ()
    # Nothing in a pure stock install is the person's own work.
    assert result.ledger.unique_to_you == ()
    markdown = result.render_markdown()
    assert HONEST_EMPTY_STRENGTHS in markdown


def test_mixed_strength_citing_one_authored_observation_is_accepted(
    tmp_path: Path,
) -> None:
    harness = RealComparerHarness(
        tmp_path, fingerprint=_vault(*_STOCK_ITEMS, *_AUTHORED_ITEMS)
    )
    run_id = _drive_guided_run(
        harness, strength_citing="weekly-ledger", expect_refusal=False
    )

    result = harness.engine.result(run_id)
    assert len(result.ledger.strengths) == 1
    markdown = result.render_markdown()
    assert HONEST_EMPTY_STRENGTHS not in markdown


def test_unique_to_you_is_a_typed_engine_field_on_the_closed_result(
    tmp_path: Path,
) -> None:
    fingerprint = _vault(
        *_AUTHORED_ITEMS,
        (ObservationKind.SKILL, "workflow-skill"),
        (ObservationKind.SKILL, "anthropic-pdf"),
    )
    harness = RealComparerHarness(tmp_path, fingerprint=fingerprint)
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(
            roots=(harness.root,), analysis_mode=AnalysisMode.INVENTORY_ONLY
        )
    )
    closed = harness.run_to(prepared.run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED

    result = harness.engine.result(prepared.run_id)
    expected = tuple(
        sorted(
            observation_id_for(item)
            for item in fingerprint.observations
            if item.identity in {"weekly-ledger", "morning-pulse"}
        )
    )
    assert result.ledger.unique_to_you == expected

    markdown = result.render_markdown()
    assert "## Unique to you" in markdown
    assert "weekly-ledger" in markdown
    assert "morning-pulse" in markdown
    # Harness-shipped and stock items never appear as unique-to-you.
    assert "anthropic-pdf" not in markdown.split("## Unique to you")[1].split("##")[0]
