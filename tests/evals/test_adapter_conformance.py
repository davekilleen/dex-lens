"""The same sanitised replay is byte-identical through every adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import anyio
import pytest
from mcp import Client
from tests.evals.real_session_fixture import CANARY
from tests.evals.test_real_session_replay import real_session_replay

from capability_exchange.diagnosis import cli as diagnosis_cli
from capability_exchange.diagnosis.mcp_server import (
    EXPECTED_TOOLS,
    build_mcp_server,
    canonical_work_bytes,
)
from capability_exchange.diagnosis.run import DiagnosisStage
from capability_exchange.diagnosis.work import AnalysisMode
from capability_exchange.evaluation.replay import (
    ReplayHarness,
    _cli_json,
    _tool_payload,
    run_cli,
    run_direct,
    run_mcp,
)


@dataclass
class AdapterHarness:
    """One guided run stopped at analysis planning for work-byte equality."""

    harness: ReplayHarness

    def direct_work_bytes(self) -> bytes:
        packet = self.harness.engine.work(self.harness.bundle.run_id)
        payload = {
            "packet": None
            if packet is None
            else packet.model_dump(mode="json")
        }
        return canonical_work_bytes(payload)

    def cli_work_bytes(self) -> bytes:
        diagnosis_cli.bind_consent_surface(_SilentSession(), _SilentServer())
        try:
            with patch.object(diagnosis_cli, "build_engine", lambda: self.harness.engine):
                payload = _cli_json(
                    ["work", "--run", self.harness.bundle.run_id, "--json"]
                )
        finally:
            diagnosis_cli.reset_consent_surface()
        return canonical_work_bytes(payload)

    def mcp_work_bytes(self) -> bytes:
        return anyio.run(self._mcp_work_bytes)

    async def _mcp_work_bytes(self) -> bytes:
        server = build_mcp_server(self.harness.engine)
        async with Client(server, raise_exceptions=True) as client:
            result = await client.call_tool(
                "get_diagnosis_work",
                {"run_id": self.harness.bundle.run_id},
            )
        return canonical_work_bytes(_tool_payload(result))


class _SilentSession:
    pass


class _SilentServer:
    pass


@pytest.fixture
def conformance(tmp_path: Path) -> AdapterHarness:
    replay = real_session_replay(ordering="forward")
    harness = ReplayHarness(
        replay,
        tmp_path,
        analysis_mode=AnalysisMode.GUIDED,
    )
    harness.prepare()
    harness.run_to(DiagnosisStage.ANALYSIS_PLANNED)
    return AdapterHarness(harness=harness)


def test_mcp_exposes_exactly_six_read_only_diagnosis_tools() -> None:
    from tests.diagnosis.test_mcp_server import fake_engine

    server = build_mcp_server(fake_engine())
    assert {tool.name for tool in server._tool_manager.list_tools()} == EXPECTED_TOOLS  # noqa: SLF001


def test_direct_cli_and_mcp_return_identical_work_bytes(conformance: AdapterHarness) -> None:
    assert conformance.direct_work_bytes() == conformance.cli_work_bytes()
    assert conformance.cli_work_bytes() == conformance.mcp_work_bytes()


@pytest.mark.parametrize("ordering", ["forward", "reverse", "rotated"])
def test_canonical_result_is_transport_and_order_invariant(ordering: str) -> None:
    replay = real_session_replay(ordering=ordering)
    outputs = {
        run_direct(replay),
        run_cli(replay),
        run_mcp(replay),
    }
    assert len(outputs) == 1
    payload = next(iter(outputs))
    assert CANARY.encode() not in payload


def test_fake_hosts_discover_mcp_tools_in_different_order() -> None:
    replay = real_session_replay(ordering="forward")
    claude = run_mcp(replay, discover="claude")
    codex = run_mcp(replay, discover="codex")
    listed = run_mcp(replay, discover="listed")
    assert claude == codex == listed
    assert CANARY.encode() not in claude
