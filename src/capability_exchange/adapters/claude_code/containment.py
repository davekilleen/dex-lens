"""OS-level containment strategies for the deep adapter (gates.md G1).

The evidence collection never runs in this (parent) process: a
:class:`ContainmentStrategy` launches it in a subprocess whose containment
is enforced at the OS capability level and **proven by runtime probes**
before any target read (see :mod:`.contained`):

- :class:`LinuxStrategy` — the child self-confines with a seccomp BPF
  filter (sockets, exec, and write-capable opens denied at the syscall
  level) plus a network namespace where the kernel permits.
- :class:`MacOSStrategy` — the child is wrapped in ``sandbox-exec`` with
  the shipped ``.sb`` profile denying network, file writes, and
  process-exec of anything but the interpreter.
- :class:`TestStrategy` — in-process, **no OS enforcement**; exists so unit
  tests can drive the allowlist → snapshot → collector pipeline directly.
  It refuses to operate outside a pytest run and is never returned by
  :func:`default_strategy`.

Fail closed (G1): if containment cannot be established or proven, the deep
adapter is disabled for this host — :class:`ContainmentUnavailableError`
carries the honest guided/export-assisted fallback message, and no read of
the person's system has happened. A child that dies mid-collection
discards its partials with its own memory; the parent never receives or
reconstructs them.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from capability_exchange.adapter import AdapterResultEnvelope
from capability_exchange.adapters.claude_code import contained
from capability_exchange.adapters.claude_code.contract import (
    CLAUDE_CODE_ADAPTER_ID,
    claude_code_contract,
)
from capability_exchange.adapters.claude_code.snapshot import CollectionBounds

__all__ = [
    "GUIDED_FALLBACK_MESSAGE",
    "CollectionFailedError",
    "CollectionRequest",
    "ContainedCollection",
    "ContainmentOutcome",
    "ContainmentStrategy",
    "ContainmentUnavailableError",
    "LinuxStrategy",
    "MacOSStrategy",
    "TestStrategy",
    "contained_inspection",
    "default_strategy",
]

#: The honest fallback reported whenever the deep adapter disables itself.
GUIDED_FALLBACK_MESSAGE = (
    "OS-level containment could not be established on this host, so the "
    "deep adapter is disabled here and nothing was read. This source alpha "
    "cannot diagnose on this host; its future guided, export-assisted path "
    "will label evidence Supported/Reported/Unknown, never Verified."
)

_MACOS_PROFILE_PATH = Path(__file__).resolve().parent / "profiles" / "claude_code_containment.sb"


def macos_profile_params(executable: str | None = None) -> list[str]:
    """The ``-D`` parameters the shipped ``.sb`` profile expects.

    The profile allows ``process-exec`` on an explicit, enumerated set of
    interpreter binaries and nothing else. Three are needed, because a
    python.org **framework** build (what the macOS CI leg installs) is not a
    single binary: ``sys.executable`` is a launcher under ``bin/``, its
    realpath is the versioned binary beside it, and the framework re-execs a
    third — ``Resources/Python.app/Contents/MacOS/Python`` — during start-up.
    Denying that third path makes the child die in ``posix_spawn`` before it
    ever runs, which reads as a containment failure rather than what it is.

    These stay three **literals** rather than a subpath over ``sys.prefix``:
    a subpath would admit anything that later appears under the prefix, and
    G1's guarantee is an enumerated exec set, not a trusted directory. No
    shell is reachable through any of the three. A candidate that does not
    exist on this host is still passed (the profile requires every parameter
    it references to be defined); a literal naming a nonexistent path admits
    nothing.
    """
    executable = executable or sys.executable
    real = os.path.realpath(executable)
    framework_app = (
        Path(sys.base_prefix) / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
    )
    return [
        "-D",
        f"PY={executable}",
        "-D",
        f"PYREAL={real}",
        "-D",
        f"PYAPP={framework_app if framework_app.is_file() else real}",
    ]


class ContainmentUnavailableError(Exception):
    """Containment cannot be established/proven: deep adapter disabled.

    Fail closed — the inspection never started, nothing was read, and the
    honest fallback is part of the message.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.fallback_guidance = GUIDED_FALLBACK_MESSAGE
        super().__init__(f"{reason}\n{GUIDED_FALLBACK_MESSAGE}")


