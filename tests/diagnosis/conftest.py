"""Shared builders for the M-D diagnosis tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from capability_exchange.adapter import (
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.evidence import EvidenceItem, EvidenceState
from capability_exchange.jobs import (
    JobBoundaries,
    JobCadence,
    JobImportance,
    SuccessContract,
)

COLLECTED_AT = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


def item(
    state: EvidenceState = EvidenceState.OBSERVED,
    reference: str = "path:.claude/skills",
    captured_at: datetime = COLLECTED_AT,
) -> EvidenceItem:
    return EvidenceItem(state=state, captured_at=captured_at, reference=reference)


def probe(
    probe_id: str,
    *items: EvidenceItem,
    health: InstrumentHealth = InstrumentHealth.HEALTHY,
    detail: str = "",
) -> ProbeResult:
    return ProbeResult(probe_id=probe_id, health=health, detail=detail, evidence=items)


def observed_probe(probe_id: str, reference: str | None = None) -> ProbeResult:
    return probe(
        probe_id, item(EvidenceState.OBSERVED, reference or f"probe:{probe_id}")
    )


def envelope(*probes: ProbeResult) -> AdapterResultEnvelope:
    return AdapterResultEnvelope(
        adapter_id="claude-code-local",
        contract_version="0.1.0",
        collected_at=COLLECTED_AT,
        probes=probes,
    )


def contract(job_id: str = "weekly-report") -> SuccessContract:
    return SuccessContract(
        job_id=job_id,
        situation="Every Friday the status report is due",
        desired_outcome="A finished report the person trusts",
        success_evidence=("a finished report exists by Friday",),
        boundaries=JobBoundaries(
            privacy_limits=("never read personal mail",),
            approval_limits=("sending anything requires approval",),
            autonomy_limits=("no changes without a person present",),
        ),
        importance=JobImportance.HIGH,
        cadence=JobCadence.WEEKLY,
        confirmed_at=COLLECTED_AT,
    )


@pytest.fixture
def confirmed_contract() -> SuccessContract:
    return contract()


#: The M1 Claude Code adapter's real probes: all configuration presence.
def presence_only_envelope() -> AdapterResultEnvelope:
    return envelope(
        observed_probe("collection-exclusions"),
        observed_probe("installation-shape"),
        observed_probe("instructions-present"),
        observed_probe("settings-present"),
        observed_probe("skills-present"),
    )
