"""G1 hostile fixture 7 (gates.md): mutation during inspection.

A real background thread mutates a file mid-collection. Reads must come
from the immutable consent-time snapshot (never live disk), evidence for a
changed file must degrade to the R2 state ``conflicting``, and detection
ambiguity must abort the inspection and discard partials — never
best-effort live reads.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest
from tests.fixtures.hostile.catalog import build_mutation_system
from tests.fixtures.hostile.pipeline import snapshot_of

from capability_exchange.adapters.claude_code.collector import EvidenceCollector
from capability_exchange.adapters.claude_code.snapshot import InspectionAbortedError
from capability_exchange.evidence import EvidenceState, supports_claims

ORIGINAL_TEXT = "Project instructions for a real repeated job.\n"


def _mutate_in_background(action) -> None:  # type: ignore[no-untyped-def]
    """Run the mutation on a real background thread and join it."""
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            action()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            failure.append(exc)

    thread = threading.Thread(target=runner, name="hostile-mutator")
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive(), "background mutator did not finish"
    assert not failure, f"background mutator failed: {failure[0]!r}"


def test_g1_reads_served_from_snapshot_not_live_disk(tmp_path: Path) -> None:
    root, target = build_mutation_system(tmp_path)
    _contract, snapshot = snapshot_of(root)
    target_path = next(
        path for path in snapshot.canonical_paths() if path.endswith("CLAUDE.md")
    )
    _mutate_in_background(lambda: target.write_text("MUTATED MID-INSPECTION\n"))
    # The live file changed; the snapshot still serves consent-time bytes.
    assert snapshot.content_of(target_path) == ORIGINAL_TEXT.encode()
    assert target.read_text() == "MUTATED MID-INSPECTION\n"


def test_g1_mutated_file_degrades_to_conflicting_never_fresh(tmp_path: Path) -> None:
    root, target = build_mutation_system(tmp_path)
    contract, snapshot = snapshot_of(root)
    _mutate_in_background(lambda: target.write_text("MUTATED MID-INSPECTION\n"))
    envelope = EvidenceCollector(contract, snapshot).collect()
    by_id = {p.probe_id: p for p in envelope.probes}
    states = [item.state for item in by_id["instructions-present"].evidence]
    assert states == [EvidenceState.CONFLICTING]
    assert all(not supports_claims(state) for state in states)
    # Untouched files keep their observed evidence.
    settings_states = [item.state for item in by_id["settings-present"].evidence]
    assert settings_states == [EvidenceState.OBSERVED]
    assert "MUTATED" not in envelope.model_dump_json()


def test_g1_continuous_writer_never_yields_observed(tmp_path: Path) -> None:
    root, target = build_mutation_system(tmp_path)
    stop = threading.Event()
    started = threading.Event()

    def churn() -> None:
        counter = 0
        while not stop.is_set():
            counter += 1
            target.write_text(f"churn iteration {counter}\n")
            started.set()

    writer = threading.Thread(target=churn, name="hostile-churn")
    writer.start()
    try:
        assert started.wait(timeout=10)
        contract, snapshot = snapshot_of(root)
        target_path = next(
            path for path in snapshot.canonical_paths() if path.endswith("CLAUDE.md")
        )
        captured_digest = snapshot.entry_for(target_path).raw_digest
        # Guarantee at least one full write landed after capture, so the
        # integrity recheck deterministically sees changed bytes.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            live = hashlib.sha256(target.read_bytes()).hexdigest()
            if live != captured_digest:
                break
        envelope = EvidenceCollector(contract, snapshot).collect()
    finally:
        stop.set()
        writer.join(timeout=30)
    by_id = {p.probe_id: p for p in envelope.probes}
    instruction_items = by_id["instructions-present"].evidence
    # The churned file was either captured-then-flagged conflicting, or
    # honestly excluded — never presented as cleanly observed.
    if instruction_items and instruction_items[0].reference.startswith("file:"):
        assert instruction_items[0].state is EvidenceState.CONFLICTING


def test_g1_detection_ambiguity_aborts_and_discards(tmp_path: Path) -> None:
    root, target = build_mutation_system(tmp_path)
    contract, snapshot = snapshot_of(root)

    def swap_for_symlink() -> None:
        target.unlink()
        target.symlink_to("/etc/hostname")

    _mutate_in_background(swap_for_symlink)
    with pytest.raises(InspectionAbortedError, match="discard"):
        EvidenceCollector(contract, snapshot).collect()
    # Abort-and-discard: no envelope exists; the only surviving object is
    # the in-memory snapshot, which still refuses to be mistaken for a
    # completed inspection (its data dies with this test scope).
