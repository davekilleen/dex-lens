"""M5 contribution egress is exactly the approved disclosure bytes."""

from __future__ import annotations

import inspect
import socket
from pathlib import Path

import pytest
from tests.cards.test_model import make_card
from tests.concierge.test_adaptation_journey import _journey
from tests.concierge.test_contribution_journey import (
    RecordingIdentity,
    RecordingIntake,
    _permissions,
    _reach_approval,
)

from capability_exchange.concierge.journey import ContributionIntakePort
from capability_exchange.contribution import InMemoryStore


def test_intake_contract_has_one_positional_payload_and_no_transport_wrapper() -> None:
    parameters = tuple(inspect.signature(ContributionIntakePort.submit).parameters.values())
    assert tuple(parameter.name for parameter in parameters) == ("self", "payload", "handle")
    assert parameters[1].kind is inspect.Parameter.POSITIONAL_ONLY
    assert parameters[1].annotation in {bytes, "bytes"}
    assert parameters[2].kind is inspect.Parameter.KEYWORD_ONLY


def test_m5_egress_equals_disclosure_payload_bytes_and_opens_no_socket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity = RecordingIdentity()
    intake = RecordingIntake()
    journey = _journey(tmp_path)
    journey.configure_contribution(
        identity=identity,
        intake=intake,
        stores=(InMemoryStore("exchange-cards"),),
    )
    _, manifest = _reach_approval(journey)
    journey.approve_contribution(_permissions())

    socket_attempts: list[object] = []

    def refuse_socket(_sock: socket.socket, address: object) -> None:
        socket_attempts.append(address)
        raise AssertionError("stage 9 may egress only through the injected intake port")

    monkeypatch.setattr(socket.socket, "connect", refuse_socket)
    journey.submit_contribution()

    assert socket_attempts == []
    assert intake.submissions == [(manifest.payload_bytes,)]
    (only_call,) = intake.submissions
    assert len(only_call) == 1
    assert type(only_call[0]) is bytes
    assert only_call[0] == manifest.payload_bytes
    assert b"headers" not in only_call[0]
    assert b"body" not in only_call[0]
    assert b"card_version_hash" not in only_call[0]


def test_no_contribution_choice_means_zero_identity_and_zero_egress(tmp_path: Path) -> None:
    identity = RecordingIdentity()
    intake = RecordingIntake()
    journey = _journey(tmp_path)
    journey.configure_contribution(
        identity=identity,
        intake=intake,
        stores=(InMemoryStore("exchange-cards"),),
    )

    assert journey.capability_map is not None
    assert identity.calls == 0
    assert intake.submissions == []
    assert make_card().version_hash not in journey.capability_map_markdown


def test_ci_runs_the_exact_m5_contribution_egress_gate() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "M5 exact contribution egress" in workflow
    assert "tests/egress/test_m5_contribution_egress.py" in workflow
