"""The same sanitised replay is byte-identical through every adapter."""

from __future__ import annotations

import pytest
from tests.evals.real_session_fixture import CANARY
from tests.evals.test_real_session_replay import real_session_replay

from capability_exchange.evaluation.replay import run_cli, run_direct, run_mcp


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
