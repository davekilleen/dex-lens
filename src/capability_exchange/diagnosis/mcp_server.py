"""Thin read-only MCP v2 stdio adapter over an injected diagnosis engine.

The adapter contains translation only. Diagnosis rules, collection, consent
issuance and report rendering stay behind the engine Protocol. Task 8 supplies
the real orchestrator; tests and later adapters inject a fake the same way.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import INVALID_REQUEST, ToolAnnotations
from pydantic import ConfigDict

from capability_exchange.diagnosis.run import DiagnosisStateError

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
    "main",
]

EXPECTED_TOOLS = {
    "prepare_diagnosis",
    "get_diagnosis_status",
    "advance_diagnosis",
    "submit_specialist_proposal",
    "get_diagnosis_result",
}
FORBIDDEN_TOOL_SUBSTRINGS = ("write", "delete", "install", "repair", "share", "send")
_SESSION_CANARY = "INVENTED_SESSION_CANARY_NEVER_RETAIN"
_ABSOLUTE_PATH = re.compile(r"(?:/Users/|/home/|/private/|[A-Za-z]:\\)")
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


@dataclass(frozen=True)
class SpecialistProposal:
    """Translation-only wire shape. Task 7 owns the real proposal schema."""

    claims: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: dict[str, object]) -> SpecialistProposal:
        extra = set(payload) - {"claims"}
        if extra:
            raise ValueError("unknown fields are forbidden on specialist proposals")
        claims = payload.get("claims", ())
        if not isinstance(claims, list | tuple):
            raise ValueError("specialist proposal claims must be a sequence")
        if not all(isinstance(item, str) for item in claims):
            raise ValueError("specialist proposal claims must be strings")
        return cls(claims=tuple(str(item) for item in claims))

    def model_dump(self) -> dict[str, object]:
        return {"claims": list(self.claims)}


@runtime_checkable
class StoredResult(Protocol):
    def dump_for_storage(self) -> dict[str, Any]: ...


@runtime_checkable
class DiagnosisEngine(Protocol):
    """The same small interface Task 9 will inject against."""

    def prepare(self, request: PrepareDiagnosisRequest) -> StoredResult: ...
    def status(self, run_id: str) -> StoredResult: ...
    def advance(self, run_id: str) -> StoredResult: ...
    def submit(self, run_id: str, proposal: object) -> StoredResult: ...
    def result(self, run_id: str) -> StoredResult: ...


def canonical_result_bytes(payload: object) -> bytes:
    """Sorted compact JSON bytes used for engine-vs-MCP equality."""

    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def build_engine() -> DiagnosisEngine:
    """Injectable factory. Task 8 owns real construction; this slice does not."""

    raise DiagnosisStateError(
        "diagnosis MCP adapter requires an injected engine; "
        "the Task 8 orchestrator is not available in this slice"
    )


def build_mcp_server(engine: DiagnosisEngine) -> MCPServer:
    server = MCPServer("dex-lens-diagnosis")
    _register_status_tool(server, engine)
    _register_advance_tool(server, engine)
    register_prepare_tool(server, engine)
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


def register_proposal_tool(server: MCPServer, engine: DiagnosisEngine) -> None:
    @server.tool(annotations=_READ_ONLY)
    def submit_specialist_proposal(run_id: str, proposal: dict[str, object]) -> dict[str, object]:
        """Offer typed, evidence-referenced semantic help for later validation."""
        try:
            parsed = SpecialistProposal.from_mapping(proposal)
        except (TypeError, ValueError) as exc:
            raise ToolError("specialist proposal is not a closed typed payload") from exc
        _refuse_hostile_payload(parsed.model_dump())
        return _dump(engine.submit, run_id, parsed)


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
    text = str(exc).lower()
    if "approve" in text or "scope" in text or "consent" in text:
        return "approve_scope"
    return "required_step"


def _refuse_hostile_payload(payload: object) -> None:
    for text in _string_values(payload):
        if _SESSION_CANARY in text:
            raise MCPError(
                code=INVALID_REQUEST,
                message="secret material is not retained on the MCP wire",
                data={"required_step": "remove_secret", "error": "HostilePayload"},
            )
        if _ABSOLUTE_PATH.search(text):
            raise MCPError(
                code=INVALID_REQUEST,
                message="absolute paths are not retained on the MCP wire",
                data={"required_step": "remove_absolute_path", "error": "HostilePayload"},
            )


def _string_values(payload: object) -> list[str]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        found: list[str] = []
        for key, value in payload.items():
            if isinstance(key, str):
                found.append(key)
            found.extend(_string_values(value))
        return found
    if isinstance(payload, list | tuple):
        found: list[str] = []
        for item in payload:
            found.extend(_string_values(item))
        return found
    return []


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
