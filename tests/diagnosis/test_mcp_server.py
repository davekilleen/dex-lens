"""Read-only MCP v2 adapter over an injected diagnosis engine."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, MCPError
from mcp.client.stdio import StdioServerParameters
from tests.evals.real_session_fixture import CANARY

from capability_exchange.diagnosis.mcp_server import (
    EXPECTED_TOOLS,
    FORBIDDEN_TOOL_SUBSTRINGS,
    PrepareDiagnosisRequest,
    SpecialistProposal,
    _required_step,
    build_engine,
    build_mcp_server,
    canonical_result_bytes,
    main,
)
from capability_exchange.diagnosis.run import (
    NEXT_ACTION,
    DiagnosisRunView,
    DiagnosisStage,
    DiagnosisStateError,
    RequiredStep,
)
from capability_exchange.diagnosis.specialists import (
    ProposalKind,
    SpecialistRole,
)
from capability_exchange.diagnosis.specialists import (
    SpecialistProposal as EngineProposal,
)

RUN_ID = "run:" + "a" * 16
CLOSED_RESULT = {
    "close": {
        "dex_should_learn": "honest empty: no reciprocal lesson yet",
        "first_move": "review invented-capability-001",
        "report_location": "app-storage:diagnosis-reports",
        "return_to_run": RUN_ID,
        "sharing_choice": "offered",
        "strongest": "already doing invented-capability-000",
    },
    "run_id": RUN_ID,
    "stage": "closed",
}
HOSTILE_ROOT = "/Users/invented/vault"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"

# CLI result-byte equality waits for Task 9. This slice compares the injected
# engine directly with the MCP tool and does not implement a diagnosis CLI.


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class FakeStored:
    payload: dict[str, Any]

    def dump_for_storage(self) -> dict[str, Any]:
        return self.payload


@dataclass
class FakeEngine:
    """Protocol-shaped stand-in. Task 8 owns the real orchestrator."""

    consented: bool = False
    collection_calls: int = 0
    prepared: list[PrepareDiagnosisRequest] = field(default_factory=list)
    submitted: list[object] = field(default_factory=list)

    def prepare(self, request: PrepareDiagnosisRequest) -> DiagnosisRunView:
        self.prepared.append(request)
        return DiagnosisRunView(
            run_id=RUN_ID,
            stage=DiagnosisStage.CREATED,
            next_action=NEXT_ACTION[DiagnosisStage.CREATED],
            input_identity=None,
            approval_url="http://127.0.0.1:9/approve",
        )

    def status(self, run_id: str) -> DiagnosisRunView:
        stage = DiagnosisStage.SCOPE_APPROVED if self.consented else DiagnosisStage.CREATED
        return DiagnosisRunView(
            run_id=run_id,
            stage=stage,
            next_action=NEXT_ACTION[stage],
        )

    def advance(self, run_id: str) -> DiagnosisRunView:
        if not self.consented:
            raise DiagnosisStateError(
                "approve the exact scope",
                required_step=RequiredStep.APPROVE_SCOPE,
            )
        self.collection_calls += 1
        return DiagnosisRunView(
            run_id=run_id,
            stage=DiagnosisStage.CAPTURED,
            next_action=NEXT_ACTION[DiagnosisStage.CAPTURED],
        )

    def submit(self, run_id: str, proposal: object) -> DiagnosisRunView:
        self.submitted.append(proposal)
        return self.status(run_id)

    def result(self, run_id: str) -> FakeStored:
        if run_id != RUN_ID:
            raise DiagnosisStateError("unknown diagnosis run")
        return FakeStored(dict(CLOSED_RESULT))


def fake_engine() -> FakeEngine:
    return FakeEngine()


def _tool_payload(result: object) -> dict[str, Any]:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or ()
    for block in content:
        text = getattr(block, "text", None)
        if text:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded
    raise AssertionError(f"tool result had no JSON object payload: {result!r}")


@pytest.mark.anyio
async def test_mcp_exposes_only_the_read_only_diagnosis_tools() -> None:
    server = build_mcp_server(fake_engine())
    async with Client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
    names = {item.name for item in tools.tools}
    assert names == EXPECTED_TOOLS
    for name in names:
        lowered = name.lower()
        assert all(token not in lowered for token in FORBIDDEN_TOOL_SUBSTRINGS)


@pytest.mark.anyio
async def test_unknown_pydantic_fields_are_refused() -> None:
    server = build_mcp_server(fake_engine())
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_diagnosis_status",
            {"run_id": RUN_ID, "invented_field": "nope"},
        )
    assert result.is_error


@pytest.mark.anyio
async def test_secret_canaries_and_absolute_paths_are_refused() -> None:
    engine = fake_engine()
    server = build_mcp_server(engine)
    async with Client(server, raise_exceptions=True) as client:
        prepared = await client.call_tool(
            "prepare_diagnosis",
            {"roots": [HOSTILE_ROOT, CANARY]},
        )
        view = _tool_payload(prepared)
        encoded = json.dumps(view)
        assert CANARY not in encoded
        assert HOSTILE_ROOT not in encoded
        assert "/Users/" not in encoded

        canary = await client.call_tool(
            "submit_specialist_proposal",
            {"run_id": RUN_ID, "proposal": {"note": CANARY}},
        )
        path = await client.call_tool(
            "submit_specialist_proposal",
            {"run_id": RUN_ID, "proposal": {"note": HOSTILE_ROOT}},
        )
        extra = await client.call_tool(
            "submit_specialist_proposal",
            {"run_id": RUN_ID, "proposal": {"note": "ok", "invented": 1}},
        )
    assert canary.is_error
    assert path.is_error
    assert extra.is_error
    assert engine.collection_calls == 0


@pytest.mark.anyio
async def test_advance_before_consent_is_structured_mcp_error_without_collection() -> None:
    engine = fake_engine()
    server = build_mcp_server(engine)
    async with Client(server, raise_exceptions=True) as client:
        with pytest.raises(MCPError) as caught:
            await client.call_tool("advance_diagnosis", {"run_id": RUN_ID})
    assert engine.collection_calls == 0
    error = caught.value
    assert error.data is not None
    assert error.data["required_step"] == "approve_scope"
    assert "approve the exact scope" in error.message


@pytest.mark.parametrize(
    "message",
    (
        "approve this scope",
        "consent is required",
        "scope approval is missing",
    ),
)
def test_required_step_is_never_inferred_from_error_message(message: str) -> None:
    assert _required_step(DiagnosisStateError(message)) == RequiredStep.REQUIRED_STEP.value


@pytest.mark.anyio
async def test_closed_result_bytes_match_direct_engine_not_a_cli() -> None:
    """CLI equality waits for Task 9. This slice compares engine vs MCP only."""

    engine = fake_engine()
    server = build_mcp_server(engine)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("get_diagnosis_result", {"run_id": RUN_ID})
    mcp_bytes = canonical_result_bytes(_tool_payload(result))
    engine_bytes = canonical_result_bytes(engine.result(RUN_ID).dump_for_storage())
    assert mcp_bytes == engine_bytes
    assert CANARY.encode() not in mcp_bytes
    assert b"/Users/" not in mcp_bytes


def test_build_engine_is_injectable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert build_engine() is not None
    engine = fake_engine()
    assert build_mcp_server(engine) is not None


def test_prepare_request_refuses_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        PrepareDiagnosisRequest.from_mapping({"roots": ["vault"], "extra": 1})


_VALID_PROPOSAL = {
    "role": SpecialistRole.TOOLS_AND_INTEGRATIONS.value,
    "kind": ProposalKind.MAPPING.value,
    "run_id": RUN_ID,
    "fingerprint_digest": "sha256:" + "b" * 64,
    "catalogue_digest": "sha256:" + "c" * 64,
    "catalogue_id": "daily-planning",
    "capability_id": "planning",
    "disposition": "shared",
    "evidence_ids": ["current:evidence"],
    "reason": "The local method matches the signed catalogue method.",
}


def test_specialist_proposal_validates_the_engine_schema() -> None:
    parsed = SpecialistProposal.from_mapping(_VALID_PROPOSAL)
    assert isinstance(parsed, EngineProposal)
    assert parsed.catalogue_id == "daily-planning"
    with pytest.raises(ValueError, match="unknown fields"):
        SpecialistProposal.from_mapping({**_VALID_PROPOSAL, "claims": ["invented"]})


@pytest.mark.anyio
async def test_submit_forwards_a_typed_engine_proposal() -> None:
    engine = fake_engine()
    server = build_mcp_server(engine)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "submit_specialist_proposal",
            {"run_id": RUN_ID, "proposal": _VALID_PROPOSAL},
        )
    assert not result.is_error
    assert len(engine.submitted) == 1
    assert isinstance(engine.submitted[0], EngineProposal)
    assert engine.submitted[0].capability_id == "planning"


_STDIO_SMOKE = r"""
from capability_exchange.diagnosis.mcp_server import build_mcp_server
from capability_exchange.diagnosis.run import (
    NEXT_ACTION,
    DiagnosisRunView,
    DiagnosisStage,
    DiagnosisStateError,
)
import sys

