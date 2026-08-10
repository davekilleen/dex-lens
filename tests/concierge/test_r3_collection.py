"""R3 collection lifecycle: scope revalidation, cancellation, honest fallback."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_exchange.adapter import AdapterResultEnvelope, InstrumentHealth, ProbeResult
from capability_exchange.adapters.claude_code import containment
from capability_exchange.adapters.claude_code.containment import (
    CollectionFailedError,
    CollectionRequest,
    LinuxStrategy,
)
from capability_exchange.adapters.claude_code.snapshot import CollectionBounds
from capability_exchange.concierge.collection import (
    CollectionCancelled,
    CollectionController,
    containment_fallback,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState


def _envelope() -> AdapterResultEnvelope:
    return AdapterResultEnvelope(
        adapter_id="claude-code-local",
        contract_version="0.1.0",
        collected_at=datetime.now(UTC),
        probes=(
            ProbeResult(
                probe_id="test-probe",
                health=InstrumentHealth.HEALTHY,
                evidence=(
                    EvidenceItem(
                        state=EvidenceState.OBSERVED,
                        captured_at=datetime.now(UTC),
                        reference="file:test",
                    ),
                ),
            ),
        ),
    )


def test_scope_snapshot_rejects_changes_before_publication(tmp_path: Path) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    controller = CollectionController((root,))
    started = threading.Event()
    release = threading.Event()

    def collector(cancel_event: threading.Event) -> AdapterResultEnvelope:
        started.set()
        release.wait(timeout=2)
        return _envelope()

    def run() -> None:
        try:
            controller.collect(collector)
        except ValueError:
            pass

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(timeout=2)
    root.rename(tmp_path / "scope-moved")
    release.set()
    worker.join(timeout=2)
    with pytest.raises(ValueError, match="scope"):
        controller.result()


def test_empty_scope_override_never_reuses_the_original_roots(tmp_path: Path) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    controller = CollectionController((root,))

    with pytest.raises(ValueError, match="empty"):
        controller.collect(lambda: _envelope(), approved_roots=())


def test_scope_shrink_stops_the_next_read_batch(tmp_path: Path) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    live_roots = [root]
    controller = CollectionController(
        (root,), scope_provider=lambda: tuple(live_roots)
    )
    started = threading.Event()
    stopped = threading.Event()
    reads: list[int] = []
    failures: list[BaseException] = []

    def collector(cancel_event: threading.Event) -> AdapterResultEnvelope:
        started.set()
        try:
            while not cancel_event.wait(0.005):
                reads.append(len(reads))
        finally:
            stopped.set()
        raise CollectionCancelled("scope shrink stopped reads")

    def run() -> None:
        try:
            controller.collect(collector)
        except BaseException as exc:
            failures.append(exc)

    owner = threading.Thread(target=run)
    owner.start()
    assert started.wait(timeout=2)
    live_roots.clear()
    owner.join(timeout=2)

    assert not owner.is_alive()
    assert stopped.is_set()
    reads_at_stop = len(reads)
    time.sleep(0.03)
    assert len(reads) == reads_at_stop
    assert failures
    assert isinstance(failures[0], (CollectionCancelled, ValueError))
    with pytest.raises((CollectionCancelled, ValueError)):
        controller.result()


def test_cancellation_discards_partial_result_and_marks_cancelled(tmp_path: Path) -> None:
    root = tmp_path / "scope"
    root.mkdir()
    controller = CollectionController((root,))
    started = threading.Event()

    def collector(cancel_event: threading.Event) -> AdapterResultEnvelope:
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.005)
        raise CollectionCancelled("cancelled")

    def run() -> None:
        try:
            controller.collect(collector)
        except CollectionCancelled:
            pass

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(timeout=2)
    controller.cancel()
    worker.join(timeout=2)
    assert controller.cancelled
    with pytest.raises(CollectionCancelled):
        controller.result()


def test_containment_fallback_is_not_verified() -> None:
    result = containment_fallback("sandbox unavailable", now=datetime.now(UTC))
    assert result.fallback
    assert "guided" in result.message.lower()
    assert all(
        item.state is not EvidenceState.OBSERVED
        for probe in result.envelope.probes
        for item in probe.evidence
    )
    assert "never Verified" in result.message


@pytest.mark.skipif(os.sys.platform != "linux", reason="real contained child requires Linux")
def test_real_contained_child_is_killed_on_cancel_before_partial_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 cancellation must stop the actual child, not only publication."""
    root = tmp_path / "scope"
    root.mkdir()
    (root / "CLAUDE.md").write_text("read barrier fixture\n")
    barrier = tmp_path / "read-barrier"
    os.mkfifo(barrier)
    child_started = threading.Event()
    child_terminated = threading.Event()
    cancel_event = threading.Event()
    original_popen = subprocess.Popen

    def tracking_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child_started.set()
        return original_popen(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(containment.subprocess, "Popen", tracking_popen)
    monkeypatch.setenv("DEX_LENS_TEST_READ_BARRIER", str(barrier))
    request = CollectionRequest(
        approved_roots=(str(root),),
        bounds=CollectionBounds(max_file_count=16, max_file_bytes=1024, max_total_bytes=4096),
        timeout_seconds=10,
        child_terminated=child_terminated,
    )
    failures: list[BaseException] = []

    def collect() -> None:
        try:
            LinuxStrategy().collect_contained(request, cancel_event=cancel_event)
        except BaseException as exc:
            failures.append(exc)

    worker = threading.Thread(target=collect)
    worker.start()
    assert child_started.wait(timeout=2)
    cancel_started = time.monotonic()
    cancel_event.set()
    worker.join(timeout=2)
    elapsed = time.monotonic() - cancel_started

    assert not worker.is_alive()
    assert child_terminated.wait(timeout=0.1)
    assert elapsed < 1.0
    assert failures and isinstance(failures[0], CollectionFailedError)
    assert list(root.glob("partial*")) == []
