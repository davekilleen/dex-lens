"""One fixture per encoded #351 negative rule (M-D acceptance).

Every negative rule in the Foundation Capability definitions gets a fixture
proving the engine honors it; a coverage test at the bottom fails if a rule
is ever added without its fixture.
"""

from __future__ import annotations

import inspect
from datetime import timedelta

from tests.diagnosis.conftest import (
    COLLECTED_AT,
    contract,
    envelope,
    item,
    observed_probe,
    probe,
)

from capability_exchange.diagnosis import (
    CapabilityState,
    FoundationCapability,
    SafetyBoundary,
    assess,
    negative_rule_ids,
)
from capability_exchange.diagnosis import engine as engine_module
from capability_exchange.evidence import EvidenceItem, EvidenceLevel, EvidenceState
from capability_exchange.jobs import SuccessContract

#: rule_id → fixture test name; the coverage test asserts totality.
FIXTURES: dict[str, str] = {}


def covers(rule_id: str):
    def decorate(func):
        FIXTURES[rule_id] = func.__name__
        return func

    return decorate


def find(map_, capability: FoundationCapability):
    (job,) = map_.jobs
    (found,) = [f for f in job.findings if f.capability is capability]
    return found


# --- Ownership & Portability ------------------------------------------------


@covers("never-move-delete-export-without-approval")
def test_an_unapproved_export_is_an_overbroad_boundary() -> None:
    map_ = assess(
        [contract()],
        envelope(observed_probe("unapproved-export", "receipt:export-event")),
    )
    ownership = find(map_, FoundationCapability.OWNERSHIP_PORTABILITY)
    assert ownership.safety_boundary is SafetyBoundary.OVERBROAD


@covers("file-presence-is-not-portability-proof")
def test_local_file_presence_is_not_portability_proof() -> None:
    map_ = assess(
        [contract()], envelope(observed_probe("installation-shape", "dir:claude-home"))
    )
    ownership = find(map_, FoundationCapability.OWNERSHIP_PORTABILITY)
    assert ownership.capability_state is CapabilityState.NOT_DEMONSTRATED
    assert ownership.evidence_level is not EvidenceLevel.VERIFIED


# --- Privacy & Minimal Disclosure --------------------------------------------


@covers("unknown-access-paths-remain-unknown")
def test_unassessed_privacy_stays_unknown_never_assumed() -> None:
    map_ = assess([contract()], envelope(observed_probe("skills-present")))
    privacy = find(map_, FoundationCapability.PRIVACY_MINIMAL_DISCLOSURE)
    assert privacy.capability_state is CapabilityState.UNKNOWN
    assert privacy.evidence_level is EvidenceLevel.UNKNOWN
    assert privacy.safety_boundary is SafetyBoundary.UNCLEAR


@covers("diagnosis-never-scans-secrets-or-unrelated-content")
def test_evidence_outside_declared_patterns_grounds_nothing() -> None:
    """A probe outside every declared observable-evidence pattern — secret
    stores, unrelated private content — contributes to no finding at all."""
    map_ = assess(
        [contract()],
        envelope(observed_probe("planted-secret-store", "path:not-in-any-pattern")),
    )
    for finding in map_.jobs[0].findings:
        assert finding.evidence == ()


# --- Context & Orientation ----------------------------------------------------


@covers("stale-and-inferred-context-must-be-labeled")
def test_stale_context_is_labeled_stale_and_supports_nothing() -> None:
    old = EvidenceItem(
        state=EvidenceState.OBSERVED,
        captured_at=COLLECTED_AT - timedelta(days=90),
        stale_after=timedelta(days=14),
        reference="log:recent-activity",
    )
    map_ = assess(
        [contract()],
        envelope(probe("recent-activity", old)),
        assessed_at=COLLECTED_AT,
    )
    context = find(map_, FoundationCapability.CONTEXT_ORIENTATION)
    assert context.capability_state is not CapabilityState.WORKING
    assert any(e.state is EvidenceState.STALE for e in context.evidence)
    assert any("stale" in note for note in context.uncertainty_notes)


@covers("more-context-is-not-automatically-better")
def test_more_configuration_never_upgrades_the_assessment() -> None:
    little = assess([contract()], envelope(observed_probe("instructions-present")))
    lots = assess(
        [contract()],
        envelope(
            probe(
                "instructions-present",
                *[
                    item(EvidenceState.OBSERVED, f"path:instructions-{index}")
                    for index in range(10)
                ],
            ),
            observed_probe("settings-present"),
        ),
    )
    for map_ in (little, lots):
        context = find(map_, FoundationCapability.CONTEXT_ORIENTATION)
        assert context.capability_state is CapabilityState.NOT_DEMONSTRATED
        assert context.evidence_level is EvidenceLevel.UNKNOWN


# --- Durable Memory & Provenance ----------------------------------------------


@covers("chat-history-alone-is-not-memory-proof")
def test_chat_history_alone_is_not_memory_proof() -> None:
    map_ = assess(
        [contract()],
        envelope(observed_probe("chat-history-present", "dir:chat-history")),
    )
    memory = find(map_, FoundationCapability.DURABLE_MEMORY_PROVENANCE)
    assert memory.capability_state is CapabilityState.NOT_DEMONSTRATED
    assert memory.capability_state is not CapabilityState.WORKING
    assert memory.evidence_level is not EvidenceLevel.VERIFIED


