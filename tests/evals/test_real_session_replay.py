from __future__ import annotations

import inspect
import json
import sys
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from enum import StrEnum
from io import StringIO
from pathlib import Path
from typing import Literal, Self
from unittest.mock import patch

import anyio
import pytest
from mcp import Client, MCPError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from tests.evals.real_session_fixture import (
    CANARY,
    EXPECTED_COUNTS,
    NOW,
    PERSON_SHAPED_NAME,
    VAULT_SHAPED_PATH,
    planted_session_fingerprint,
    planted_session_ledger,
    real_session_fingerprint,
    real_session_input,
    real_session_ledger,
    real_session_report,
    synthetic_entry_ids,
)

from capability_exchange.diagnosis import cli as diagnosis_cli
from capability_exchange.diagnosis.comparison import ComparisonLedger, Disposition
from capability_exchange.diagnosis.mcp_server import build_mcp_server
from capability_exchange.diagnosis.observations import EvidenceFingerprint
from capability_exchange.diagnosis.orchestrator import (
    ComparisonBuilder,
    VerifiedCatalogueSlice,
)
from capability_exchange.diagnosis.run import DiagnosisStage, DiagnosisStateError
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistProposal,
    SpecialistProposalError,
    SpecialistRole,
    candidate_id_for,
)
from capability_exchange.diagnosis.work import AnalysisMode, WorkPacket
from capability_exchange.evaluation.diagnosis import evaluate_diagnosis
from capability_exchange.evaluation.replay import (
    FIXED_RUN_ID,
    ReplayBundle,
    ReplayHarness,
    _FixedComparer,
    _SilentServer,
    _SilentSession,
    run_cli,
    run_direct,
    run_mcp,
)

EXPECTED = Path(__file__).parents[1] / "fixtures" / "evals" / "real-session-expected.json"
FALSE_COVERAGE_CLAIM = "93 capabilities are already covered"


class StrictExpectedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ExpectedObservationCounts(StrictExpectedModel):
    mcp_servers_declared: Literal[0]
    mcp_tools_known: Literal[0]
    automation_implemented: Literal[0]
    automation_loaded: Literal[0]
    health_collectors: Literal[0]
    restore_proofs: Literal[0]


class ExpectedDispositionCounts(StrictExpectedModel):
    not_assessed: Literal[80] = Field(alias=Disposition.NOT_ASSESSED.value)
    not_relevant: Literal[17] = Field(alias=Disposition.NOT_RELEVANT.value)
    shared: Literal[8]
    worth_borrowing: Literal[3] = Field(alias=Disposition.WORTH_BORROWING.value)
    fragile_or_contradictory: Literal[3] = Field(alias=Disposition.FRAGILE_OR_CONTRADICTORY.value)
    strong_here: Literal[2] = Field(alias=Disposition.STRONG_HERE.value)
    dex_should_learn: Literal[2] = Field(alias=Disposition.DEX_SHOULD_LEARN.value)


class ExpectedStage(StrEnum):
    CREATED = "created"
    SCOPE_APPROVED = "scope-approved"
    CAPTURED = "captured"
    CATALOGUE_VERIFIED = "catalogue-verified"
    JOBS_CONFIRMED = "jobs-confirmed"
    COMPARED = "compared"
    RENDERED = "rendered"
    CHECKED = "checked"
    SAVED = "saved"
    CLOSED = "closed"


class ExpectedProvenanceClass(StrEnum):
    VAULT_AUTHORED = "vault-authored"
    USER_GLOBAL = "user-global"


class ExpectedCleanCloseField(StrEnum):
    STRONGEST_GROUNDED_CAPABILITY = "strongest_grounded_capability"
    RECIPROCAL_VALUE = "reciprocal_value"
    SINGLE_BEST_FIRST_MOVE = "single_best_first_move"
    REPORT_LOCATION = "report_location"
    RETURN_TO_RUN = "return_to_run"
    SHARING_CHOICE = "sharing_choice"
    FUTURE_WATCH_CHOICE = "future_watch_choice"