class CollectionFailedError(Exception):
    """The contained collection aborted; partials were discarded with it."""


@dataclass(frozen=True, slots=True)
class ContainmentOutcome:
    """What was actually enforced and proven for one collection run."""

    established: bool
    os_enforced: bool
    layers: tuple[str, ...]
    proofs: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ContainedCollection:
    """A completed contained collection: the outcome plus the envelope."""

    outcome: ContainmentOutcome
    envelope: AdapterResultEnvelope


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    """One inspection request: the approved roots and explicit bounds."""

    approved_roots: tuple[str, ...]
    bounds: CollectionBounds = field(default_factory=CollectionBounds)
    timeout_seconds: float = 120.0

    def as_payload(self) -> dict[str, object]:
        return {
            "schema": contained.REQUEST_SCHEMA,
            "approved_roots": list(self.approved_roots),
            "bounds": self.bounds.as_payload(),
        }


class ContainmentStrategy(ABC):
    """One way of establishing OS-level containment for the collection."""

    name: str
    os_enforced: bool

    @abstractmethod
    def availability(self) -> tuple[bool, str]:
        """(available, honest reason when not)."""

    @abstractmethod
    def collect_contained(
        self,
        request: CollectionRequest,
        cancel_event: threading.Event | None = None,
    ) -> ContainedCollection:
        """Collect under containment, or refuse honestly (fail closed)."""


def _child_environment() -> dict[str, str]:
    """A minimal environment for the contained child."""
    environment = {
        "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": "/usr/bin:/bin",
    }
    if "HOME" in os.environ:
        environment["HOME"] = os.environ["HOME"]
    return environment


