"""Person-shaped and vault-shaped coverage for the ``evidence_legend``.

The legend deliberately ships observation labels and relative references out
of the CLI/MCP ``work`` surface: those fields are local-only, drawn from the
already privacy-screened fingerprint, and the host driving the diagnosis of
its own system sits in the same trust domain as the fingerprint artifact on
disk. The canary suite proved a legend cannot carry the session canary; this
file adds the two planted shapes no wire guard can detect by pattern — a
person-shaped label and a vault-shaped relative path — and states plainly
what is allowed: carrying them on the ``work`` surface is the legend's job,
and refusing them is the capture guard's job, one stage upstream.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import anyio
import pytest
from mcp import Client
from tests.evals.real_session_fixture import (
    CANARY,
    PERSON_SHAPED_NAME,
    VAULT_SHAPED_PATH,
    planted_session_fingerprint,
)
from tests.evals.test_real_session_replay import real_session_replay

from capability_exchange.diagnosis import cli as diagnosis_cli
from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.mcp_server import (
    build_mcp_server,
    canonical_work_bytes,
)
from capability_exchange.diagnosis.run import DiagnosisStage, DiagnosisStateError
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposal,
    candidate_id_for,
)
from capability_exchange.diagnosis.work import AnalysisMode
from capability_exchange.evaluation.replay import (
    ReplayHarness,
    _cli_json,
    _SilentServer,
    _SilentSession,
    _tool_payload,
)

#: The planted observation's label when the canary is left out: exactly the
#: person-shaped content the wire guard cannot tell from a legitimate title.
_PLANTED_LABEL = f"{PERSON_SHAPED_NAME} weekly review checkpoint"


def _planted_harness(tmp_path: Path) -> ReplayHarness:
    replay = real_session_replay(
        fingerprint=planted_session_fingerprint(include_canary=False)
    )
    harness = ReplayHarness(replay, tmp_path, analysis_mode=AnalysisMode.GUIDED)
    harness.prepare()
    harness.run_to(DiagnosisStage.ANALYSIS_PLANNED)
    return harness


def _cli_work_payload(harness: ReplayHarness) -> dict[str, object]:
    diagnosis_cli.bind_consent_surface(_SilentSession(), _SilentServer())
    try:
        with patch.object(diagnosis_cli, "build_engine", lambda: harness.engine):
            return _cli_json(["work", "--run", harness.bundle.run_id, "--json"])
    finally:
        diagnosis_cli.reset_consent_surface()


def _mcp_work_payload(harness: ReplayHarness) -> dict[str, object]:
    async def drive() -> dict[str, object]:
        server = build_mcp_server(harness.engine)
        async with Client(server, raise_exceptions=True) as client:
            result = await client.call_tool(
                "get_diagnosis_work", {"run_id": harness.bundle.run_id}
            )
        return _tool_payload(result)

    return anyio.run(drive)


def _planted_row(payload: dict[str, object]) -> dict[str, object]:
    legend = payload["evidence_legend"]
    assert isinstance(legend, list)
    rows = [row for row in legend if row["identity"] == "invented-planted-method"]
    assert len(rows) == 1
    return rows[0]


def test_the_legend_carries_the_planted_shapes_on_both_work_surfaces(
    tmp_path: Path,
) -> None:
    """Positive control: shipping these shapes is the legend's job, and allowed.

    A label and a relative reference from the privacy-screened fingerprint are
    local-only facts the host needs in order to cite the opaque evidence and
    observation tokens; the CLI and MCP ``work`` payloads therefore carry them
    deliberately, in the same trust domain as the fingerprint artifact on
    disk. Without this control, the canary-absence tests could pass against a
    legend that ships nothing at all.
    """

    harness = _planted_harness(tmp_path)
    cli_payload = _cli_work_payload(harness)
    mcp_payload = _mcp_work_payload(harness)
    assert canonical_work_bytes(cli_payload) == canonical_work_bytes(mcp_payload)

    row = _planted_row(cli_payload)
    assert row["label"] == _PLANTED_LABEL
    assert PERSON_SHAPED_NAME in row["label"]
    assert row["relative_reference"] == VAULT_SHAPED_PATH
    assert row["source_class"] == "vault-authored"
    # The plant is shape-only: the canary was left out, and none rides along.
    assert CANARY not in json.dumps(cli_payload)


def test_the_same_work_payload_never_exists_for_a_canary_carrying_fingerprint(
    tmp_path: Path,
) -> None:
    """The refusal for detectable secrets sits upstream, at capture.

    With the canary planted into the same observation, the engine refuses the
    fingerprint before anything is retained, so the run never reaches the
    stage that issues packets — there is no work payload, and therefore no
    legend, for the canary to ride out on. The legend's allowance for local
    shapes is not an allowance for secret material.
    """

    replay = real_session_replay(
        fingerprint=planted_session_fingerprint(include_canary=True)
    )
    harness = ReplayHarness(replay, tmp_path, analysis_mode=AnalysisMode.GUIDED)
    harness.prepare()
    harness.approve()
    approved = harness.engine.advance(replay.run_id)
    assert approved.stage is DiagnosisStage.SCOPE_APPROVED

    with pytest.raises(DiagnosisStateError, match="refuses to retain"):
        harness.engine.advance(replay.run_id)

    with pytest.raises(DiagnosisStateError):
        harness.engine.work_context(replay.run_id)
    with pytest.raises(DiagnosisStateError):
        harness.engine.pending_work(replay.run_id)
    assert CANARY not in harness.stored_run_text()


def test_a_reason_quoting_a_legend_label_is_retained_only_where_proposals_live(
    tmp_path: Path,
) -> None:
    """Pin the retention surface for quoted legend content deliberately.

    A specialist may quote a legend label in its reason — that is the legend
    working as designed, and the reason then round-trips into retained
    artifacts through the normal validated-proposal path. What is allowed:
    the quoted label lands in the ``work-responses`` and
    ``reconciled-proposals`` artifacts, which live in local app storage in
    the same trust domain as the fingerprint that carried the label first.
    What is pinned: those are the only artifacts the quote reaches — the
    engine-authored ``work-queue`` and ``work-audit`` never absorb proposal
    prose, so retention stays attributable to the submission, not ambient.
    """

    harness = _planted_harness(tmp_path)
    engine = harness.engine
    run_id = harness.bundle.run_id
    payload = _cli_work_payload(harness)
    row = _planted_row(payload)
    first = engine.work(run_id)
    assert first is not None
    # No quotation marks in the sentence: the artifacts are scanned as JSON
    # text, where a quote character would be escaped and defeat the substring
    # assertions below.
    quoting_reason = (
        f"The method {row['label']} documented at {row['relative_reference']} "
        "is distinctive and grounded in the approved evidence."
    )
    assert PERSON_SHAPED_NAME in quoting_reason
    assert VAULT_SHAPED_PATH in quoting_reason
    proposal = SpecialistProposal(
        role=first.role,
        kind=ProposalKind.STRENGTH,
        run_id=first.run_id,
        fingerprint_digest=first.fingerprint_digest,
        catalogue_digest=first.catalogue_digest,
        packet_id=first.packet_id,
        packet_digest=first.packet_digest,
        catalogue_id=first.catalogue_ids[0],
        capability_id=first.capability_ids[0],
        candidate_id=candidate_id_for(
            ProposalKind.STRENGTH, first.catalogue_ids[0], first.capability_ids[0]
        ),
        disposition=Disposition.STRONG_HERE,
        evidence_ids=(str(row["evidence_id"]),),
        observation_ids=(str(row["observation_id"]),),
        reason=quoting_reason,
    )
    engine.submit_work(run_id, first.packet_id, (proposal,))
    harness.run_to(DiagnosisStage.CLOSED)

    checkpoint = harness.checkpoint()
    artifacts = {
        kind: json.dumps(
            harness._artifact_payload(checkpoint, kind),  # noqa: SLF001 - digest store
            default=str,
        )
        for kind in (
            "work-queue",
            "work-responses",
            "work-audit",
            "reconciled-proposals",
        )
    }
    # The honest retention surface: the validated proposal, quote and all.
    assert quoting_reason in artifacts["work-responses"]
    assert quoting_reason in artifacts["reconciled-proposals"]
    # And nowhere the proposal path does not write.
    assert quoting_reason not in artifacts["work-queue"]
    assert quoting_reason not in artifacts["work-audit"]
    for planted in (PERSON_SHAPED_NAME, VAULT_SHAPED_PATH):
        assert planted not in artifacts["work-queue"]
        assert planted not in artifacts["work-audit"]