class RealSessionExpectedContract(StrictExpectedModel):
    release_id: Literal["invented-release-v1"]
    observations: ExpectedObservationCounts
    catalogue_entry_count: Literal[115]
    disposition_counts: ExpectedDispositionCounts
    expected_stage_order: tuple[ExpectedStage, ...]
    forbidden_claims: tuple[Literal["93 capabilities are already covered"], ...]
    required_provenance_classes: tuple[ExpectedProvenanceClass, ...]
    required_clean_close_fields: tuple[ExpectedCleanCloseField, ...]
    max_recommendations: Literal[10]
    requires_strength: Literal[True]
    requires_reciprocal_answer: Literal[True]

    @field_validator("expected_stage_order")
    @classmethod
    def _stage_order_is_exact(cls, value: tuple[ExpectedStage, ...]) -> tuple[ExpectedStage, ...]:
        if value != tuple(ExpectedStage):
            raise ValueError("expected_stage_order must contain every stage in exact order")
        return value

    @field_validator("required_provenance_classes")
    @classmethod
    def _provenance_classes_are_exact(
        cls, value: tuple[ExpectedProvenanceClass, ...]
    ) -> tuple[ExpectedProvenanceClass, ...]:
        if value != tuple(ExpectedProvenanceClass):
            raise ValueError(
                "required_provenance_classes must contain both source classes in exact order"
            )
        return value

    @field_validator("required_clean_close_fields")
    @classmethod
    def _clean_close_fields_are_exact(
        cls, value: tuple[ExpectedCleanCloseField, ...]
    ) -> tuple[ExpectedCleanCloseField, ...]:
        if value != tuple(ExpectedCleanCloseField):
            raise ValueError(
                "required_clean_close_fields must contain every clean-close field in exact order"
            )
        return value

    def evaluator_mapping(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)

    def without_literal_blacklist(self) -> Self:
        raw = self.evaluator_mapping()
        raw["forbidden_claims"] = []
        return self.model_validate_json(json.dumps(raw))


def expected_contract() -> RealSessionExpectedContract:
    return RealSessionExpectedContract.model_validate_json(EXPECTED.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("case", "error_field"),
    (
        ("missing-required-field", "catalogue_entry_count"),
        ("extra-top-level-field", "unexpected_field"),
        ("malformed-disposition-count", "not-assessed"),
        ("extra-nested-disposition", "invented-extra"),
        ("unknown-stage", "expected_stage_order"),
    ),
)
def test_expected_contract_rejects_malformed_mapping(
    case: str,
    error_field: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if case == "missing-required-field":
        raw.pop("catalogue_entry_count")
    elif case == "extra-top-level-field":
        raw["unexpected_field"] = "invented"
    elif case == "malformed-disposition-count":
        raw["disposition_counts"]["not-assessed"] = "eighty"
    elif case == "extra-nested-disposition":
        raw["disposition_counts"]["invented-extra"] = 1
    else:
        raw["expected_stage_order"][0] = "finished"

    malformed = tmp_path / f"{case}.json"
    malformed.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "EXPECTED", malformed)

    with pytest.raises(ValidationError, match=error_field):
        expected_contract()


def test_report_cannot_claim_93_covered_when_80_are_not_assessed() -> None:
    ledger = real_session_ledger()
    truthful_report = real_session_report()
    contradictory_report = truthful_report.replace(
        "80 capabilities remain Unknown",
        FALSE_COVERAGE_CLAIM,
    )
    expected = expected_contract()
    expected_mapping = expected.evaluator_mapping()

    assert synthetic_entry_ids() == tuple(
        f"invented-capability-{index:03d}" for index in range(115)
    )
    assert Counter(item.disposition for item in ledger.entries) == EXPECTED_COUNTS
    assert expected.catalogue_entry_count == len(ledger.entries)
    assert expected.disposition_counts.model_dump(mode="json", by_alias=True) == {
        disposition.value: count for disposition, count in EXPECTED_COUNTS.items()
    }
    assert {item.source_class for item in real_session_input().sources} == set(
        expected.required_provenance_classes
    )
    assert expected.forbidden_claims == (FALSE_COVERAGE_CLAIM,)
    assert len({item.name for item in real_session_input().sources}) == 1
    assert all(
        reference.startswith(("probe-token:", "file-token:"))
        for item in ledger.entries
        for reference in item.evidence_references
    )
    assert all(
        item.evidence.reference.startswith(("probe-token:", "file-token:"))
        for item in real_session_fingerprint().observations
    )
    retained = "\n".join(
        (
            real_session_fingerprint().model_dump_json(),
            ledger.model_dump_json(),
            contradictory_report,
            expected.model_dump_json(by_alias=True),
        )
    )
    assert CANARY not in retained

    truthful_result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=truthful_report,
        expected=expected_mapping,
    )
    assert truthful_result.passed, truthful_result

    reconciliation_contract = expected.without_literal_blacklist()
    result = evaluate_diagnosis(
        fingerprint=real_session_fingerprint(),
        ledger=ledger,
        report_markdown=contradictory_report,
        expected=reconciliation_contract.evaluator_mapping(),
    )

    assert not result.passed, (
        "contradictory coverage report passed because the evaluator did not "
        "reconcile ledger-derived facts"
    )
    assert any("ledger-derived facts" in item for item in result.report_errors), (
        result.report_errors
    )