@covers("the-system-must-not-invent-memory")
def test_no_claim_supporting_memory_evidence_is_ever_synthesized() -> None:
    """Every claim-supporting evidence item in a memory finding traces back
    to a reference the envelope actually collected — the engine invents
    nothing."""
    collected = envelope(
        observed_probe("write-retrieve-correct", "receipt:memory-roundtrip"),
        observed_probe("chat-history-present", "dir:chat-history"),
    )
    collected_references = {
        evidence.reference for p in collected.probes for evidence in p.evidence
    }
    map_ = assess([contract()], collected)
    memory = find(map_, FoundationCapability.DURABLE_MEMORY_PROVENANCE)
    for evidence in memory.evidence:
        if evidence.state in (
            EvidenceState.OBSERVED,
            EvidenceState.USER_REPORTED,
            EvidenceState.INFERRED,
        ):
            assert evidence.reference in collected_references


# --- Scoped Agency & Human Control --------------------------------------------


@covers("read-access-never-implies-write-permission")
def test_read_access_never_implies_write_permission() -> None:
    """Observed read access is configuration evidence: it grounds no Working
    verdict, no Verified level, and never a Safe boundary."""
    map_ = assess(
        [contract()],
        envelope(observed_probe("read-access-observed", "config:read-scope")),
    )
    agency = find(map_, FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL)
    assert agency.capability_state is not CapabilityState.WORKING
    assert agency.evidence_level is not EvidenceLevel.VERIFIED
    assert agency.safety_boundary is not SafetyBoundary.SAFE


# --- Safe Change & Recovery ----------------------------------------------------


@covers("diagnosis-never-mutates")
def test_diagnosis_never_mutates(tmp_path, monkeypatch) -> None:
    """The engine writes nothing anywhere and its source contains no write
    call: it maps two in-memory values to a third."""
    monkeypatch.chdir(tmp_path)
    assess([contract()], envelope(observed_probe("skills-present")))
    assert list(tmp_path.iterdir()) == []
    source = inspect.getsource(engine_module)
    for token in ("open(", "write_text", "write_bytes", "unlink", "mkdir", "rename("):
        assert token not in source


@covers("no-guaranteed-recovery-no-automated-adaptation")
def test_diagnosis_offers_no_adaptation_entry_point() -> None:
    import capability_exchange.diagnosis as package

    callables = [name for name in package.__all__ if name.islower()]
    assert callables  # the surface exists
    for name in dir(package):
        lowered = name.lower()
        for token in ("adapt", "apply", "install", "heal", "mutate"):
            assert token not in lowered


# --- Honest Health & Observability ---------------------------------------------


@covers("file-presence-never-means-healthy")
def test_file_presence_never_means_healthy() -> None:
    map_ = assess(
        [contract()],
        envelope(
            observed_probe("skills-present"),
            observed_probe("instructions-present", "path:claude-md"),
            observed_probe("settings-present", "path:settings-json"),
        ),
    )
    health = find(map_, FoundationCapability.HONEST_HEALTH_OBSERVABILITY)
    assert health.capability_state is CapabilityState.NOT_DEMONSTRATED
    assert health.capability_state is not CapabilityState.WORKING
    assert health.evidence_level is not EvidenceLevel.VERIFIED


@covers("uncertainty-remains-visible")
def test_instrument_failure_is_reported_never_hidden() -> None:
    from capability_exchange.adapter import InstrumentHealth

    map_ = assess(
        [contract()],
        envelope(
            probe(
                "live-check",
                health=InstrumentHealth.COULD_NOT_CHECK,
                detail="live checks were out of the approved scope",
            )
        ),
    )
    health = find(map_, FoundationCapability.HONEST_HEALTH_OBSERVABILITY)
    assert health.capability_state is CapabilityState.UNKNOWN
    assert any("could not assess live-check" in n for n in health.uncertainty_notes)
    assert any(e.state is EvidenceState.BLOCKED for e in health.evidence)


# --- Compounding & Correctability ----------------------------------------------


@covers("no-autonomous-permanent-self-modification")
def test_autonomous_self_modification_is_overbroad() -> None:
    map_ = assess(
        [contract()],
        envelope(
            observed_probe("explicit-promotion-observed", "receipt:promotion-1"),
            observed_probe("autonomous-self-modification", "log:self-change"),
        ),
    )
    compounding = find(map_, FoundationCapability.COMPOUNDING_CORRECTABILITY)
    assert compounding.safety_boundary is SafetyBoundary.OVERBROAD
    assert any("beyond what this job requires" in n for n in compounding.uncertainty_notes)


@covers("one-systems-pattern-is-not-universal-truth")
def test_findings_stay_scoped_to_one_system_and_job() -> None:
    """Two confirmed jobs get independent findings; nothing rolls one job's
    result into another's, and no map field speaks for 'systems in general'."""
    map_ = assess(
        [contract("alpha-job"), contract("beta-job")],
        envelope(observed_probe("explicit-promotion-observed", "receipt:promotion-1")),
    )
    assert len(map_.jobs) == 2
    for job in map_.jobs:
        for finding in job.findings:
            assert finding.job_id == job.job_id
    field_names = set(SuccessContract.model_fields) | {
        name for job in map_.jobs for name in type(job).model_fields
    }
    assert "universal" not in " ".join(field_names)


# --- Coverage: every encoded negative rule has a fixture -----------------------


def test_every_negative_rule_has_a_fixture() -> None:
    assert set(FIXTURES) == set(negative_rule_ids()), (
        "every encoded #351 negative rule must have exactly one fixture test; "
        f"missing={sorted(set(negative_rule_ids()) - set(FIXTURES))} "
        f"extra={sorted(set(FIXTURES) - set(negative_rule_ids()))}"
    )
