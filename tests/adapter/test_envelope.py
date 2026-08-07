"""Adapter result envelope: deterministic collector output, honest instruments.

Per-probe instrument grammar is healthy / intentionally-off / broken /
could-not-check — instrument health, NOT Evidence Level (HANDOFF 3.2 item 2:
the axes are separate; conflating them would silently turn health into
evidence). Instrument failure is reported, never counted as success.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from capability_exchange.adapter.envelope import (
    FAILED_INSTRUMENT_HEALTHS,
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.boundary.serialization import (
    EphemeralByDefaultError,
    NoTransmissibleFieldsError,
)
from capability_exchange.evidence import EvidenceItem, EvidenceLevel, EvidenceState

CAPTURED = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def item(state: EvidenceState = EvidenceState.OBSERVED, ref: str = "probe:skills") -> EvidenceItem:
    return EvidenceItem(state=state, captured_at=CAPTURED, reference=ref)


def probe(
    probe_id: str = "skills-present",
    health: InstrumentHealth = InstrumentHealth.HEALTHY,
    **kwargs: object,
) -> ProbeResult:
    if health is not InstrumentHealth.HEALTHY:
        kwargs.setdefault("detail", "instrument state reported honestly")
    if health is InstrumentHealth.HEALTHY:
        kwargs.setdefault("evidence", (item(),))
    return ProbeResult(probe_id=probe_id, health=health, **kwargs)


def envelope(*probes: ProbeResult) -> AdapterResultEnvelope:
    return AdapterResultEnvelope(
        adapter_id="claude-code-macos",
        contract_version="1.0.0",
        collected_at=CAPTURED,
        probes=probes or (probe(),),
    )


class TestInstrumentGrammar:
    def test_health_vocabulary_is_exactly_the_doctor_grammar(self) -> None:
        assert {h.value for h in InstrumentHealth} == {
            "healthy",
            "intentionally-off",
            "broken",
            "could-not-check",
        }

    def test_instrument_health_is_not_evidence_level(self) -> None:
        # HANDOFF 3.2 item 2: separate axes — health answers "is the
        # instrument healthy?", Evidence Level answers "how is a claim known?".
        assert {h.value for h in InstrumentHealth}.isdisjoint(
            {level.value for level in EvidenceLevel}
        )

    def test_instrument_health_is_not_an_evidence_state_either(self) -> None:
        assert {h.value for h in InstrumentHealth}.isdisjoint(
            {s.value for s in EvidenceState}
        )

    def test_unknown_health_is_rejected_not_coerced(self) -> None:
        # Closed vocabulary: an unknown health value must refuse, never
        # silently become a success.
        with pytest.raises(ValidationError):
            ProbeResult(probe_id="p-1", health="ok")


class TestProbeResult:
    def test_healthy_probe_with_observed_evidence(self) -> None:
        result = probe()
        assert result.succeeded
        assert result.evidence[0].state is EvidenceState.OBSERVED

    def test_broken_probe_never_carries_claim_supporting_evidence(self) -> None:
        with pytest.raises(ValidationError, match="never counted as success"):
            ProbeResult(
                probe_id="p-1",
                health=InstrumentHealth.BROKEN,
                detail="probe crashed",
                evidence=(item(EvidenceState.OBSERVED),),
            )

    def test_could_not_check_never_carries_claim_supporting_evidence(self) -> None:
        with pytest.raises(ValidationError, match="never counted as success"):
            ProbeResult(
                probe_id="p-1",
                health=InstrumentHealth.COULD_NOT_CHECK,
                detail="scope excluded the target",
                evidence=(item(EvidenceState.USER_REPORTED),),
            )

    def test_broken_probe_may_carry_non_claim_evidence(self) -> None:
        result = ProbeResult(
            probe_id="p-1",
            health=InstrumentHealth.BROKEN,
            detail="probe crashed before reading",
            evidence=(item(EvidenceState.BLOCKED, ref="probe:p-1"),),
        )
        assert not result.succeeded

    def test_instrument_failure_must_be_reported(self) -> None:
        # "Instrument failure is reported, never counted as success":
        # a non-healthy probe with no detail is an unreported failure.
        for health in (
            InstrumentHealth.BROKEN,
            InstrumentHealth.COULD_NOT_CHECK,
            InstrumentHealth.INTENTIONALLY_OFF,
        ):
            with pytest.raises(ValidationError, match="report"):
                ProbeResult(probe_id="p-1", health=health)

    def test_detail_rejects_multiline_payloads(self) -> None:
        with pytest.raises(ValidationError):
            ProbeResult(
                probe_id="p-1",
                health=InstrumentHealth.BROKEN,
                detail="line one\nline two",
            )

    def test_detail_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            ProbeResult(
                probe_id="p-1",
                health=InstrumentHealth.BROKEN,
                detail="x" * 4096,
            )

    def test_probe_id_must_be_kebab_case(self) -> None:
        with pytest.raises(ValidationError):
            ProbeResult(probe_id="Not A Probe", health=InstrumentHealth.HEALTHY)


class TestEnvelopeDeterminism:
    def test_probe_order_is_canonicalized(self) -> None:
        a, b = probe("alpha-probe"), probe("beta-probe")
        env_one = envelope(a, b)
        env_two = envelope(b, a)
        assert env_one == env_two
        assert env_one.model_dump_json() == env_two.model_dump_json()
        assert [p.probe_id for p in env_one.probes] == ["alpha-probe", "beta-probe"]

    def test_duplicate_probe_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            envelope(probe("same-probe"), probe("same-probe"))

    def test_naive_collected_at_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdapterResultEnvelope(
                adapter_id="claude-code-macos",
                contract_version="1.0.0",
                collected_at=datetime(2026, 8, 7, 12, 0),  # noqa: DTZ001
                probes=(probe(),),
            )

    def test_empty_envelope_rejected(self) -> None:
        # A collector that checked nothing must say could-not-check per
        # probe, not return an empty envelope that implies a clean bill.
        with pytest.raises(ValidationError):
            AdapterResultEnvelope(
                adapter_id="claude-code-macos",
                contract_version="1.0.0",
                collected_at=CAPTURED,
                probes=(),
            )


class TestEnvelopeRoundTrip:
    """G2 serialization boundary: every field is inventoried; the envelope
    round-trips through the packaged inventory with no test substitute."""

    def full_envelope(self) -> AdapterResultEnvelope:
        return envelope(
            probe("skills-present"),
            probe(
                "hooks-configured",
                InstrumentHealth.INTENTIONALLY_OFF,
                detail="hooks disabled by the person's own settings",
            ),
            probe(
                "memory-files",
                InstrumentHealth.BROKEN,
                detail="probe crashed before reading",
                evidence=(item(EvidenceState.BLOCKED, ref="probe:memory-files"),),
            ),
            probe(
                "session-logs",
                InstrumentHealth.COULD_NOT_CHECK,
                detail="path excluded from the approved scope",
            ),
        )

    def test_python_round_trip(self) -> None:
        env = self.full_envelope()
        assert AdapterResultEnvelope.model_validate(env.model_dump()) == env

    def test_json_round_trip(self) -> None:
        env = self.full_envelope()
        payload = json.loads(env.model_dump_json())
        assert AdapterResultEnvelope.model_validate(payload) == env

    def test_envelope_is_ephemeral_by_default(self) -> None:
        with pytest.raises(EphemeralByDefaultError):
            self.full_envelope().dump_for_storage()

    def test_envelope_is_never_transmissible(self) -> None:
        with pytest.raises(NoTransmissibleFieldsError):
            self.full_envelope().dump_for_transmission()


HEALTH_STRATEGY = st.lists(
    st.sampled_from(list(InstrumentHealth)), min_size=1, max_size=8
)


class TestBrokenInstrumentNeverSuccess:
    @settings(max_examples=50, deadline=None)
    @given(healths=HEALTH_STRATEGY)
    def test_failed_instruments_are_reported_never_successes(
        self, healths: list[InstrumentHealth]
    ) -> None:
        probes = tuple(
            probe(f"probe-{index}", health) for index, health in enumerate(healths)
        )
        env = envelope(*probes)

        successes = env.successful_probes
        failures = env.reported_failures

        assert all(p.health is InstrumentHealth.HEALTHY for p in successes)
        assert all(p.health in FAILED_INSTRUMENT_HEALTHS for p in failures)
        assert not {p.probe_id for p in successes} & {p.probe_id for p in failures}

        counts = env.health_counts()
        assert sum(counts.values()) == len(probes)
        assert counts[InstrumentHealth.BROKEN] == sum(
            1 for h in healths if h is InstrumentHealth.BROKEN
        )
        assert len(successes) == counts[InstrumentHealth.HEALTHY]

    def test_stale_evidence_does_not_make_an_instrument_unhealthy(self) -> None:
        # Axis separation the other way round: a healthy instrument can
        # honestly report evidence that later degrades to stale.
        result = ProbeResult(
            probe_id="p-1",
            health=InstrumentHealth.HEALTHY,
            evidence=(
                EvidenceItem(
                    state=EvidenceState.OBSERVED,
                    captured_at=CAPTURED,
                    stale_after=timedelta(days=1),
                    reference="probe:p-1",
                ),
            ),
        )
        later = CAPTURED + timedelta(days=2)
        assert result.succeeded
        assert result.evidence[0].effective_state(now=later) is EvidenceState.STALE
