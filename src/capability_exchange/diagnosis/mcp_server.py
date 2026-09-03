"""Thin read-only MCP v2 stdio adapter over an injected diagnosis engine.

The adapter contains translation only. Diagnosis rules, collection, consent
issuance and report rendering stay behind the engine Protocol. Task 8 supplies
the real orchestrator; tests and later adapters inject a fake the same way.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import INVALID_REQUEST, ToolAnnotations
from pydantic import ConfigDict

from capability_exchange.diagnosis.payload_guard import (
    REMOVE_ABSOLUTE_PATH,
    REMOVE_SECRET,
    HostilePayloadError,
    parse_specialist_proposal,
    refuse_hostile_payload,
)
from capability_exchange.diagnosis.run import DiagnosisStateError, RequiredStep
from capability_exchange.diagnosis.specialists import (
    SpecialistProposal as EngineProposal,
)
from capability_exchange.diagnosis.specialists import (
    SpecialistProposalError,
)
from capability_exchange.diagnosis.work import WorkQueueError

__all__ = [
    "EXPECTED_TOOLS",
    "FORBIDDEN_TOOL_SUBSTRINGS",
    "DiagnosisEngine",
    "PrepareDiagnosisRequest",
    "SpecialistProposal",
    "StoredResult",
    "build_engine",
    "build_mcp_server",
    "canonical_result_bytes",
    "canonical_work_bytes",
    "main",
]

EXPECTED_TOOLS = {
    "prepare_diagnosis",
    "get_diagnosis_status",
    "advance_diagnosis",
    "get_diagnosis_work",
    "submit_specialist_proposal",
    "get_diagnosis_result",
}
FORBIDDEN_TOOL_SUBSTRINGS = ("write", "delete", "install", "repair", "share", "send")
_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    open_world_hint=False,
)


@dataclass(frozen=True)
class PrepareDiagnosisRequest:
    """Candidate roots for the local consent surface. Nothing is read here."""

    roots: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.roots:
            raise ValueError("prepare requires at least one candidate root")

    @classmethod
    def from_mapping(cls, payload: dict[str, object]) -> PrepareDiagnosisRequest:
        extra = set(payload) - {"roots"}
        if extra:
            raise ValueError("unknown fields are forbidden on prepare requests")
        roots = payload.get("roots")
        if not isinstance(roots, list | tuple) or not roots:
            raise ValueError("prepare requires at least one candidate root")
        if not all(isinstance(item, str) for item in roots):
            raise ValueError("prepare roots must be strings")
        return cls(roots=tuple(str(item) for item in roots))


class SpecialistProposal:
    """Refuse unknown wire fields, then validate the Task 7 proposal schema."""

    _FIELDS = frozenset(EngineProposal.model_fields)

    @classmethod
    def from_mapping(cls, payload: dict[str, object]) -> EngineProposal:
        return parse_specialist_proposal(payload)


@runtime_checkable
class StoredResult(Protocol):
    def dump_for_storage(self) -> dict[str, Any]: ...


@runtime_checkable
class DiagnosisEngine(Protocol):
    """The same small interface Task 9 will inject against."""

    def prepare(self, request: PrepareDiagnosisRequest) -> StoredResult: ...
    def status(self, run_id: str) -> StoredResult: ...
    def advance(self, run_id: str) -> StoredResult: ...
    def work(self, run_id: str) -> object: ...
    def work_context(self, run_id: str) -> tuple[object, ...]: ...
    def submit_work(
        self,
        run_id: str,
        packet_id: str,
        proposals: tuple[object, ...] = (),
    ) -> StoredResult: ...
    def submit(self, run_id: str, proposal: object) -> StoredResult: ...
    def result(self, run_id: str) -> StoredResult: ...


def _json_row(row: object) -> object:
    """Dump one typed legend row; already-plain rows pass through."""

    dump = getattr(row, "model_dump", None)
    return dump(mode="json") if callable(dump) else row


def canonical_work_bytes(payload: object) -> bytes:
    """Sorted compact JSON bytes used for engine-vs-adapter work equality."""

    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def canonical_result_bytes(payload: object) -> bytes:
    """Sorted compact JSON bytes used for engine-vs-MCP equality."""

    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def build_engine() -> DiagnosisEngine:
    """Return the process engine. Tests monkeypatch this function."""

    from capability_exchange.diagnosis.defaults import build_default_engine

    return build_default_engine()


def build_mcp_server(engine: DiagnosisEngine) -> MCPServer:
    server = MCPServer("dex-lens-diagnosis")
    _register_status_tool(server, engine)
    _register_advance_tool(server, engine)
    register_prepare_tool(server, engine)
    register_work_tool(server, engine)
    register_proposal_tool(server, engine)
    register_result_tool(server, engine)
    _forbid_unknown_tool_fields(server)
    return server


def main() -> None:
    build_mcp_server(build_engine()).run(transport="stdio")


def register_prepare_tool(server: MCPServer, engine: DiagnosisEngine) -> None:
    @server.tool(annotations=_READ_ONLY)
    def prepare_diagnosis(roots: list[str]) -> dict[str, object]:
        """Create a pending run and return the local consent action without reading."""
        request = PrepareDiagnosisRequest.from_mapping({"roots": list(roots)})
        return _dump(engine.prepare, request)


def register_work_tool(server: MCPServer, engine: DiagnosisEngine) -> None:
    @server.tool(annotations=_READ_ONLY)
    def get_diagnosis_work(run_id: str) -> dict[str, object]:
        """Return the next engine-issued packet, or a typed empty result."""
        try:
            packet = engine.work(run_id)
            legend = () if packet is None else tuple(engine.work_context(run_id))
        except DiagnosisStateError as exc:
            raise MCPError(
                code=INVALID_REQUEST,
                message=str(exc),
                data={"required_step": _required_step(exc), "error": type(exc).__name__},
            ) from exc
        if packet is None:
            payload: dict[str, object] = {"packet": None}
        else:
            # The legend rides alongside the packet so a host can cite the
            # packet's opaque evidence/observation tokens without reading
            # engine source. It never joins the packet's digest-bound identity.
            payload = {
                "packet": packet.model_dump(mode="json"),
                "evidence_legend": [_json_row(row) for row in legend],
            }
        _refuse_hostile_payload(payload)
        return payload


def register_proposal_tool(server: MCPServer, engine: DiagnosisEngine) -> None:
    @server.tool(annotations=_READ_ONLY)
    def submit_specialist_proposal(
        run_id: str,
        packet_id: str,
        proposals: list[dict[str, object]],
    ) -> dict[str, object]:
        """Validate and record one engine-issued packet response."""
        try:
            parsed = tuple(SpecialistProposal.from_mapping(item) for item in proposals)
        except (TypeError, ValueError) as exc:
            # ``parse_specialist_proposal`` raises plain ValueError carrying
            # only fixed rule text plus failing field names — never pydantic
            # messages or submitted values — so exactly that wording may be
            # surfaced verbatim.  Any other exception type keeps the closed
            # sentence: its text could interpolate submitted values.
            message = (
                str(exc)
                if type(exc) is ValueError
                else "specialist proposal is not a closed typed payload"
            )
            raise ToolError(message) from exc
        for item in parsed:
            _refuse_hostile_payload(item.model_dump())
        return _dump_work(engine.submit_work, run_id, packet_id, parsed)


def register_result_tool(server: MCPServer, engine: DiagnosisEngine) -> None:
    @server.tool(annotations=_READ_ONLY)
    def get_diagnosis_result(run_id: str) -> dict[str, object]:
        """Return the closed typed result for one local run."""
        return _dump(engine.result, run_id)


def _register_status_tool(server: MCPServer, engine: DiagnosisEngine) -> None:
    @server.tool(annotations=_READ_ONLY)
    def get_diagnosis_status(run_id: str) -> dict[str, object]:
        """Return proved stages and the next required action for one local run."""
        return _dump(engine.status, run_id)


def _register_advance_tool(server: MCPServer, engine: DiagnosisEngine) -> None:
    @server.tool(annotations=_READ_ONLY)
    def advance_diagnosis(run_id: str) -> dict[str, object]:
        """Perform one lawful read-only diagnosis transition."""
        return _dump(engine.advance, run_id)


def _dump_work(method: Callable[..., StoredResult], *args: object) -> dict[str, object]:
    try:
        payload = method(*args).dump_for_storage()
    except (DiagnosisStateError, WorkQueueError, SpecialistProposalError) as exc:
        raise MCPError(
            code=INVALID_REQUEST,
            message=str(exc),
            data={
                "required_step": _required_step(exc)
                if isinstance(exc, DiagnosisStateError)
                else RequiredStep.REQUIRED_STEP.value,
                "error": type(exc).__name__,
            },
        ) from exc
    _refuse_hostile_payload(payload)
    return payload


def _dump(method: Callable[..., StoredResult], *args: object) -> dict[str, object]:
    try:
        payload = method(*args).dump_for_storage()
    except DiagnosisStateError as exc:
        raise MCPError(
            code=INVALID_REQUEST,
            message=str(exc),
            data={"required_step": _required_step(exc), "error": type(exc).__name__},
        ) from exc
    _refuse_hostile_payload(payload)
    return payload


def _required_step(exc: DiagnosisStateError) -> str:
    typed = getattr(exc, "required_step", RequiredStep.REQUIRED_STEP)
    if isinstance(typed, RequiredStep):
        return typed.value
    return RequiredStep.REQUIRED_STEP.value


_HOSTILE_MESSAGES = {
    REMOVE_SECRET: "secret material is not retained on the MCP wire",
    REMOVE_ABSOLUTE_PATH: "absolute paths are not retained on the MCP wire",
}


def _refuse_hostile_payload(payload: object) -> None:
    try:
        refuse_hostile_payload(payload)
    except HostilePayloadError as exc:
        raise MCPError(
            code=INVALID_REQUEST,
            message=_HOSTILE_MESSAGES[exc.required_step],
            data={"required_step": exc.required_step, "error": "HostilePayload"},
        ) from exc


def _forbid_unknown_tool_fields(server: MCPServer) -> None:
    """SDK argument models ignore extras; diagnosis tools must refuse them."""

    for tool in server._tool_manager.list_tools():  # noqa: SLF001 - translation lock
        locked = type(
            f"{tool.fn_metadata.arg_model.__name__}Locked",
            (tool.fn_metadata.arg_model,),
            {"model_config": ConfigDict(extra="forbid")},
        )
        tool.fn_metadata.arg_model = locked
        schema = locked.model_json_schema(by_alias=True)
        schema["additionalProperties"] = False
        tool.parameters = schema
