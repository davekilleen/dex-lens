"""R3 collection lifecycle: scope revalidation, cancellation, honest fallback."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_exchange.adapter import AdapterResultEnvelope, InstrumentHealth, ProbeResult
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
