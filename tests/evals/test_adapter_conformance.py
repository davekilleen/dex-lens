"""The same sanitised replay is byte-identical through every adapter."""

from __future__ import annotations

import json
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
from capability_exchange.diagnosis.specialists import candidate_id_for
from capability_exchange.diagnosis.work import NORMAL_ROLES, AnalysisMode
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
        engine = self.harness.engine
        packets = engine.pending_work(self.harness.bundle.run_id)
        if not packets:
            payload: dict[str, object] = {"packet": None, "packets": []}
        else:
            dumped = [item.model_dump(mode="json") for item in packets]
            payload = {
                "packet": dumped[0],
                "packets": dumped,
                "evidence_legend": [
                    row.model_dump(mode="json")
                    for row in engine.work_context(self.harness.bundle.run_id)
                ],
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


def _cli_work_payload(harness: ReplayHarness) -> dict[str, object]:
    diagnosis_cli.bind_consent_surface(_SilentSession(), _SilentServer())
    try:
        with patch.object(diagnosis_cli, "build_engine", lambda: harness.engine):
            return _cli_json(["work", "--run", harness.bundle.run_id, "--json"])
    finally:
        diagnosis_cli.reset_consent_surface()


def test_work_json_legend_maps_every_packet_token_to_its_observation(
    conformance: AdapterHarness,
) -> None:
    """The legend explains exactly the opaque tokens the packet lets a host cite."""

    payload = _cli_work_payload(conformance.harness)
    packet = payload["packet"]
    assert isinstance(packet, dict)
    legend = payload["evidence_legend"]
    assert isinstance(legend, list)
    fingerprint = conformance.harness.bundle.fingerprint
    assert len(legend) == len(fingerprint.observations)
    assert [row["evidence_id"] for row in legend] == sorted(packet["evidence_ids"])
    rows_by_observation = {row["observation_id"]: row for row in legend}
    for observation in fingerprint.observations:
        row = rows_by_observation[observation.observation_id]
        assert row == {
            "evidence_id": row["evidence_id"],
            "observation_id": observation.observation_id,
            "kind": observation.kind.value,
            "identity": observation.identity,
            "label": observation.label,
            "relative_reference": observation.provenance.relative_reference,
            "source_class": observation.provenance.source_class.value,
        }


def test_a_host_can_cite_and_submit_using_only_the_work_payload(
    conformance: AdapterHarness,
    tmp_path: Path,
) -> None:
    """Acceptance: the legend alone lets a host construct an accepted proposal.

    Everything below comes from the ``work --json`` payload plus the public
    closed vocabulary — no reading of engine source, no hand-minted tokens.
    """

    harness = conformance.harness
    payload = _cli_work_payload(harness)
    packet = payload["packet"]
    assert isinstance(packet, dict)
    row = payload["evidence_legend"][0]
    catalogue_id = packet["catalogue_ids"][0]
    capability_id = packet["capability_ids"][0]
    proposal = {
        "role": packet["role"],
        "kind": "mapping",
        "run_id": packet["run_id"],
        "fingerprint_digest": packet["fingerprint_digest"],
        "catalogue_digest": packet["catalogue_digest"],
        "packet_id": packet["packet_id"],
        "packet_digest": packet["packet_digest"],
        "catalogue_id": catalogue_id,
        "capability_id": capability_id,
        "candidate_id": candidate_id_for("mapping", catalogue_id, capability_id),
        "disposition": "shared",
        "evidence_ids": [row["evidence_id"]],
        "observation_ids": [row["observation_id"]],
        "reason": (
            f"The approved evidence for {row['identity']} matches this catalogue method."
        ),
    }
    path = tmp_path / "cited-proposal.json"
    path.write_text(json.dumps(proposal), encoding="utf-8")
    diagnosis_cli.bind_consent_surface(_SilentSession(), _SilentServer())
    try:
        with patch.object(diagnosis_cli, "build_engine", lambda: harness.engine):
            view = _cli_json(
                [
                    "submit",
                    "--run",
                    harness.bundle.run_id,
                    "--packet",
                    str(packet["packet_id"]),
                    "--proposal",
                    str(path),
                ]
            )
            after = _cli_json(["work", "--run", harness.bundle.run_id, "--json"])
    finally:
        diagnosis_cli.reset_consent_surface()
    assert view["stage"] == DiagnosisStage.ANALYSIS_PLANNED.value
    next_packet = after["packet"]
    assert isinstance(next_packet, dict)
    assert next_packet["packet_id"] != packet["packet_id"]


def _cli_call(harness: ReplayHarness, argv: list[str]) -> dict[str, object]:
    diagnosis_cli.bind_consent_surface(_SilentSession(), _SilentServer())
    try:
        with patch.object(diagnosis_cli, "build_engine", lambda: harness.engine):
            return _cli_json(argv)
    finally:
        diagnosis_cli.reset_consent_surface()


def test_work_payload_lists_every_pending_normal_packet(
    conformance: AdapterHarness,
) -> None:
    """One ``work --json`` fetch hands a host the whole legal round at once."""

    payload = _cli_work_payload(conformance.harness)
    packets = payload["packets"]
    assert isinstance(packets, list)
    assert [item["role"] for item in packets] == [role.value for role in NORMAL_ROLES]
    assert packets[0] == payload["packet"]
    assert "sceptical-reconciler" not in {item["role"] for item in packets}


def test_work_payload_carries_exactly_one_legend_and_packets_carry_none(
    conformance: AdapterHarness,
) -> None:
    """The 282-row legend problem: the legend appears once, never per packet."""

    payload = _cli_work_payload(conformance.harness)
    assert payload["evidence_legend"]
    packets = payload["packets"]
    assert isinstance(packets, list) and packets
    assert all("evidence_legend" not in item for item in packets)
    assert canonical_work_bytes(payload).count(b'"evidence_legend"') == 1


def test_sceptical_packet_joins_the_list_alone_only_after_normals_are_final(
    conformance: AdapterHarness,
) -> None:
    """While any normal packet is pending the list excludes sceptical work;
    once every normal receipt is final the sceptical packet is the only entry."""

    harness = conformance.harness
    run_id = harness.bundle.run_id
    payload = _cli_work_payload(harness)
    normals = payload["packets"]
    assert [item["role"] for item in normals] == [role.value for role in NORMAL_ROLES]

    for item in normals[:-1]:
        _cli_call(
            harness,
            ["submit", "--run", run_id, "--packet", str(item["packet_id"])],
        )
    one_left = _cli_work_payload(harness)
    assert [item["role"] for item in one_left["packets"]] == [normals[-1]["role"]]
    assert "sceptical-reconciler" not in {
        item["role"] for item in one_left["packets"]
    }

    _cli_call(
        harness,
        ["submit", "--run", run_id, "--packet", str(normals[-1]["packet_id"])],
    )
    unlocked = _cli_work_payload(harness)
    assert [item["role"] for item in unlocked["packets"]] == ["sceptical-reconciler"]
    assert unlocked["packet"]["role"] == "sceptical-reconciler"

    _cli_call(
        harness,
        [
            "submit",
            "--run",
            run_id,
            "--packet",
            str(unlocked["packet"]["packet_id"]),
        ],
    )
    drained = _cli_work_payload(harness)
    assert drained == {"packet": None, "packets": []}


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
