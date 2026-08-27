from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
    HumanCapability,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    SafeAttribute,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState

NOW = datetime(2026, 8, 27, tzinfo=UTC)
CANARY = "INVENTED_SESSION_CANARY_NEVER_RETAIN"

EXPECTED_COUNTS = Counter(
    {
        Disposition.NOT_ASSESSED: 80,
        Disposition.NOT_RELEVANT: 17,
        Disposition.SHARED: 8,
        Disposition.WORTH_BORROWING: 3,
        Disposition.FRAGILE_OR_CONTRADICTORY: 3,
        Disposition.STRONG_HERE: 2,
        Disposition.DEX_SHOULD_LEARN: 2,
    }
)


@dataclass(frozen=True)
class SyntheticSourceInput:
    """Invented source metadata before the privacy-safe fingerprint boundary."""

    identity: str
    name: str
    source_class: str
    evidence_reference: str


@dataclass(frozen=True)
class SyntheticSessionInput:
    """Synthetic raw input whose secret must not cross into retained artifacts."""

    secret: str
    sources: tuple[SyntheticSourceInput, ...]


def synthetic_entry_ids() -> tuple[str, ...]:
    return tuple(f"invented-capability-{index:03d}" for index in range(115))


def real_session_input() -> SyntheticSessionInput:
    return SyntheticSessionInput(
        secret=CANARY,
        sources=(
            SyntheticSourceInput(
                identity="invented-shared-method-vault",
                name="Invented shared method",
                source_class="vault-authored",
                evidence_reference="file-token:invented-vault-method.md",
            ),
            SyntheticSourceInput(
                identity="invented-shared-method-global",
                name="Invented shared method",
                source_class="user-global",
                evidence_reference="file-token:invented-global-method.md",
            ),
        ),
    )


def real_session_fingerprint() -> EvidenceFingerprint:
    session_input = real_session_input()
    observations = [
        Observation(
            kind=ObservationKind.RELEASE,
            identity="invented-release",
            label="Invented release",
            operational_state=OperationalState.IMPLEMENTED,
            evidence=EvidenceItem(
                state=EvidenceState.OBSERVED,
                captured_at=NOW,
                reference="probe-token:invented-release",
            ),
            provenance={
                "source_id": "scope:invented-release",
                "source_class": "harness-bundled",
                "scope_reference": "scope:sha256:" + "a" * 64,
                "relative_reference": "synthetic/release/VERSION",
            },
            attributes=(SafeAttribute(key="release-id", value="invented-release-v1"),),
        )
    ]
    observations.extend(
        Observation(
            kind=ObservationKind.SKILL,
            identity=source.identity,
            label=source.name,
            operational_state=OperationalState.IMPLEMENTED,
            evidence=EvidenceItem(
                state=EvidenceState.OBSERVED,
                captured_at=NOW,
                reference=source.evidence_reference,
            ),
            provenance={
                "source_id": f"scope:{source.identity}",
                "source_class": source.source_class,
                "scope_reference": (
                    "scope:sha256:" + ("b" if source.source_class == "vault-authored" else "c") * 64
                ),
                "relative_reference": f"synthetic/{source.identity}/SKILL.md",
            },
            attributes=(SafeAttribute(key="source-kind", value=source.source_class),),
        )
        for source in session_input.sources
    )
    return EvidenceFingerprint(
        adapter_id="invented-local-adapter",
        collected_at=NOW,
        observations=tuple(observations),
    )


def real_session_ledger() -> ComparisonLedger:
    identities = synthetic_entry_ids()
    capabilities = tuple(
        HumanCapability(
            capability_id=identity,
            title=f"Invented capability {index:03d}",
            job_ids=(f"invented-job-{index:03d}",),
            catalogue_ids=(identity,),
            person_observation_ids=(),
        )
        for index, identity in enumerate(identities)
    )
    entries: list[CatalogueDisposition] = []
    offset = 0
    for disposition, count in EXPECTED_COUNTS.items():
        for index in range(offset, offset + count):
            identity = identities[index]
            grounded = disposition not in {
                Disposition.NOT_ASSESSED,
                Disposition.NOT_RELEVANT,
            }
            evidence_references = (
                (
                    (
                        f"probe-token:invented-evidence-{index:03d}"
                        if index % 2 == 0
                        else f"file-token:invented-evidence-{index:03d}.md"
                    ),
                )
                if grounded
                else ()
            )
            entries.append(
                CatalogueDisposition(
                    catalogue_id=identity,
                    disposition=disposition,
                    capability_id=identity,
                    evidence_references=evidence_references,
                    method_compared=disposition is Disposition.SHARED,
                    reason=f"Invented replay reason {index:03d} for {disposition.value}.",
                )
            )
        offset += count
    return ComparisonLedger(
        catalogue_version=115,
        catalogue_sha256="b" * 64,
        capabilities=capabilities,
        entries=tuple(entries),
        reciprocal_answer="Dex should learn the invented reviewed-checkpoint method.",
    )


def real_session_report() -> str:
    return """# Invented diagnosis

## What I read
- Invented inventory: `file-token:invented-inventory.md`

## What is working especially well
### Invented review checkpoint — Verified
> Confirm the invented checkpoint before the next step.
> - `file-token:invented-strength.md`

## What Dex should learn from you
### Invented reciprocal method — Verified
> Pair every invented choice with an invented review checkpoint.
> - `file-token:invented-reciprocal.md`

## Worth borrowing from Dex
### Invented reliability check — Supported
> The invented check remains bounded to synthetic evidence.
> - `probe-token:invented-reliability.md`

## Considered and rejected
- `invented-capability-080` — not relevant to the invented setup.

## Fragility and contradictions
I checked the rules in `file-token:invented-rules.md` against the
invented skills and found no conflicts.

## Coverage and limits
- 80 capabilities remain Unknown.
- Every identity and evidence reference in this replay is invented.

## What happens next
- Strongest grounded capability: the invented review checkpoint.
- Reciprocal value: the invented reviewed-checkpoint method.
- Single best first move: consider the invented reliability check.
- Report location: `file-token:invented-report.md`.
- Return to run: `probe-token:invented-run`.
- Sharing choice: undecided.
- Future-watch choice: undecided.
"""
