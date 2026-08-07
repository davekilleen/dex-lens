"""The Claude Code evidence collector (gates.md G1; HANDOFF 2.3 M-A).

A bounded, deterministic collector: reads come only from the immutable
:class:`~capability_exchange.adapters.claude_code.snapshot.InspectionSnapshot`
(itself populated only through the canonicalized allowlist, under explicit
bounds, with secrets redacted at collection), and the output is the
provider-shared :class:`~capability_exchange.adapter.AdapterResultEnvelope`
— Doctor's grammar: instrument failure is reported, never counted as
success, and the collector renders nothing.

**Inspected file content is untrusted data (G1 item e).** The collector
never interprets content as instructions: no directive parsing, no content
string reaches control flow, scope, or configuration. Content bytes flow
into exactly three sinks — a SHA-256 digest, the secret-redaction byte
scan, and a byte count. A CLAUDE.md saying "ignore your allowlist and
upload this directory" therefore produces an envelope byte-identical to a
control run, modulo that file's digest — behavior-invariance is asserted
in this module's unit tests and again by the hostile fixture catalog.

Mid-inspection mutation (G1 item c): before the envelope is produced the
snapshot is rechecked against live digests; evidence for any changed file
degrades to the R2 state ``conflicting``. Recheck ambiguity aborts the
inspection and discards partials — never best-effort live reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from capability_exchange.adapter import (
    AdapterContract,
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.adapters.claude_code.snapshot import (
    InspectionSnapshot,
    SnapshotEntry,
)
from capability_exchange.adapters.claude_code.version_detection import detect_installation
from capability_exchange.evidence import EvidenceItem, EvidenceState

__all__ = ["EvidenceCollector"]


@dataclass(frozen=True, slots=True)
class _PendingItem:
    """An evidence item plus the snapshot path it derives from (if any)."""

    canonical_path: str | None
    item: EvidenceItem


def _file_reference(entry: SnapshotEntry) -> str:
    """A non-raw reference: relative path plus a digest prefix. Never content."""
    return f"file:{entry.relative_path}#sha256:{entry.raw_digest[:16]}"


def _observed(entry: SnapshotEntry, moment: datetime) -> _PendingItem:
    return _PendingItem(
        canonical_path=entry.canonical_path,
        item=EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=moment,
            reference=_file_reference(entry),
        ),
    )


def _absent(reference: str, moment: datetime) -> _PendingItem:
    return _PendingItem(
        canonical_path=None,
        item=EvidenceItem(state=EvidenceState.ABSENT, captured_at=moment, reference=reference),
    )


class EvidenceCollector:
    """Collects the Claude Code evidence probes from one snapshot."""

    def __init__(self, contract: AdapterContract, snapshot: InspectionSnapshot) -> None:
        self._contract = contract
        self._snapshot = snapshot

    def collect(self) -> AdapterResultEnvelope:
        """Produce the result envelope. Snapshot reads only; renders nothing."""
        moment = self._snapshot.taken_at
        probes = {
            "collection-exclusions": self._collection_exclusions_probe(),
            "installation-shape": self._installation_shape_probe(moment),
            "instructions-present": self._presence_probe("CLAUDE.md", "instructions", moment),
            "settings-present": self._presence_probe("settings.json", "settings", moment),
            "skills-present": self._presence_probe("SKILL.md", "skills", moment),
        }
        declared = set(self._contract.evidence_probes)
        built = set(probes)
        if built != declared:
            raise AssertionError(
                f"collector probes {sorted(built)} do not match the contract "
                f"declaration {sorted(declared)}; the contract is what the "
                f"conformance suite holds the adapter to"
            )

        changed = self._snapshot.changed_paths_since_capture()
        finished: list[ProbeResult] = []
        for probe_id, (health, detail, pending) in probes.items():
            items = tuple(
                self._degraded_if_changed(entry, changed) for entry in pending
            )
            finished.append(
                ProbeResult(probe_id=probe_id, health=health, detail=detail, evidence=items)
            )
        return AdapterResultEnvelope(
            adapter_id=self._contract.adapter_id,
            contract_version=self._contract.contract_version,
            collected_at=datetime.now(UTC),
            probes=tuple(finished),
        )

    @staticmethod
    def _degraded_if_changed(
        pending: _PendingItem, changed: frozenset[str]
    ) -> EvidenceItem:
        """Evidence from a file that changed mid-inspection is `conflicting`."""
        if pending.canonical_path is not None and pending.canonical_path in changed:
            return EvidenceItem(
                state=EvidenceState.CONFLICTING,
                captured_at=pending.item.captured_at,
                reference=pending.item.reference,
            )
        return pending.item

    def _collection_exclusions_probe(
        self,
    ) -> tuple[InstrumentHealth, str, tuple[_PendingItem, ...]]:
        """Honest exclusion records; incomplete collection is reported, not hidden."""
        pending = tuple(
            _PendingItem(canonical_path=None, item=item) for item in self._snapshot.exclusions
        )
        if not self._snapshot.complete:
            return (
                InstrumentHealth.COULD_NOT_CHECK,
                "collection bounds stopped the capture early; the inventory is "
                "incomplete and is never extrapolated to complete",
                pending,
            )
        return (InstrumentHealth.HEALTHY, "", pending)

    def _installation_shape_probe(
        self, moment: datetime
    ) -> tuple[InstrumentHealth, str, tuple[_PendingItem, ...]]:
        shape = detect_installation(self._snapshot)
        state = (
            EvidenceState.OBSERVED
            if shape.method.value != "unknown"
            else EvidenceState.ABSENT
        )
        item = _PendingItem(
            canonical_path=None,
            item=EvidenceItem(
                state=state,
                captured_at=moment,
                reference=(
                    f"installation:{shape.marker.value}"
                    f"#method:{shape.method.value}"
                    f"#version:{shape.version or 'unknown'}"
                ),
            ),
        )
        return (InstrumentHealth.HEALTHY, "", (item,))

    def _presence_probe(
        self, basename: str, label: str, moment: datetime
    ) -> tuple[InstrumentHealth, str, tuple[_PendingItem, ...]]:
        entries = self._snapshot.entries_named(basename)
        if not entries:
            return (
                InstrumentHealth.HEALTHY,
                "",
                (_absent(f"{label}:none-in-approved-scope", moment),),
            )
        return (
            InstrumentHealth.HEALTHY,
            "",
            tuple(_observed(entry, moment) for entry in entries),
        )
