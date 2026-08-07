"""The M1 egress harness (HANDOFF 5.2, Linux-testable layer; gates.md G2).

Runs a full inspection over a fixture system seeded with unique canary
strings, **inside the containment wrapper**, and asserts:

(a) the containment subprocess cannot open sockets — proven both by the
    child's own pre-read probes and by a separate test probe run under the
    same strategy attempting exactly that;
(b) canaries and their derivations (SHA-256 of the canary, substrings)
    appear nowhere in any serialized envelope, log line, or crash output.

At M1 there is no approved default-path network flow at all (catalog
refresh arrives with its D8 decision); the approved-egress set is empty,
so the assertion is total: nothing observable may carry canary material,
and the inspection process must be incapable of opening a socket in the
first place. OS-level packet capture joins at M3 when a real journey
exists; here the syscall layer is the wire.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from tests.fixtures.hostile.catalog import (
    CANARY_API_TOKEN,
    CANARY_AWS_KEY_ID,
    CANARY_AWS_SECRET,
    CANARY_PERSONAL_STRING,
    CANARY_PRIVATE_KEY_BLOCK,
    assert_no_canary_leak,
    build_benign_system,
)

from capability_exchange.adapters.claude_code import contained

#: A personal-string canary planted as a file's ENTIRE content: any unkeyed
#: content hash in the envelope would then be sha256(canary) — a verifiable
#: derivation (G2 counts hashes of canaries as canary material).
WHOLE_FILE_CANARY = CANARY_PERSONAL_STRING

#: The canaries this harness plants and hunts, with their derivations.
EGRESS_CANARIES: tuple[str, ...] = (
    CANARY_AWS_KEY_ID,
    CANARY_AWS_SECRET,
    CANARY_API_TOKEN,
    CANARY_PERSONAL_STRING,
)


def build_canary_system(base: Path) -> Path:
    """A synthetic system with canaries in every collection-relevant spot:
    secret-shaped (redacted at collection), personal non-secret-shaped
    (bounded by the data boundary alone), and one whole-file canary whose
    unkeyed hash would equal the canary's own hash."""
    root = build_benign_system(base)
    (root / "CLAUDE.md").write_bytes(WHOLE_FILE_CANARY.encode())
    (root / "notes.md").write_text(
        f"Weekly review. Remember {CANARY_PERSONAL_STRING} for the retro.\n"
    )
    (root / ".claude" / "ops.env").write_text(
        f"AWS_ACCESS_KEY_ID={CANARY_AWS_KEY_ID}\n"
        f"AWS_SECRET_ACCESS_KEY={CANARY_AWS_SECRET}\n"
        f"OPENAI_API_KEY={CANARY_API_TOKEN}\n"
        f"{CANARY_PRIVATE_KEY_BLOCK}"
    )
    return root


@dataclass(frozen=True, slots=True)
class ContainedRunCapture:
    """Everything observable from one contained child run."""

    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def observable_output(self) -> bytes:
        return self.stdout + b"\n" + self.stderr


def run_contained_child(
    approved_roots: list[str],
    *,
    containment_mode: str = "self",
    bounds_payload: dict[str, object] | None = None,
    timeout: float = 120.0,
) -> ContainedRunCapture:
    """Run the real contained child process and capture every byte it emits.

    This is the same entry point the containment strategies launch —
    stdout carries the serialized result, stderr carries every log line;
    together they are the complete observable surface of one inspection.
    """
    request: dict[str, object] = {
        "schema": contained.REQUEST_SCHEMA,
        "approved_roots": approved_roots,
    }
    if bounds_payload is not None:
        request["bounds"] = bounds_payload
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "capability_exchange.adapters.claude_code.contained_entry",
            "--containment",
            containment_mode,
        ],
        input=json.dumps(request).encode(),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return ContainedRunCapture(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def assert_capture_leak_free(capture: ContainedRunCapture, *, context: str) -> None:
    """No canary, substring, or sha256 derivation in anything the run emitted."""
    assert_no_canary_leak(capture.observable_output, EGRESS_CANARIES, context=context)


#: A probe run under the same confinement the collection child uses: it
#: attempts to open sockets (TCP, UDP, IPv6) and reports every refusal.
SOCKET_PROBE_SOURCE = textwrap.dedent(
    """
    import socket, sys
    from capability_exchange.adapters.claude_code.contained import (
        confine_this_process,
    )
    confine_this_process()
    escapes = []
    for family, kind in (
        (socket.AF_INET, socket.SOCK_STREAM),
        (socket.AF_INET, socket.SOCK_DGRAM),
        (socket.AF_INET6, socket.SOCK_STREAM),
    ):
        try:
            sock = socket.socket(family, kind)
        except PermissionError:
            continue
        try:
            sock.settimeout(0.25)
            sock.connect(("127.0.0.1", 9))
            escapes.append(f"connected({family},{kind})")
        except PermissionError:
            pass
        except OSError:
            escapes.append(f"socket-created({family},{kind})")
        finally:
            sock.close()
    if escapes:
        print("; ".join(escapes), file=sys.stderr)
        sys.exit(1)
    print("all-socket-attempts-refused")
    sys.exit(0)
    """
)


def run_socket_probe_under_linux_strategy(timeout: float = 60.0) -> ContainedRunCapture:
    """Attempt sockets from inside the same self-confinement the Linux
    strategy applies to the collection child."""
    completed = subprocess.run(
        [sys.executable, "-c", SOCKET_PROBE_SOURCE],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return ContainedRunCapture(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