def _launch_contained_child(
    argv: list[str],
    request: CollectionRequest,
    *,
    layer_reason: str,
    os_enforced: bool,
    cancel_event: threading.Event | None = None,
) -> ContainedCollection:
    """Launch the child (never via a shell), enforce exits, parse the result."""
    try:
        payload = json.dumps(request.as_payload()).encode("utf-8")
        if cancel_event is None:
            completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
                argv,
                input=payload,
                capture_output=True,
                timeout=request.timeout_seconds,
                env=_child_environment(),
                check=False,
            )
        else:
            # ``subprocess.run`` cannot be interrupted by the browser's
            # cancellation request. Keep the child handle so cancellation
            # kills the contained process and stops reads, not just the later
            # result publication.
            process = subprocess.Popen(  # noqa: S603 - fixed argv, shell=False
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_child_environment(),
            )
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.close()
            # ``Popen.communicate`` otherwise tries to flush the closed pipe
            # when collecting output after a cancellation/timeout.
            process.stdin = None
            output: list[tuple[bytes, bytes]] = []
            output_error: list[BaseException] = []

            def drain_output() -> None:
                try:
                    output.append(process.communicate())
                except BaseException as exc:
                    output_error.append(exc)

            drainer = threading.Thread(
                target=drain_output,
                name="dex-lens-contained-output",
                daemon=True,
            )
            drainer.start()
            deadline = time.monotonic() + request.timeout_seconds
            while drainer.is_alive():
                drainer.join(timeout=0.05)
                if not drainer.is_alive():
                    break
                if cancel_event.wait(0.05):
                    process.kill()
                    drainer.join(timeout=5)
                    raise CollectionFailedError(
                        "contained collection cancelled and child was killed; "
                        "partial collection died with the child process"
                    )
                if time.monotonic() >= deadline:
                    process.kill()
                    drainer.join(timeout=5)
                    raise CollectionFailedError(
                        "contained collection timed out and was killed; partial "
                        "collection died with the child process"
                    )
            if output_error:
                raise output_error[0]
            if not output:
                raise CollectionFailedError(
                    "contained collection ended without readable output"
                )
            stdout, stderr = output[0]
            completed = subprocess.CompletedProcess(
                argv, process.returncode, stdout, stderr
            )
    except subprocess.TimeoutExpired as exc:
        raise CollectionFailedError(
            "contained collection timed out and was killed; partial "
            "collection died with the child process"
        ) from exc
    except OSError as exc:
        raise ContainmentUnavailableError(
            f"could not launch the contained collection process "
            f"({type(exc).__name__})"
        ) from exc

    stderr_line = completed.stderr.decode("utf-8", "replace").strip().splitlines()
    stderr_summary = stderr_line[-1] if stderr_line else "(no detail)"
    if completed.returncode == contained.EXIT_CONTAINMENT_UNAVAILABLE:
        raise ContainmentUnavailableError(stderr_summary)
    if completed.returncode != contained.EXIT_OK:
        raise CollectionFailedError(
            f"contained collection aborted (exit {completed.returncode}): "
            f"{stderr_summary}; partials were discarded"
        )

    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
        if payload.get("schema") != contained.RESULT_SCHEMA:
            raise ValueError(f"unexpected result schema {payload.get('schema')!r}")
        envelope = AdapterResultEnvelope.model_validate(payload["envelope"])
        layers = tuple(str(layer) for layer in payload["layers"])
        proofs = tuple(str(proof) for proof in payload["proofs"])
    except (ValueError, KeyError, TypeError) as exc:
        raise CollectionFailedError(
            f"contained collection produced an unparseable result "
            f"({type(exc).__name__}); discarding it (fail closed)"
        ) from exc
    if envelope.adapter_id != CLAUDE_CODE_ADAPTER_ID:
        raise CollectionFailedError(
            f"result envelope names adapter {envelope.adapter_id!r}, not "
            f"{CLAUDE_CODE_ADAPTER_ID!r}; discarding it (fail closed)"
        )
    return ContainedCollection(
        outcome=ContainmentOutcome(
            established=True,
            os_enforced=os_enforced,
            layers=layers,
            proofs=proofs,
            reason=layer_reason,
        ),
        envelope=envelope,
    )


_CHILD_MODULE = "capability_exchange.adapters.claude_code.contained_entry"


class LinuxStrategy(ContainmentStrategy):
    """Linux: child self-confines (seccomp filter, network namespace)."""

    name = "linux-seccomp"
    os_enforced = True

    def availability(self) -> tuple[bool, str]:
        if sys.platform != "linux":
            return (False, f"LinuxStrategy requires Linux, not {sys.platform!r}")
        if platform.machine() not in ("x86_64", "aarch64"):
            return (False, f"no seccomp syscall table for {platform.machine()!r}")
        return (True, "")

    def collect_contained(
        self,
        request: CollectionRequest,
        cancel_event: threading.Event | None = None,
    ) -> ContainedCollection:
        available, reason = self.availability()
        if not available:
            raise ContainmentUnavailableError(reason)
        argv = [sys.executable, "-I", "-m", _CHILD_MODULE, "--containment", "self"]
        return _launch_contained_child(
            argv,
            request,
            layer_reason="child self-confined before any target read; probes proved denial",
            os_enforced=True,
            cancel_event=cancel_event,
        )


