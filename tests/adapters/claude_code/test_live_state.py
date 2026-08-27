"""Optional operating-system status uses fixed read-only commands only."""

from __future__ import annotations

from capability_exchange.adapters.claude_code import live_state
from capability_exchange.diagnosis.observations import OperationalState


def test_live_probe_uses_fixed_argv_and_never_runs_vault_commands(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(live_state, "_run", lambda argv: calls.append(tuple(argv)) or "")

    live_state.collect_live_states(platform="darwin")

    assert calls == [("launchctl", "list")]


def test_linux_live_probe_uses_one_fixed_systemd_command(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(live_state, "_run", lambda argv: calls.append(tuple(argv)) or "")

    live_state.collect_live_states(platform="linux")

    assert calls == [
        ("systemctl", "--user", "list-units", "--no-legend", "--no-pager")
    ]


def test_launchctl_output_only_retains_job_identity_and_loaded_state(monkeypatch) -> None:
    monkeypatch.setattr(
        live_state,
        "_run",
        lambda _argv: "PID\tStatus\tLabel\n491\t0\tnightly-check\n-\t0\tchangelog-check\n",
    )

    states = live_state.collect_live_states(platform="darwin")

    assert [(item.identity, item.operational_state) for item in states] == [
        ("changelog-check", OperationalState.LOADED),
        ("nightly-check", OperationalState.LOADED),
    ]
