"""G2/G1 egress tests for the macOS sandbox-exec containment layer.

Runs only on darwin (the CI Actions matrix covers macOS; HANDOFF M1 —
macOS enforcement with a Linux-testable abstraction elsewhere). Mirrors
the Linux-layer harness: socket refusal probed under the same strategy,
and a full contained inspection whose observable output is canary-free.

Every darwin test tolerates exactly one alternative outcome: the honest
G1 refusal (containment unavailable on this host) — never a silent,
uncontained collection.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from tests.egress.harness import build_canary_system
from tests.fixtures.hostile.catalog import assert_no_canary_leak

from capability_exchange.adapters.claude_code.containment import (
    _MACOS_PROFILE_PATH,
    CollectionRequest,
    ContainmentUnavailableError,
    MacOSStrategy,
    macos_profile_params,
)

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin", reason="sandbox-exec profile tests run on darwin only"
)

#: The proof probe run under the shipped .sb profile: sockets, write-opens,
#: and shell exec must all be denied (same machinery the child uses).
PROFILE_PROBE_SOURCE = textwrap.dedent(
    """
    from capability_exchange.adapters.claude_code.contained import prove_containment
    proofs = prove_containment()
    print(";".join(proofs))
    """
)


def _sandbox_exec_argv(python_source: str) -> list[str]:
    # Same parameter set the adapter uses. Built from the shared helper rather
    # than restated here: a drifted copy would let the profile pass its own
    # test while the real inspection child dies in posix_spawn.
    sandbox_exec = shutil.which("sandbox-exec")
    assert sandbox_exec is not None
    return [
        sandbox_exec,
        *macos_profile_params(),
        "-f",
        str(_MACOS_PROFILE_PATH),
        sys.executable,
        "-c",
        python_source,
    ]


class TestProfileExecSetIsEnumerated:
    """Runs on every platform: the profile is shipped data, not host state.

    G1 allows exec of an enumerated interpreter set. These assertions are the
    structural guard on that — a later "just allow the prefix" fix would turn
    the exec allowance into a trusted directory and would fail here rather
    than pass quietly on a green macOS leg.
    """

    def test_g1_profile_allows_exec_only_by_literal(self) -> None:
        text = _MACOS_PROFILE_PATH.read_text()
        allow_exec = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("(allow process-exec")
        ]
        assert allow_exec, "profile must allow the interpreter itself"
        for line in allow_exec:
            assert "(literal (param " in line, f"non-literal exec allowance: {line}"
            assert "subpath" not in line, f"subpath exec allowance widens G1: {line}"

    def test_g1_every_referenced_param_is_supplied(self) -> None:
        text = _MACOS_PROFILE_PATH.read_text()
        referenced = set(re.findall(r'\(param "([A-Z]+)"\)', text))
        supplied = {
            arg.split("=", 1)[0] for arg in macos_profile_params() if not arg.startswith("-")
        }
        # sandbox-exec fails to compile the profile if any referenced
        # parameter is undefined, which would surface as an opaque
        # containment failure rather than a named one.
        assert referenced <= supplied, f"undefined profile params: {referenced - supplied}"

    def test_g1_params_name_only_interpreter_binaries(self) -> None:
        values = [arg.split("=", 1)[1] for arg in macos_profile_params() if not arg.startswith("-")]
        assert values, "no interpreter literals supplied"
        for value in values:
            assert "python" in Path(value).name.lower(), f"non-interpreter exec literal: {value}"


@darwin_only
class TestSandboxProfileDenials:
    def test_g2_profile_file_ships_with_the_adapter(self) -> None:
        assert _MACOS_PROFILE_PATH.is_file()
        text = _MACOS_PROFILE_PATH.read_text()
        assert "(deny network*)" in text
        assert "(deny file-write*)" in text
        assert "(deny process-exec*)" in text

    def test_g2_socket_write_and_exec_denied_under_the_profile(self) -> None:
        if shutil.which("sandbox-exec") is None:
            pytest.skip("sandbox-exec not present on this darwin host")
        completed = subprocess.run(
            _sandbox_exec_argv(PROFILE_PROBE_SOURCE),
            capture_output=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode()
        proofs = set(completed.stdout.decode().strip().split(";"))
        assert {"write-open-denied", "exec-denied"} <= proofs
        assert proofs & {"socket-denied", "connect-denied"}


@darwin_only
class TestContainedInspectionLeakFreeOnDarwin:
    def test_g2_full_inspection_output_carries_no_canary_derivations(
        self, tmp_path: Path
    ) -> None:
        canary_root = build_canary_system(tmp_path)
        try:
            result = MacOSStrategy().collect_contained(
                CollectionRequest(approved_roots=(str(canary_root),))
            )
        except ContainmentUnavailableError as refusal:
            # The honest G1 downgrade — and even the refusal text must be
            # canary-free.
            assert_no_canary_leak(str(refusal), context="refusal message")
            return
        assert result.outcome.os_enforced
        assert "socket-denied" in result.outcome.proofs
        assert_no_canary_leak(
            result.envelope.model_dump_json(), context="serialized envelope"
        )
