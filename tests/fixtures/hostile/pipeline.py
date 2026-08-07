"""In-process adapter pipeline helpers for the hostile fixture tests.

The catalog exercises the allowlist → snapshot → collector pipeline
directly (the OS-enforcement layer has its own suite in
``tests/adapters/claude_code/test_containment.py`` and ``tests/egress/``).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.adapter import AdapterContract, AdapterResultEnvelope
from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.collector import EvidenceCollector
from capability_exchange.adapters.claude_code.contract import claude_code_contract
from capability_exchange.adapters.claude_code.snapshot import (
    CollectionBounds,
    InspectionSnapshot,
    take_snapshot,
)

#: A fixed consent moment so two runs' ``captured_at`` values are identical.
FIXED_CONSENT_MOMENT = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)

_VOLATILE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # The collection timestamp is per-run by nature.
    (re.compile(r'"collected_at":\s*"[^"]+"'), '"collected_at":"<collected-at>"'),
    # Content digests are, by definition, derived from each file's data
    # content — the one thing G1's behavior-invariance clause exempts.
    (re.compile(r"#(?:snap|sha256|digest)[a-z-]*:[0-9a-f]+"), "#digest:<data>"),
    (re.compile(r"sha256:[0-9a-f]+"), "sha256:<data>"),
)


def allowlist_for(contract: AdapterContract) -> CanonicalAllowlist:
    return CanonicalAllowlist(contract.read_scope, denied_paths=contract.denied_paths)


def snapshot_of(
    root: Path,
    *,
    bounds: CollectionBounds | None = None,
    taken_at: datetime | None = None,
) -> tuple[AdapterContract, InspectionSnapshot]:
    contract = claude_code_contract([str(root)])
    snapshot = take_snapshot(allowlist_for(contract), bounds=bounds, taken_at=taken_at)
    return contract, snapshot


def collect_from(
    root: Path,
    *,
    bounds: CollectionBounds | None = None,
    taken_at: datetime | None = None,
) -> AdapterResultEnvelope:
    contract, snapshot = snapshot_of(root, bounds=bounds, taken_at=taken_at)
    return EvidenceCollector(contract, snapshot).collect()


def serialized(envelope: AdapterResultEnvelope) -> str:
    """The envelope's serialized JSON bytes (as text)."""
    return envelope.model_dump_json()


def normalized_bytes(envelope: AdapterResultEnvelope) -> str:
    """Serialized envelope with only the legitimately-per-run values masked.

    Masks exactly two things: the collection timestamp and content-derived
    digest tokens ("modulo the file's data content", gates.md G1 fixture 5).
    Everything else — probe ids, ordering, health, details, states,
    reference paths, exclusion records — must be byte-identical between an
    injected run and its control run.
    """
    text = serialized(envelope)
    for pattern, replacement in _VOLATILE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