CANARY = "INVENTED_SESSION_CANARY_NEVER_RETAIN"
print(CANARY, file=sys.stderr)

class Engine:
    def prepare(self, request):
        return DiagnosisRunView(
            run_id="run:" + "a" * 16,
            stage=DiagnosisStage.CREATED,
            next_action=NEXT_ACTION[DiagnosisStage.CREATED],
        )
    def status(self, run_id):
        return self.prepare(None)
    def advance(self, run_id):
        raise DiagnosisStateError("approve the exact scope")
    def submit(self, run_id, proposal):
        return self.status(run_id)
    def result(self, run_id):
        class Stored:
            def dump_for_storage(self):
                return {"run_id": run_id, "stage": "closed"}
        return Stored()

build_mcp_server(Engine()).run(transport="stdio")
"""


def _stdio_env() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(_SRC)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["LENS_TEST_CANARY"] = CANARY
    return environment


@pytest.mark.anyio
async def test_stdio_subprocess_speaks_the_closed_tool_set() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", _STDIO_SMOKE],
        env=_stdio_env(),
        cwd=str(_REPO_ROOT),
    )
    async with Client(params, raise_exceptions=True) as client:
        tools = await client.list_tools()
        prepared = await client.call_tool("prepare_diagnosis", {"roots": [HOSTILE_ROOT]})
    names = {item.name for item in tools.tools}
    assert names == EXPECTED_TOOLS
    encoded = json.dumps(_tool_payload(prepared))
    assert CANARY not in encoded
    assert HOSTILE_ROOT not in encoded


def test_stdio_stdout_contains_protocol_only() -> None:
    initialize = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "lens-task-10", "version": "0"},
            },
        },
        separators=(",", ":"),
    )
    initialized = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    list_tools = json.dumps(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        separators=(",", ":"),
    )
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _STDIO_SMOKE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=_REPO_ROOT,
        env=_stdio_env(),
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    try:
        proc.stdin.write(initialize + "\n")
        proc.stdin.flush()
        first = proc.stdout.readline()
        proc.stdin.write(initialized + "\n")
        proc.stdin.write(list_tools + "\n")
        rest, stderr = proc.communicate(timeout=15)
    except Exception:
        proc.kill()
        raise
    stdout = first + rest
    assert proc.returncode == 0, stderr
    assert stdout, "stdio server wrote no protocol frames"
    assert CANARY not in stdout
    assert HOSTILE_ROOT not in stdout
    assert "/Users/" not in stdout
    frames = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert frames, "stdio server wrote no JSON-RPC frames"
    for message in frames:
        assert message["jsonrpc"] == "2.0"
        assert "method" in message or "result" in message or "error" in message
    assert any(frame.get("id") == 1 and "result" in frame for frame in frames)
    listed = next(frame for frame in frames if frame.get("id") == 2 and "result" in frame)
    names = {item["name"] for item in listed["result"]["tools"]}
    assert names == EXPECTED_TOOLS


def test_main_uses_injectable_build_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Server:
        def run(self, transport: str = "stdio") -> None:
            calls.append(transport)

    monkeypatch.setattr(
        "capability_exchange.diagnosis.mcp_server.build_engine",
        lambda: fake_engine(),
    )
    monkeypatch.setattr(
        "capability_exchange.diagnosis.mcp_server.build_mcp_server",
        lambda engine: _Server(),
    )
    main()
    assert calls == ["stdio"]