def _order(items: tuple[object, ...], ordering: str) -> tuple[object, ...]:
    if ordering == "forward":
        return items
    if ordering == "reverse":
        return tuple(reversed(items))
    if ordering == "rotated":
        if not items:
            return items
        return items[1:] + items[:1]
    raise ValueError(f"unknown replay ordering: {ordering}")


def real_session_replay(
    *,
    ordering: str = "forward",
    fingerprint: EvidenceFingerprint | None = None,
    ledger: ComparisonLedger | None = None,
) -> ReplayBundle:
    """Sanitised real-session input with a fixed clock and run id.

    ``fingerprint`` and ``ledger`` overrides exist for the canary suite, which
    deliberately hands the engine planted inputs.
    """

    fingerprint = real_session_fingerprint() if fingerprint is None else fingerprint
    fingerprint = fingerprint.model_copy(
        update={"observations": _order(fingerprint.observations, ordering)}
    )
    ledger = real_session_ledger() if ledger is None else ledger
    ledger = ledger.model_copy(
        update={
            "capabilities": _order(ledger.capabilities, ordering),
            "entries": _order(ledger.entries, ordering),
        }
    )
    return ReplayBundle(
        fingerprint=fingerprint,
        catalogue=VerifiedCatalogueSlice(
            version=ledger.catalogue_version,
            sha256=ledger.catalogue_sha256,
            catalogue_ids=tuple(item.catalogue_id for item in ledger.entries),
            capability_ids=tuple(item.capability_id for item in ledger.capabilities),
            unavailable_ids=(),
            family_contract_present=False,
        ),
        ledger=ledger,
        proposals=(),
        clock=NOW,
        run_id=FIXED_RUN_ID,
    )


def test_engine_replay_never_retains_the_session_canary(tmp_path: Path) -> None:
    replay = real_session_replay(ordering="forward")
    harness = ReplayHarness(replay, tmp_path)
    result = harness.run_to_closed()
    retained = "\n".join(
        (
            harness.retained_text(),
            result.dump_for_storage().__repr__(),
            json.dumps(result.dump_for_storage(), default=str),
            run_direct(replay).decode("utf-8"),
        )
    )
    assert CANARY not in retained


_PLANTED_SHAPES = (CANARY, PERSON_SHAPED_NAME, VAULT_SHAPED_PATH)
_CLEAN_REASON = "The invented approved evidence shows a distinctive reliable method."