class MacOSStrategy(ContainmentStrategy):
    """macOS: child wrapped in sandbox-exec with the shipped .sb profile."""

    name = "macos-sandbox-exec"
    os_enforced = True

    def availability(self) -> tuple[bool, str]:
        if sys.platform != "darwin":
            return (False, f"MacOSStrategy requires macOS, not {sys.platform!r}")
        if shutil.which("sandbox-exec") is None:
            return (False, "sandbox-exec not found on this host")
        if not _MACOS_PROFILE_PATH.is_file():
            return (False, f"containment profile missing at {_MACOS_PROFILE_PATH}")
        return (True, "")

    def collect_contained(
        self,
        request: CollectionRequest,
        cancel_event: threading.Event | None = None,
    ) -> ContainedCollection:
        available, reason = self.availability()
        if not available:
            raise ContainmentUnavailableError(reason)
        sandbox_exec = shutil.which("sandbox-exec")
        assert sandbox_exec is not None
        argv = [
            sandbox_exec,
            *macos_profile_params(),
            "-f",
            str(_MACOS_PROFILE_PATH),
            sys.executable,
            "-I",
            "-m",
            _CHILD_MODULE,
            "--containment",
            "external",
        ]
        return _launch_contained_child(
            argv,
            request,
            layer_reason="sandbox-exec profile denies network, writes, and non-interpreter exec",
            os_enforced=True,
            cancel_event=cancel_event,
        )


class TestStrategy(ContainmentStrategy):
    """In-process pipeline for unit tests. No OS enforcement — ever eligible
    only inside a pytest run, and never selected by :func:`default_strategy`."""

    name = "test-in-process"
    os_enforced = False

    def availability(self) -> tuple[bool, str]:
        if "PYTEST_CURRENT_TEST" not in os.environ:
            return (
                False,
                "TestStrategy provides no OS enforcement and refuses to "
                "operate outside a pytest run (fail closed)",
            )
        return (True, "")

    def collect_contained(
        self,
        request: CollectionRequest,
        cancel_event: threading.Event | None = None,
    ) -> ContainedCollection:
        available, reason = self.availability()
        if not available:
            raise ContainmentUnavailableError(reason)
        if cancel_event is not None and cancel_event.is_set():
            raise CollectionFailedError("contained collection cancelled before it started")
        from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
        from capability_exchange.adapters.claude_code.collector import EvidenceCollector
        from capability_exchange.adapters.claude_code.snapshot import take_snapshot

        contract = claude_code_contract(list(request.approved_roots))
        allowlist = CanonicalAllowlist(contract.read_scope, denied_paths=contract.denied_paths)
        snapshot = take_snapshot(allowlist, bounds=request.bounds)
        envelope = EvidenceCollector(contract, snapshot).collect()
        return ContainedCollection(
            outcome=ContainmentOutcome(
                established=True,
                os_enforced=False,
                layers=("test-strategy-no-os-enforcement",),
                proofs=(),
                reason="unit-test pipeline; containment asserted by the test harness only",
            ),
            envelope=envelope,
        )


def default_strategy() -> ContainmentStrategy:
    """The OS-enforced strategy for this host, or an honest refusal.

    Never returns :class:`TestStrategy` — a strategy without OS enforcement
    is not a containment strategy for real inspection.
    """
    strategy: ContainmentStrategy
    if sys.platform == "linux":
        strategy = LinuxStrategy()
    elif sys.platform == "darwin":
        strategy = MacOSStrategy()
    else:
        raise ContainmentUnavailableError(
            f"no OS-enforced containment strategy exists for platform {sys.platform!r}"
        )
    available, reason = strategy.availability()
    if not available:
        raise ContainmentUnavailableError(reason)
    return strategy


def contained_inspection(
    approved_roots: list[str] | tuple[str, ...],
    *,
    strategy: ContainmentStrategy | None = None,
    bounds: CollectionBounds | None = None,
    cancel_event: threading.Event | None = None,
) -> ContainedCollection:
    """One full contained inspection of the approved roots.

    Validates the roots through the shipped contract first (an invalid
    scope refuses before any process is launched), then collects under the
    host's OS-enforced strategy.
    """
    claude_code_contract(list(approved_roots))  # scope validation, fail closed
    chosen = strategy or default_strategy()
    request = CollectionRequest(
        approved_roots=tuple(approved_roots),
        bounds=bounds or CollectionBounds(),
    )
    return chosen.collect_contained(request, cancel_event=cancel_event)
