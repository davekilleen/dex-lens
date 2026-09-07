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
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import anyio
import pytest
from mcp import Client
from tests.diagnosis.test_real_comparer_guided_run import (
    RECIPROCAL_ID,
    RealComparerHarness,
    _proposals_for_packet,
)
from tests.evals.real_session_fixture import (
    CANARY,
    PERSON_SHAPED_NAME,
    VAULT_SHAPED_PATH,
    planted_session_fingerprint,
)
from tests.evals.test_real_session_replay import real_session_replay

from capability_exchange.boundary.crashlog import write_crash_log
from capability_exchange.diagnosis import cli as diagnosis_cli
from capability_exchange.diagnosis.comparison import Disposition
from capability_exchange.diagnosis.mcp_server import (
    build_mcp_server,
    canonical_work_bytes,
)
from capability_exchange.diagnosis.orchestrator import PrepareDiagnosisRequest
from capability_exchange.diagnosis.payload_guard import (
    HostilePayloadError,
    refuse_hostile_payload,
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
from capability_exchange.share import cli as share_cli

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


def test_a_quoting_reason_reaches_the_proposal_artifacts_and_no_engine_authored_one(
    tmp_path: Path,
) -> None:
    """Pin which run-store artifacts absorb quoted legend content.

    A specialist may quote a legend label in its reason — that is the legend
    working as designed, and the reason then round-trips into retained
    artifacts through the normal validated-proposal path. What is allowed:
    the quoted label lands in the ``work-responses`` and
    ``reconciled-proposals`` artifacts, which live in local app storage in
    the same trust domain as the fingerprint that carried the label first.
    What is pinned here: among the four work artifacts, only the two the
    proposal path writes carry the quote — the engine-authored ``work-queue``
    and ``work-audit`` never absorb proposal prose, so retention stays
    attributable to the submission, not ambient.

    This is NOT a containment claim for the whole run (its earlier name and
    docstring implied one it never checked): driven through the real comparer,
    a quoting reason also lawfully reaches the ledger and the saved local
    report. That allowance, and the outbound surfaces that must never carry
    it, are stated and checked by
    ``test_planted_shapes_quoted_in_a_reason_stay_local_and_never_go_outbound``.
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


#: Both planted shapes, exactly as a specialist would copy them out of a
#: legend row into a valid one-line reason. Everything here is invented.
_QUOTING_REASON = (
    f"The method {_PLANTED_LABEL} documented at {VAULT_SHAPED_PATH} "
    "is a lesson Dex lacks."
)

_PLANTED_SHAPES = (PERSON_SHAPED_NAME, VAULT_SHAPED_PATH)

_WOW_GATE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_wow_gate.py"


def _closed_real_comparer_run_quoting_the_planted_shapes(
    tmp_path: Path,
) -> tuple[RealComparerHarness, str]:
    """Drive the REAL comparer to CLOSED with the quoting reason retained.

    The reason rides the uncontested reciprocal proposal, whose prose the
    sceptical reconciler never rewrites, so it survives coalescing into the
    ledger entry, the rendered markdown, and the saved report.
    """

    harness = RealComparerHarness(tmp_path)
    prepared = harness.engine.prepare(
        PrepareDiagnosisRequest(roots=(harness.root,), analysis_mode=AnalysisMode.GUIDED)
    )
    harness.run_to(prepared.run_id, DiagnosisStage.ANALYSIS_PLANNED)
    quoted = False
    while True:
        packet = harness.engine.work(prepared.run_id)
        if packet is None:
            break
        proposals = tuple(
            item.model_copy(update={"reason": _QUOTING_REASON})
            if item.kind is ProposalKind.RECIPROCAL and item.catalogue_id == RECIPROCAL_ID
            else item
            for item in _proposals_for_packet(packet)
        )
        quoted = quoted or any(item.reason == _QUOTING_REASON for item in proposals)
        harness.engine.submit_work(prepared.run_id, packet.packet_id, proposals)
    assert quoted
    closed = harness.run_to(prepared.run_id, DiagnosisStage.CLOSED)
    assert closed.stage is DiagnosisStage.CLOSED
    return harness, prepared.run_id


def test_planted_shapes_quoted_in_a_reason_stay_local_and_never_go_outbound(
    tmp_path: Path,
) -> None:
    """THE CONTRACT (finding A4, 2026-09-07 adversarial review), both halves.

    The saved report is the person's own private artifact, and naming their
    own labels and vault-relative paths is the product's job — the path is
    what separates a hunt that ran from a sentence about a hunt. So a valid
    reason quoting a legend row's person-shaped label and client-shaped
    relative path DOES reach the ledger, the rendered markdown, and the
    report saved to local app storage: that propagation is intended and
    documented here, not a leak.

    What is guaranteed instead: no outbound, shareable, or commit-able
    surface the repo ships ever carries those shapes — the wow-gate grade
    JSON (a closed vocabulary of scores and slugs), the grader's own stderr,
    the wire guard's refusal, and the crash log all stay clean. The share
    payload is covered by its own sibling test below.
    """

    harness, run_id = _closed_real_comparer_run_quoting_the_planted_shapes(tmp_path)
    result = harness.engine.result(run_id)

    # ---- The allowance: the local, private artifacts carry the shapes. ----
    markdown = result.render_markdown()
    ledger_json = result.ledger.model_dump_json()
    saved_markdown_files = sorted(harness.report_store.directory.glob("*.md"))
    assert saved_markdown_files, "the closed run must have saved its local report"
    saved_markdown = saved_markdown_files[-1].read_text(encoding="utf-8")
    for planted in _PLANTED_SHAPES:
        assert planted in ledger_json
        assert planted in markdown
        assert planted in saved_markdown

    # ---- The guarantee: every outbound surface stays clean. ----
    # 1. The wow-gate grade JSON, produced by the real grader entry point
    #    from the saved result file, and the grader's own terminal output.
    result_json_files = sorted(harness.report_store.directory.glob("*.result.json"))
    assert result_json_files
    saved_result_json = result_json_files[-1].read_text(encoding="utf-8")
    for planted in _PLANTED_SHAPES:
        assert planted in saved_result_json  # the grader's input DOES carry them
    grade_path = tmp_path / "grade.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(_WOW_GATE_SCRIPT),
            "--result",
            str(result_json_files[-1]),
            "--output",
            str(grade_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    grade_text = grade_path.read_text(encoding="utf-8")
    for planted in _PLANTED_SHAPES:
        assert planted not in grade_text
        assert planted not in completed.stdout
        assert planted not in completed.stderr

    # 2. A refusal message: even when a reason carrying the shapes is refused
    #    (here, for also smuggling an absolute path), the refusal names the
    #    required step and never echoes the content.
    with pytest.raises(HostilePayloadError) as caught:
        refuse_hostile_payload(f"{_QUOTING_REASON} /Users/invented-owner/private.md")
    for planted in _PLANTED_SHAPES:
        assert planted not in str(caught.value)

    # 3. The crash log: an exception whose message embeds the shapes is
    #    stored structurally, values discarded.
    crash_path = write_crash_log(
        ValueError(f"invented crash while rendering {_QUOTING_REASON}"),
        tmp_path / "crash-logs",
    )
    crash_text = crash_path.read_text(encoding="utf-8")
    assert "ValueError" in crash_text
    for planted in _PLANTED_SHAPES:
        assert planted not in crash_text


def test_the_share_payload_is_exactly_the_previewed_card_and_never_the_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The share-back channel carries the card, the contact, the version — only.

    On a machine whose local report and ledger carry the planted shapes, a
    share of an invented idea card must produce an outbound payload built
    from nothing but the card the person previewed: exactly three fields,
    none of them read from the reports store, so the planted shapes cannot
    ride along unless a person deliberately writes them into the card and
    approves the preview.
    """

    _closed_real_comparer_run_quoting_the_planted_shapes(tmp_path)

    card = tmp_path / "card.md"
    card_text = "# Invented pattern\n\nPair every invented step with an invented check.\n"
    card.write_text(card_text, encoding="utf-8")

    sent: list[bytes] = []

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            del limit
            return b"Shared."

    def _capture(request: object, timeout: float | None = None) -> _Response:
        del timeout
        sent.append(request.data)  # type: ignore[attr-defined]
        return _Response()

    monkeypatch.setattr(share_cli.urllib.request, "urlopen", _capture)
    assert share_cli.share_main([str(card), "--yes"]) == 0

    assert len(sent) == 1
    payload = json.loads(sent[0])
    assert set(payload) == {"card", "contact", "lens_version"}
    assert payload["card"] == card_text
    assert payload["contact"] is None
    outbound_text = sent[0].decode("utf-8")
    for planted in (PERSON_SHAPED_NAME, VAULT_SHAPED_PATH):
        assert planted not in outbound_text