def _drive_cli(engine: object, argv: list[str]) -> tuple[int, str, str]:
    """Run one diagnosis CLI command over an injected engine, capturing streams."""

    stdout, stderr = StringIO(), StringIO()
    diagnosis_cli.bind_consent_surface(_SilentSession(), _SilentServer())
    try:
        with (
            patch.object(diagnosis_cli, "build_engine", lambda: engine),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = diagnosis_cli.diagnosis_main(argv)
    finally:
        diagnosis_cli.reset_consent_surface()
    return code, stdout.getvalue(), stderr.getvalue()


def _drive_mcp_advance_error(harness: ReplayHarness) -> str:
    """Advance over MCP expecting a refusal; return everything the wire carried."""

    async def drive() -> str:
        server = build_mcp_server(harness.engine)
        async with Client(server, raise_exceptions=True) as client:
            with pytest.raises(MCPError) as caught:
                await client.call_tool(
                    "advance_diagnosis",
                    {"run_id": harness.bundle.run_id},
                )
        error = caught.value
        return json.dumps(
            {"message": error.message, "data": error.data},
            default=str,
        )

    return anyio.run(drive)


def _strength_proposal(packet: WorkPacket, *, reason: str) -> SpecialistProposal:
    return SpecialistProposal(
        role=packet.role,
        kind=ProposalKind.STRENGTH,
        run_id=packet.run_id,
        fingerprint_digest=packet.fingerprint_digest,
        catalogue_digest=packet.catalogue_digest,
        packet_id=packet.packet_id,
        packet_digest=packet.packet_digest,
        catalogue_id=packet.catalogue_ids[0],
        capability_id=packet.capability_ids[0],
        candidate_id=candidate_id_for(
            ProposalKind.STRENGTH,
            packet.catalogue_ids[0],
            packet.capability_ids[0],
        ),
        disposition=Disposition.STRONG_HERE,
        evidence_ids=(packet.evidence_ids[0],),
        observation_ids=(packet.observation_ids[0],),
        reason=reason,
    )


def test_hostile_fingerprint_is_refused_before_any_retention(tmp_path: Path) -> None:
    """A collected fingerprint carrying the canary must never become an artifact.

    Red first: without the capture guard this run captured normally and the
    canary, the person-shaped name, and the vault-shaped path were all retained
    verbatim inside the stored fingerprint artifact.
    """

    replay = real_session_replay(fingerprint=planted_session_fingerprint())
    harness = ReplayHarness(replay, tmp_path, analysis_mode=AnalysisMode.GUIDED)
    harness.prepare()
    harness.approve()
    approved = harness.engine.advance(replay.run_id)
    assert approved.stage is DiagnosisStage.SCOPE_APPROVED

    with pytest.raises(DiagnosisStateError, match="refuses to retain") as caught:
        harness.engine.advance(replay.run_id)

    stored = harness.stored_run_text()
    for planted in _PLANTED_SHAPES:
        assert planted not in str(caught.value)
        assert planted not in stored

    code, stdout, stderr = _drive_cli(
        harness.engine, ["advance", "--run", replay.run_id, "--json"]
    )
    assert code == 2
    assert "refuses to retain" in stderr
    mcp_error = _drive_mcp_advance_error(harness)
    for planted in _PLANTED_SHAPES:
        assert planted not in stdout
        assert planted not in stderr
        assert planted not in mcp_error


def test_hostile_ledger_is_refused_before_render_or_save(tmp_path: Path) -> None:
    """A comparison ledger carrying the canary must never render or save.

    Red first: without the comparison guard this run closed cleanly and the
    canary appeared verbatim in the ledger artifact, the result JSON, the
    saved report, and the rendered markdown.
    """

    replay = real_session_replay(ledger=planted_session_ledger())
    harness = ReplayHarness(replay, tmp_path)
    harness.prepare()
    harness.run_to(DiagnosisStage.JOBS_CONFIRMED)

    with pytest.raises(DiagnosisStateError, match="refuses to retain") as caught:
        harness.engine.advance(replay.run_id)

    stored = harness.stored_run_text()
    for planted in _PLANTED_SHAPES:
        assert planted not in str(caught.value)
        assert planted not in stored

    with pytest.raises(DiagnosisStateError, match="not closed"):
        harness.engine.result(replay.run_id)

    code, stdout, stderr = _drive_cli(
        harness.engine, ["advance", "--run", replay.run_id, "--json"]
    )
    assert code == 2
    assert "refuses to retain" in stderr
    mcp_error = _drive_mcp_advance_error(harness)
    for planted in _PLANTED_SHAPES:
        assert planted not in stdout
        assert planted not in stderr
        assert planted not in mcp_error


def test_hostile_specialist_reason_burns_one_attempt_and_is_never_retained(
    tmp_path: Path,
) -> None:
    """A guided proposal reason carrying the canary is refused, not recorded.

    Red first: without the submit_work guard the engine accepted this proposal
    and the canary was retained verbatim inside the work-responses and
    reconciled-proposals artifacts.
    """

    replay = real_session_replay()
    harness = ReplayHarness(replay, tmp_path, analysis_mode=AnalysisMode.GUIDED)
    harness.prepare()
    harness.run_to(DiagnosisStage.ANALYSIS_PLANNED)
    engine = harness.engine
    first = engine.work(replay.run_id)
    assert first is not None
    hostile = _strength_proposal(
        first,
        reason=f"{PERSON_SHAPED_NAME} wrote {VAULT_SHAPED_PATH}: {CANARY}.",
    )

    with pytest.raises(SpecialistProposalError, match="one retry remains"):
        engine.submit_work(replay.run_id, first.packet_id, (hostile,))
    for planted in _PLANTED_SHAPES:
        assert planted not in harness.stored_run_text()

    work_payloads: list[dict[str, object]] = [first.model_dump(mode="json")]
    views = [
        engine.submit_work(
            replay.run_id,
            first.packet_id,
            (_strength_proposal(first, reason=_CLEAN_REASON),),
        ).dump_for_storage()
    ]
    while True:
        packet = engine.work(replay.run_id)
        if packet is None:
            break
        work_payloads.append(packet.model_dump(mode="json"))
        views.append(
            engine.submit_work(replay.run_id, packet.packet_id, ()).dump_for_storage()
        )
    harness.run_to(DiagnosisStage.CLOSED)
    result = engine.result(replay.run_id)

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
            "ledger",
        )
    }
    # Positive control: the guided corpus carries real specialist content, so
    # the absence assertions below scan surfaces that provably retain content.
    assert _CLEAN_REASON in artifacts["work-responses"]
    assert _CLEAN_REASON in artifacts["reconciled-proposals"]

    surfaces = {
        "work-bytes": json.dumps(work_payloads),
        "submit-responses": json.dumps(views, default=str),
        "result-json": json.dumps(result.dump_for_storage(), default=str),
        "rendered-markdown": result.render_markdown(),
        "stored-run-text": harness.stored_run_text(),
        **artifacts,
    }
    for name, text in surfaces.items():
        for planted in _PLANTED_SHAPES:
            assert planted not in text, (name, planted)


