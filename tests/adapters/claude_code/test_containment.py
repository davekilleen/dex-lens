"""OS-level containment (G1 items a, f fail-closed): enforced strategies,
runtime proof, honest disable with guided fallback, zero writes."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest
from tests.adapters.claude_code.fixture_helpers import (
    PLANTED_API_TOKEN,
    PLANTED_AWS_KEY_ID,
    PLANTED_SECRET_VALUE,
    tree_digests,
)

from capability_exchange.adapters.claude_code import containment
from capability_exchange.adapters.claude_code.containment import (
    GUIDED_FALLBACK_MESSAGE,
    CollectionFailedError,
    CollectionRequest,
    ContainmentUnavailableError,
    LinuxStrategy,
    MacOSStrategy,
    TestStrategy,
    contained_inspection,
    default_strategy,
)

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="LinuxStrategy requires Linux")
macos_only = pytest.mark.skipif(sys.platform != "darwin", reason="MacOSStrategy requires macOS")


def request_for(root: Path) -> CollectionRequest:
    return CollectionRequest(approved_roots=(str(root),))


class TestStrategySelection:
    @linux_only
    def test_default_strategy_is_os_enforced(self) -> None:
        strategy = default_strategy()
        assert strategy.os_enforced
        assert not isinstance(strategy, TestStrategy)

    def test_unsupported_platform_fails_closed_with_honest_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(containment.sys, "platform", "sunos5")
        with pytest.raises(ContainmentUnavailableError) as caught:
            default_strategy()
        assert caught.value.fallback_guidance == GUIDED_FALLBACK_MESSAGE
        assert "guided, export-assisted" in str(caught.value)

    def test_linux_strategy_refuses_off_linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(containment.sys, "platform", "darwin")
        available, reason = LinuxStrategy().availability()
        assert not available
        assert "Linux" in reason

    def test_macos_strategy_refuses_off_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(containment.sys, "platform", "linux")
        available, reason = MacOSStrategy().availability()
        assert not available

    def test_default_strategy_refuses_macos_without_socket_creation_proof(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A connect-time denial is not the G1 socket-creation guarantee.

        GitHub's macOS runners currently allocate AF_INET sockets under the
        shipped Seatbelt profile.  The deep adapter must therefore disable
        itself before any target read when the runtime probe cannot prove
        ``socket()`` is denied, while retaining the guided fallback.
        """
        monkeypatch.setattr(containment.sys, "platform", "darwin")
        monkeypatch.setattr(containment.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
        monkeypatch.setattr(
            containment,
            "_probe_macos_runtime_proofs",
            lambda _sandbox_exec: ("connect-denied", "write-open-denied", "exec-denied"),
            raising=False,
        )

        with pytest.raises(ContainmentUnavailableError) as caught:
            default_strategy()

        assert "socket creation" in caught.value.reason.lower()
        assert caught.value.fallback_guidance == GUIDED_FALLBACK_MESSAGE
        assert "guided, export-assisted" in str(caught.value)

    def test_cancellable_child_drains_output_larger_than_pipe_capacity(
        self, claude_root: Path
    ) -> None:
        envelope = TestStrategy().collect_contained(request_for(claude_root)).envelope
        response = {
            "schema": containment.contained.RESULT_SCHEMA,
            "envelope": envelope.model_dump(mode="json"),
            "layers": ["test-output-drain"],
            "proofs": ["large-output-completed"],
        }
        script = (
            "import json,sys; sys.stdin.buffer.read(); "
            f"payload=json.loads({json.dumps(json.dumps(response))}); "
            "payload['padding']='x'*262144; sys.stdout.write(json.dumps(payload))"
        )

        result = containment._launch_contained_child(
            [sys.executable, "-c", script],
            request_for(claude_root),
            layer_reason="test output draining",
            os_enforced=False,
            cancel_event=threading.Event(),
        )

        assert result.envelope == envelope
        assert result.outcome.proofs == ("large-output-completed",)


class TestTestStrategyDiscipline:
    def test_test_strategy_reports_no_os_enforcement(self, claude_root: Path) -> None:
        result = TestStrategy().collect_contained(request_for(claude_root))
        assert result.outcome.established
        assert not result.outcome.os_enforced
        assert result.outcome.layers == ("test-strategy-no-os-enforcement",)

    def test_test_strategy_refuses_outside_pytest(
        self, claude_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with pytest.raises(ContainmentUnavailableError, match="refuses to"):
            TestStrategy().collect_contained(request_for(claude_root))


@linux_only
class TestLinuxContainedCollection:
    def test_end_to_end_contained_collection(self, secret_bearing_root: Path) -> None:
        before = tree_digests(secret_bearing_root)
        result = LinuxStrategy().collect_contained(request_for(secret_bearing_root))
        after = tree_digests(secret_bearing_root)

        # zero writes: the inspected tree is byte- and mtime-identical
        assert before == after
        assert result.outcome.established and result.outcome.os_enforced
        assert "seccomp-filter" in result.outcome.layers
        assert set(result.outcome.proofs) == {
            "socket-denied",
            "write-open-denied",
            "exec-denied",
        }
        payload = json.dumps(result.envelope.model_dump(mode="json"))
        for canary in (PLANTED_AWS_KEY_ID, PLANTED_SECRET_VALUE, PLANTED_API_TOKEN):
            assert canary not in payload

    def test_nonexistent_root_aborts_with_partials_discarded(self, tmp_path: Path) -> None:
        with pytest.raises(CollectionFailedError, match="discarded"):
            LinuxStrategy().collect_contained(request_for(tmp_path / "missing"))

    def test_contained_inspection_front_door(self, claude_root: Path) -> None:
        result = contained_inspection([str(claude_root)])
        assert result.envelope.adapter_id == "claude-code-local"
        probe_ids = [p.probe_id for p in result.envelope.probes]
        assert "collection-exclusions" in probe_ids

    def test_symlink_escape_stays_contained_end_to_end(
        self, claude_root: Path, tmp_path: Path
    ) -> None:
        secret_target = tmp_path / "outside" / "id_ed25519"
        secret_target.parent.mkdir()
        secret_target.write_text("PRIVATE-KEY-CANARY-BYTES")
        (claude_root / "innocent.md").symlink_to(secret_target)
        result = LinuxStrategy().collect_contained(request_for(claude_root))
        payload = json.dumps(result.envelope.model_dump(mode="json"))
        assert "PRIVATE-KEY-CANARY-BYTES" not in payload
        assert "symlink-escape" in payload  # honest exclusion record


@linux_only
class TestSeccompDeniesEvenBuggyCode:
    """G1: the process cannot open sockets or spawn shells even if its own
    code is buggy — proven by attempting exactly that after confinement."""

    def test_confined_process_cannot_socket_write_or_exec(self) -> None:
        probe = textwrap.dedent(
            """
            import errno, os, socket, sys
            from capability_exchange.adapters.claude_code.contained import (
                confine_this_process,
            )
            confine_this_process()
            failures = []
            try:
                socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                failures.append("socket-allowed")
            except PermissionError:
                pass
            try:
                os.open("/dev/null", os.O_WRONLY)
                failures.append("write-open-allowed")
            except PermissionError:
                pass
            try:
                fd = os.open("/tmp/containment-breakout", os.O_WRONLY | os.O_CREAT, 0o600)
                failures.append("create-allowed")
            except PermissionError:
                pass
            try:
                os.unlink("/tmp/containment-breakout-nonexistent")
                failures.append("unlink-reached-fs")
            except PermissionError:
                pass
            except FileNotFoundError:
                failures.append("unlink-reached-fs")
            try:
                os.posix_spawn("/bin/sh", ["/bin/sh", "-c", ":"], {})
                failures.append("shell-spawned")
            except PermissionError:
                pass
            # reading still works: this is a collector, not a lockbox
            with open("/etc/hostname", "rb") as fh:
                fh.read(8)
            if failures:
                print("; ".join(failures), file=sys.stderr)
                sys.exit(1)
            sys.exit(0)
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, timeout=60, check=False
        )
        assert completed.returncode == 0, completed.stderr.decode()

    def test_confined_process_cannot_write_file_metadata(self, tmp_path: Path) -> None:
        """G1(a) "no file writes" covers *metadata* writes too.

        Adversarial M1 finding: the open-flag filter gates write capability
        acquired through ``open``, but ``utimensat`` and the ``*xattr``
        family take a path (or a read-only fd) and mutate a file without
        ever opening it for writing. Both changed the inspected tree on disk
        under confinement. Timestamps and extended attributes are part of
        the person's system; a contained collector must not be able to
        touch them even if its own code is buggy.
        """
        victim = tmp_path / "victim.txt"
        victim.write_text("original\n")
        probe = textwrap.dedent(
            f"""
            import os, sys
            from capability_exchange.adapters.claude_code.contained import (
                confine_this_process,
            )
            victim = {str(victim)!r}
            before_mtime = os.stat(victim).st_mtime_ns
            confine_this_process()
            failures = []

            def denied(label, fn):
                try:
                    fn()
                except PermissionError:
                    return
                except OSError as exc:
                    failures.append(f"{{label}}-errno-{{exc.errno}}")
                    return
                failures.append(label)

            denied("utime-path", lambda: os.utime(victim, (1000000, 1000000)))
            denied("utime-nofollow",
                   lambda: os.utime(victim, (1000000, 1000000), follow_symlinks=False))
            denied("utime-fd", lambda: os.utime(os.open(victim, os.O_RDONLY), (2, 2)))
            denied("setxattr", lambda: os.setxattr(victim, "user.probe", b"escaped"))
            denied("removexattr", lambda: os.removexattr(victim, "user.probe"))

            if os.stat(victim).st_mtime_ns != before_mtime:
                failures.append("MTIME-ACTUALLY-CHANGED")
            if b"user.probe" in b"".join(os.listxattr(victim)):
                failures.append("XATTR-ACTUALLY-SET")
            if failures:
                print("; ".join(failures), file=sys.stderr)
                sys.exit(1)
            sys.exit(0)
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, timeout=60, check=False
        )
        assert completed.returncode == 0, completed.stderr.decode()
        assert victim.read_text() == "original\n"


@macos_only
class TestMacOSContainedCollection:
    def test_end_to_end_contained_or_honest_refusal(self, secret_bearing_root: Path) -> None:
        """On macOS the collection either completes under sandbox-exec with
        all three proofs, or refuses honestly — never a silent uncontained
        collection (G1 fail closed)."""
        before = tree_digests(secret_bearing_root)
        try:
            result = MacOSStrategy().collect_contained(request_for(secret_bearing_root))
        except ContainmentUnavailableError as refusal:
            assert refusal.fallback_guidance == GUIDED_FALLBACK_MESSAGE
            return
        finally:
            assert tree_digests(secret_bearing_root) == before
        assert result.outcome.os_enforced
        assert "external-sandbox-profile" in result.outcome.layers
        assert {"write-open-denied", "exec-denied"} <= set(result.outcome.proofs)
        # The network proof is honestly platform-shaped: Linux seccomp denies
        # socket() outright, while sandbox-exec's `(deny network*)` lets the
        # fd be allocated and denies `connect`. Either is proof of no egress
        # — egress needs connect/sendto, and prove_containment raises if a
        # connection actually succeeds. Asserting the Linux label alone would
        # fail a correctly contained macOS run.
        assert set(result.outcome.proofs) & {"socket-denied", "connect-denied"}
        payload = json.dumps(result.envelope.model_dump(mode="json"))
        assert PLANTED_AWS_KEY_ID not in payload


class TestChildProtocolFailClosed:
    def test_child_refuses_malformed_request(self) -> None:
        from capability_exchange.adapters.claude_code import contained

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "capability_exchange.adapters.claude_code.contained_entry",
                "--containment",
                "external",
            ],
            input=b'{"schema": "wrong/1"}',
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == contained.EXIT_COLLECTION_FAILED
        assert b"invalid collection request" in completed.stderr

    def test_child_refuses_unknown_request_keys(self) -> None:
        from capability_exchange.adapters.claude_code import contained

        request = {
            "schema": contained.REQUEST_SCHEMA,
            "approved_roots": ["/tmp"],
            "surprise_field": True,
        }
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "capability_exchange.adapters.claude_code.contained_entry",
                "--containment",
                "external",
            ],
            input=json.dumps(request).encode(),
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == contained.EXIT_COLLECTION_FAILED

    @linux_only
    def test_uncontained_external_mode_refuses_to_collect(self, claude_root: Path) -> None:
        """A child told containment is external, but actually uncontained,
        must prove the gap and refuse before reading anything (fail closed)."""
        from capability_exchange.adapters.claude_code import contained

        request = {
            "schema": contained.REQUEST_SCHEMA,
            "approved_roots": [str(claude_root)],
        }
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "capability_exchange.adapters.claude_code.contained_entry",
                "--containment",
                "external",
            ],
            input=json.dumps(request).encode(),
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == contained.EXIT_CONTAINMENT_UNAVAILABLE
        assert b"containment unavailable" in completed.stderr
        assert completed.stdout == b""  # nothing collected, nothing emitted
