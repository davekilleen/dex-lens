"""G2 default-path egress tests over the contained inspection (M1 layer).

The full inspection runs inside the containment wrapper over a canary-
seeded fixture system. Zero approved egress exists at M1, so the harness
asserts (a) the inspection process cannot open sockets at all — probed
from inside the same strategy — and (b) canaries and their derivations
(SHA-256, substrings) appear nowhere in the serialized envelope, any log
line, or crash output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from tests.egress.harness import (
    EGRESS_CANARIES,
    WHOLE_FILE_CANARY,
    assert_capture_leak_free,
    build_canary_system,
    run_contained_child,
    run_socket_probe_under_linux_strategy,
)
from tests.fixtures.hostile.catalog import assert_no_canary_leak, derivations_of

from capability_exchange.adapters.claude_code import contained
from capability_exchange.adapters.claude_code.containment import (
    CollectionRequest,
    LinuxStrategy,
)

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux strategy layer")


@pytest.fixture
def canary_root(tmp_path: Path) -> Path:
    return build_canary_system(tmp_path)


@linux_only
class TestSocketRefusalUnderSameStrategy:
    def test_g2_socket_attempts_refused_inside_the_containment_strategy(self) -> None:
        capture = run_socket_probe_under_linux_strategy()
        assert capture.returncode == 0, capture.stderr.decode()
        assert b"all-socket-attempts-refused" in capture.stdout

    def test_g2_collection_child_proves_socket_denial_before_reading(
        self, canary_root: Path
    ) -> None:
        result = LinuxStrategy().collect_contained(
            CollectionRequest(approved_roots=(str(canary_root),))
        )
        assert "socket-denied" in result.outcome.proofs
        assert "exec-denied" in result.outcome.proofs
        assert "write-open-denied" in result.outcome.proofs


@linux_only
class TestFullInspectionLeakFree:
    def test_g2_envelope_logs_and_stdout_carry_no_canary_derivations(
        self, canary_root: Path
    ) -> None:
        capture = run_contained_child([str(canary_root)])
        assert capture.returncode == contained.EXIT_OK, capture.stderr.decode()
        assert_capture_leak_free(capture, context="contained child output")
        # The stdout payload IS the serialized envelope wrapper — parse and
        # assert on the envelope's own serialized bytes too.
        payload = json.loads(capture.stdout.decode())
        assert_no_canary_leak(
            json.dumps(payload["envelope"]),
            EGRESS_CANARIES,
            context="serialized envelope",
        )

    def test_g2_whole_file_canary_hash_never_in_envelope(
        self, canary_root: Path
    ) -> None:
        # CLAUDE.md's entire content is one canary: an unkeyed content hash
        # anywhere in the output would be sha256(canary) — a verifiable
        # derivation. The reference digest must be per-inspection keyed.
        capture = run_contained_child([str(canary_root)])
        assert capture.returncode == contained.EXIT_OK, capture.stderr.decode()
        text = capture.observable_output.decode("utf-8", "replace")
        for derived in derivations_of(WHOLE_FILE_CANARY):
            assert derived not in text, (
                "a derivation of the whole-file canary (its bytes or their "
                "sha256) is present in the inspection output"
            )

    def test_g2_two_runs_never_share_reference_digests(self, canary_root: Path) -> None:
        # Keyed references must be unlinkable across runs: if two separate
        # inspections emit the same digest for the same content, the digest
        # is content-derived in an attacker-verifiable way.
        def reference_digests(raw: bytes) -> set[str]:
            payload = json.loads(raw.decode())
            found: set[str] = set()
            for probe in payload["envelope"]["probes"]:
                for item in probe["evidence"]:
                    reference = item["reference"]
                    if "#snap:" in reference:
                        found.add(reference.split("#snap:", 1)[1])
            return found

        first = run_contained_child([str(canary_root)])
        second = run_contained_child([str(canary_root)])
        assert first.returncode == second.returncode == contained.EXIT_OK
        first_digests = reference_digests(first.stdout)
        second_digests = reference_digests(second.stdout)
        assert first_digests, "expected keyed reference digests in the envelope"
        assert first_digests.isdisjoint(second_digests)


@linux_only
class TestCrashOutputLeakFree:
    def test_g2_invalid_request_crash_carries_no_canaries(
        self, canary_root: Path
    ) -> None:
        capture = run_contained_child(
            [str(canary_root)],
            bounds_payload={"max_file_count": 4, "surprise": True},
        )
        assert capture.returncode == contained.EXIT_COLLECTION_FAILED
        assert b"collection aborted" in capture.stderr
        assert_capture_leak_free(capture, context="crash output")

    def test_g2_missing_root_crash_carries_no_canaries(self, tmp_path: Path) -> None:
        canary_root = build_canary_system(tmp_path)
        capture = run_contained_child(
            [str(canary_root), str(tmp_path / "does-not-exist")]
        )
        assert capture.returncode == contained.EXIT_COLLECTION_FAILED
        assert_capture_leak_free(capture, context="crash output")

    def test_g2_killed_mid_collection_emits_nothing(self, canary_root: Path) -> None:
        import subprocess

        request = {
            "schema": contained.REQUEST_SCHEMA,
            "approved_roots": [str(canary_root)],
        }
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "capability_exchange.adapters.claude_code.contained_entry",
                    "--containment",
                    "self",
                ],
                input=json.dumps(request).encode(),
                capture_output=True,
                timeout=0.05,
                check=False,
            )
        except subprocess.TimeoutExpired as caught:
            # The kill landed mid-collection: partials died with the child;
            # whatever escaped before the kill must be canary-free.
            for stream in (caught.stdout, caught.stderr):
                if stream:
                    assert_no_canary_leak(
                        stream, EGRESS_CANARIES, context="killed-child output"
                    )
        else:
            # The child outran the kill on this machine — its complete
            # output must be canary-free like any other run.
            assert_no_canary_leak(
                completed.stdout + b"\n" + completed.stderr,
                EGRESS_CANARIES,
                context="fast-child output",
            )
