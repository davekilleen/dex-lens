"""Optional fixed read-only operating-system status probes.

No inspected value can influence an executable, argument, environment value,
or shell. The only two commands in this module are product-authored tuples.
Failures return no state, which leaves the fingerprint honestly unassessed.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from capability_exchange.diagnosis.observations import HealthState, OperationalState, RuntimeState

__all__ = ["LiveState", "collect_live_states"]

_DARWIN_COMMAND = ("launchctl", "list")
_LINUX_COMMAND = (
    "systemctl",
    "--user",
    "list-units",
    "--no-legend",
    "--no-pager",
)
_MINIMAL_ENVIRONMENT = {"PATH": "/usr/bin:/bin"}


@dataclass(frozen=True, slots=True)
class LiveState:
    """One job identity the operating system says is currently loaded."""

    kind: str
    identity: str
    runtime_state: RuntimeState
    captured_at: datetime
    health_state: HealthState = HealthState.NOT_ASSESSED
    source_id: str | None = None

    def __init__(
        self,
        kind: str,
        identity: str,
        runtime_state: RuntimeState | str | None = None,
        captured_at: datetime | None = None,
        *,
        operational_state: OperationalState | str | None = None,
        health_state: HealthState | str = HealthState.NOT_ASSESSED,
        source_id: str | None = None,
    ) -> None:
        """Build a runtime-only status record.

        ``operational_state`` is accepted only for old callers; the record
        stores ``runtime_state`` and never carries the collapsed scalar.
        """

        if runtime_state is not None and operational_state is not None:
            raise ValueError("live state cannot carry both runtime and operational state")
        selected = runtime_state if runtime_state is not None else operational_state
        if selected is None:
            raise ValueError("live state requires a runtime state")
        if captured_at is None:
            raise ValueError("live state requires a capture timestamp")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "runtime_state", RuntimeState(selected))
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "health_state", HealthState(health_state))
        object.__setattr__(self, "source_id", source_id)

    @property
    def operational_state(self) -> OperationalState:
        """Compatibility projection; live state is persisted as runtime only."""

        try:
            return OperationalState(self.runtime_state.value)
        except ValueError:
            return OperationalState.NOT_ASSESSED


def _run(argv: tuple[str, ...]) -> str:
    """Run one product-authored status command, never a command from a vault."""
    try:
        completed = subprocess.run(
            argv,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=_MINIMAL_ENVIRONMENT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def _parse_launchctl(output: str, captured_at: datetime) -> tuple[LiveState, ...]:
    states: list[LiveState] = []
    for line in output.splitlines():
        columns = line.split()
        if len(columns) < 3 or columns[-1].lower() == "label":
            continue
        label = columns[-1]
        if not label or any(ord(char) < 0x20 for char in label):
            continue
        states.append(
            LiveState(
                kind="automation",
                identity=label,
                runtime_state=RuntimeState.LOADED,
                captured_at=captured_at,
            )
        )
    return tuple(sorted(states, key=lambda item: item.identity))


def _parse_systemd(output: str, captured_at: datetime) -> tuple[LiveState, ...]:
    states: list[LiveState] = []
    for line in output.splitlines():
        columns = line.split(maxsplit=4)
        if len(columns) < 4:
            continue
        unit, load, active, _sub = columns[:4]
        if load != "loaded" or active not in {"active", "activating", "reloading"}:
            continue
        if not unit.endswith((".service", ".timer")):
            continue
        identity = unit.rsplit(".", 1)[0]
        states.append(
            LiveState(
                kind="automation",
                identity=identity,
                runtime_state=RuntimeState.LOADED,
                captured_at=captured_at,
            )
        )
    return tuple(sorted(states, key=lambda item: item.identity))


def collect_live_states(
    *,
    platform: str = sys.platform,
    scope_receipt: object | None = None,
) -> tuple[LiveState, ...]:
    """Ask the host whether scheduled jobs are loaded, using fixed commands.

    When a receipt is supplied, live collection is permitted only when that
    receipt explicitly includes ``include_live_state``.  The no-receipt form
    remains a compatibility path for the standalone inventory command; the
    diagnosis flow always supplies its approved receipt before collecting.
    """

    if scope_receipt is not None and not bool(
        getattr(scope_receipt, "include_live_state", False)
    ):
        return ()
    captured_at = datetime.now(UTC)
    if platform == "darwin":
        return _parse_launchctl(_run(_DARWIN_COMMAND), captured_at)
    if platform.startswith("linux"):
        return _parse_systemd(_run(_LINUX_COMMAND), captured_at)
    return ()
