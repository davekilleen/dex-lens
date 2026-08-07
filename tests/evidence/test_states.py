"""R2 closed evidence-state vocabulary tests (module M-B slice).

Gate source of truth: docs/handoff/sources/gates.md R2.
- The vocabulary is closed: exactly the eleven declared states, nothing else.
- Missing or unknown state coerces to `not-assessed` and supports nothing.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from capability_exchange.evidence.states import (
    CLAIM_SUPPORTING_STATES,
    EvidenceState,
    coerce_state,
    supports_claims,
)

R2_VOCABULARY = {
    "observed",
    "user-reported",
    "inferred",
    "stale",
    "conflicting",
    "absent",
    "not-assessed",
    "insufficient",
    "blocked",
    "unverified",
    "withdrawn",
}


class TestClosedVocabulary:
    def test_exactly_the_eleven_r2_states(self) -> None:
        assert {member.value for member in EvidenceState} == R2_VOCABULARY
        assert len(EvidenceState) == 11

    def test_states_are_strings(self) -> None:
        for member in EvidenceState:
            assert isinstance(member.value, str)

    def test_not_assessed_exists(self) -> None:
        assert EvidenceState.NOT_ASSESSED.value == "not-assessed"


class TestCoercion:
    @pytest.mark.parametrize("value", sorted(R2_VOCABULARY))
    def test_exact_values_round_trip(self, value: str) -> None:
        assert coerce_state(value).value == value

    def test_enum_members_pass_through(self) -> None:
        for member in EvidenceState:
            assert coerce_state(member) is member

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("user_reported", EvidenceState.USER_REPORTED),
            ("user reported", EvidenceState.USER_REPORTED),
            ("Not Assessed", EvidenceState.NOT_ASSESSED),
            ("not_assessed", EvidenceState.NOT_ASSESSED),
            ("  observed  ", EvidenceState.OBSERVED),
            ("OBSERVED", EvidenceState.OBSERVED),
        ],
    )
    def test_normalization_of_separator_and_case(
        self, raw: str, expected: EvidenceState
    ) -> None:
        assert coerce_state(raw) is expected

    @pytest.mark.parametrize(
        "unknown",
        [None, "", "verified", "healthy", "OK", "primitive-state", 42, object(), b"observed"],
    )
    def test_unknown_or_missing_coerces_to_not_assessed(self, unknown: object) -> None:
        """Fail closed: anything outside the vocabulary is `not-assessed`."""
        assert coerce_state(unknown) is EvidenceState.NOT_ASSESSED

    @given(st.text())
    def test_arbitrary_text_always_lands_in_the_closed_vocabulary(self, raw: str) -> None:
        state = coerce_state(raw)
        assert isinstance(state, EvidenceState)

    @given(st.one_of(st.none(), st.integers(), st.floats(), st.binary(), st.booleans()))
    def test_non_string_garbage_coerces_to_not_assessed(self, garbage: object) -> None:
        assert coerce_state(garbage) is EvidenceState.NOT_ASSESSED


class TestSupportsNothing:
    def test_not_assessed_supports_nothing(self) -> None:
        assert supports_claims(EvidenceState.NOT_ASSESSED) is False

    def test_absent_supports_nothing(self) -> None:
        assert supports_claims(EvidenceState.ABSENT) is False

    def test_only_observed_user_reported_inferred_support_claims(self) -> None:
        assert CLAIM_SUPPORTING_STATES == frozenset(
            {EvidenceState.OBSERVED, EvidenceState.USER_REPORTED, EvidenceState.INFERRED}
        )
        for member in EvidenceState:
            assert supports_claims(member) is (member in CLAIM_SUPPORTING_STATES)

    @given(st.one_of(st.none(), st.text()))
    def test_coerced_unknown_state_supports_nothing(self, raw: object) -> None:
        state = coerce_state(raw)
        if state is EvidenceState.NOT_ASSESSED:
            assert supports_claims(state) is False