def test_planted_session_content_never_leaves_the_fingerprint_artifact(
    tmp_path: Path,
) -> None:
    """Shapes no guard can detect must stay confined to the fingerprint.

    A person-shaped name and a relative vault-shaped path are legitimate-shaped
    local content: the wire guard cannot recognise them, so the engine must
    contain them structurally. The positive controls prove the plant and the
    scan both work before the absence assertions claim anything.
    """

    replay = real_session_replay(
        fingerprint=planted_session_fingerprint(include_canary=False)
    )

    def responder(packet: WorkPacket) -> tuple[SpecialistProposal, ...]:
        if packet.role is SpecialistRole.TOOLS_AND_INTEGRATIONS:
            return (_strength_proposal(packet, reason=_CLEAN_REASON),)
        return ()

    harness = ReplayHarness(
        replay,
        tmp_path,
        analysis_mode=AnalysisMode.GUIDED,
        work_responder=responder,
    )
    harness.prepare()
    harness.run_to(DiagnosisStage.CLOSED)
    result = harness.engine.result(replay.run_id)

    checkpoint = harness.checkpoint()
    artifacts = {
        kind: json.dumps(
            harness._artifact_payload(checkpoint, kind),  # noqa: SLF001 - digest store
            default=str,
        )
        for kind in (
            "fingerprint",
            "work-queue",
            "work-responses",
            "work-audit",
            "reconciled-proposals",
            "ledger",
        )
    }
    # Positive controls: the plant is present where local retention is honest,
    # and the guided corpus carries real specialist content.
    assert PERSON_SHAPED_NAME in artifacts["fingerprint"]
    assert VAULT_SHAPED_PATH in artifacts["fingerprint"]
    assert _CLEAN_REASON in artifacts["work-responses"]

    surfaces = {
        "work-queue": artifacts["work-queue"],
        "work-responses": artifacts["work-responses"],
        "work-audit": artifacts["work-audit"],
        "reconciled-proposals": artifacts["reconciled-proposals"],
        "ledger": artifacts["ledger"],
        "result-json": json.dumps(result.dump_for_storage(), default=str),
        "rendered-markdown": result.render_markdown(),
        "cli-stdout": run_cli(replay).decode("utf-8"),
        "mcp-result": run_mcp(replay).decode("utf-8"),
        "direct-result": run_direct(
            replay, analysis_mode=AnalysisMode.GUIDED
        ).decode("utf-8"),
    }
    for name, text in surfaces.items():
        for planted in (PERSON_SHAPED_NAME, VAULT_SHAPED_PATH, CANARY):
            assert planted not in text, (name, planted)


def test_replay_comparer_accepts_every_engine_comparison_argument() -> None:
    engine_arguments = {
        name
        for name, parameter in inspect.signature(ComparisonBuilder.compare).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    replay_arguments = set(inspect.signature(_FixedComparer.compare).parameters)
    assert engine_arguments <= replay_arguments, (
        "the replay comparer must accept every argument the engine passes to compare(); "
        f"missing: {sorted(engine_arguments - replay_arguments)}"
    )
