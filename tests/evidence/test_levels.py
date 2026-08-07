"""R2 state-combination → Evidence Level mapping tests (normative, total).

Gate source of truth: docs/handoff/sources/gates.md R2 and HANDOFF.md M-B:
- The mapping is TOTAL: every reachable R2 state combination maps to exactly
  one Evidence Level (Verified / Supported / Reported / Unknown).
- `stale`, `conflicting`, `insufficient`, `blocked`, `absent`, `not-assessed`
  never map to Verified.
- `observed` alone can reach Verified.
- Person-supplied material caps at Supported; the person's account
  (`user-reported`) caps at Reported.
"""

from __future__ import annotations

from itertools import chain, combinations

from hypothesis import given
from hypothesis import strategies as st

from capability_exchange.evidence.levels import (
    NEVER_VERIFIED_STATES,
    EvidenceLevel,
    evidence_level,
)
from capability_exchange.evidence.states import EvidenceState

ALL_STATES = tuple(EvidenceState)

state_sets = st.frozensets(st.sampled_from(ALL_STATES))
raw_state_inputs = st.lists(
    st.one_of(
        st.sampled_from(ALL_STATES),
        st.sampled_from([s.value for s in ALL_STATES]),
        st.none(),
        st.text(max_size=20),
    ),
    max_size=8,
)


def powerset(states: tuple[EvidenceState, ...]):
    return chain.from_iterable(combinations(states, r) for r in range(len(states) + 1))


class TestTotality:
    def test_exhaustive_every_combination_maps_to_exactly_one_level(self) -> None:
        """All 2^11 combinations of the closed vocabulary map deterministically
        to exactly one Evidence Level."""
        for combo in powerset(ALL_STATES):
            level = evidence_level(combo)
            assert isinstance(level, EvidenceLevel)
            assert evidence_level(combo) is level  # deterministic

    @given(state_sets)
    def test_every_combination_maps_to_exactly_one_level(
        self, states: frozenset[EvidenceState]
    ) -> None:
        level = evidence_level(states)
        assert isinstance(level, EvidenceLevel)
        assert evidence_level(states) is level

    @given(raw_state_inputs)
    def test_mapping_is_total_over_unclean_inputs(self, raw: list[object]) -> None:
        """Unknown strings and None coerce to `not-assessed`; the mapping never
        raises and never leaves the four-level vocabulary."""
        level = evidence_level(raw)
        assert isinstance(level, EvidenceLevel)

    @given(state_sets)
    def test_order_and_duplication_do_not_matter(
        self, states: frozenset[EvidenceState]
    ) -> None:
        as_list = list(states)
        assert evidence_level(as_list) is evidence_level(reversed(as_list))
        assert evidence_level(as_list * 3) is evidence_level(states)


class TestNeverVerified:
    def test_the_six_never_verified_states_are_declared(self) -> None:
        assert NEVER_VERIFIED_STATES == frozenset(
            {
                EvidenceState.STALE,
                EvidenceState.CONFLICTING,
                EvidenceState.INSUFFICIENT,
                EvidenceState.BLOCKED,
                EvidenceState.ABSENT,
                EvidenceState.NOT_ASSESSED,
            }
        )

    @given(state_sets)
    def test_no_combination_containing_a_never_verified_state_is_verified(
        self, states: frozenset[EvidenceState]
    ) -> None:
        if states & NEVER_VERIFIED_STATES:
            assert evidence_level(states) is not EvidenceLevel.VERIFIED

    def test_each_never_verified_state_alone_is_not_verified(self) -> None:
        for state in NEVER_VERIFIED_STATES:
            assert evidence_level({state}) is not EvidenceLevel.VERIFIED


class TestNormativeCeilings:
    def test_observed_alone_reaches_verified(self) -> None:
        assert evidence_level({EvidenceState.OBSERVED}) is EvidenceLevel.VERIFIED

    def test_user_account_alone_caps_at_reported(self) -> None:
        assert evidence_level({EvidenceState.USER_REPORTED}) is EvidenceLevel.REPORTED

    def test_inferred_alone_caps_at_supported(self) -> None:
        assert evidence_level({EvidenceState.INFERRED}) is EvidenceLevel.SUPPORTED

    def test_empty_combination_is_unknown(self) -> None:
        """No evidence at all supports nothing."""
        assert evidence_level(()) is EvidenceLevel.UNKNOWN

    def test_not_assessed_alone_is_unknown(self) -> None:
        assert evidence_level({EvidenceState.NOT_ASSESSED}) is EvidenceLevel.UNKNOWN

    @given(state_sets)
    def test_user_supplied_material_never_yields_verified(
        self, states: frozenset[EvidenceState]
    ) -> None:
        """Evidence derived from person-supplied material (exports, selected
        files, interviews) caps at Supported even when directly observed."""
        level = evidence_level(states, user_supplied_material=True)
        assert level is not EvidenceLevel.VERIFIED

    def test_user_supplied_observed_material_is_supported_not_verified(self) -> None:
        assert (
            evidence_level({EvidenceState.OBSERVED}, user_supplied_material=True)
            is EvidenceLevel.SUPPORTED
        )

    @given(state_sets)
    def test_only_direct_observation_can_reach_verified(
        self, states: frozenset[EvidenceState]
    ) -> None:
        if evidence_level(states) is EvidenceLevel.VERIFIED:
            assert EvidenceState.OBSERVED in states
            assert not states & NEVER_VERIFIED_STATES

    @given(state_sets)
    def test_conflicting_evidence_is_unknown(
        self, states: frozenset[EvidenceState]
    ) -> None:
        """Contradictory evidence cannot honestly support any level."""
        if EvidenceState.CONFLICTING in states:
            assert evidence_level(states) is EvidenceLevel.UNKNOWN

    @given(state_sets)
    def test_adding_evidence_never_raises_level_past_its_ceiling(
        self, states: frozenset[EvidenceState]
    ) -> None:
        """Adding a claim-free state (e.g. `withdrawn`) never raises the level."""
        base = evidence_level(states)
        widened = evidence_level(states | {EvidenceState.WITHDRAWN})
        assert widened.rank() <= base.rank() or base is EvidenceLevel.UNKNOWN


class TestLevelVocabulary:
    def test_exactly_four_levels(self) -> None:
        assert {level.value for level in EvidenceLevel} == {
            "verified",
            "supported",
            "reported",
            "unknown",
        }

    def test_rank_order(self) -> None:
        assert (
            EvidenceLevel.VERIFIED.rank()
            > EvidenceLevel.SUPPORTED.rank()
            > EvidenceLevel.REPORTED.rank()
            > EvidenceLevel.UNKNOWN.rank()
        )
