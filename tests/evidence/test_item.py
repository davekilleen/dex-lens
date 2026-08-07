"""EvidenceItem tests: state + source age + non-raw reference (R2).

Gate source of truth: docs/handoff/sources/gates.md R2.
- Every evidence item carries state, source age, and a non-raw reference.
- Hostile fixture: a "reference" containing raw file content fails validation.
- Missing/unknown state coerces to `not-assessed`.
- Stale-beyond-threshold evidence degrades to `stale` automatically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from capability_exchange.evidence.item import (
    REFERENCE_MAX_LENGTH,
    EvidenceItem,
)
from capability_exchange.evidence.states import EvidenceState

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


def make_item(**overrides: object) -> EvidenceItem:
    payload: dict[str, object] = {
        "state": "observed",
        "captured_at": NOW - timedelta(hours=1),
        "reference": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    }
    payload.update(overrides)
    return EvidenceItem(**payload)


class TestStateHandling:
    def test_valid_state_accepted(self) -> None:
        assert make_item(state="observed").state is EvidenceState.OBSERVED

    def test_unknown_state_coerces_to_not_assessed(self) -> None:
        assert make_item(state="totally-new-state").state is EvidenceState.NOT_ASSESSED

    def test_missing_state_coerces_to_not_assessed(self) -> None:
        item = EvidenceItem(
            captured_at=NOW - timedelta(hours=1),
            reference="path:.claude/settings.json",
        )
        assert item.state is EvidenceState.NOT_ASSESSED

    def test_none_state_coerces_to_not_assessed(self) -> None:
        assert make_item(state=None).state is EvidenceState.NOT_ASSESSED


class TestSourceAge:
    def test_captured_at_required(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceItem(state="observed", reference="path:CLAUDE.md")

    def test_naive_timestamp_rejected(self) -> None:
        """Fail closed: an ambiguous (naive) timestamp is an unverifiable age."""
        with pytest.raises(ValidationError):
            make_item(captured_at=datetime(2026, 8, 7, 12, 0, 0))  # noqa: DTZ001

    def test_age_is_now_minus_captured_at(self) -> None:
        item = make_item(captured_at=NOW - timedelta(hours=3))
        assert item.age(now=NOW) == timedelta(hours=3)

    def test_fresh_item_keeps_its_state(self) -> None:
        item = make_item(stale_after=timedelta(days=7))
        assert item.effective_state(now=NOW) is EvidenceState.OBSERVED

    def test_stale_beyond_threshold_degrades_to_stale(self) -> None:
        item = make_item(
            captured_at=NOW - timedelta(days=30),
            stale_after=timedelta(days=7),
        )
        assert item.effective_state(now=NOW) is EvidenceState.STALE

    def test_no_threshold_means_no_silent_staleness_but_state_kept(self) -> None:
        item = make_item(captured_at=NOW - timedelta(days=400), stale_after=None)
        assert item.effective_state(now=NOW) is EvidenceState.OBSERVED

    def test_future_captured_at_is_unverifiable_and_supports_nothing(self) -> None:
        """Fail closed: evidence claiming to be captured in the future has an
        unverifiable age; it degrades to `not-assessed`."""
        item = make_item(captured_at=NOW + timedelta(hours=2))
        assert item.effective_state(now=NOW) is EvidenceState.NOT_ASSESSED

    def test_terminal_states_do_not_degrade_to_stale(self) -> None:
        for state in (EvidenceState.ABSENT, EvidenceState.WITHDRAWN, EvidenceState.BLOCKED):
            item = make_item(
                state=state,
                captured_at=NOW - timedelta(days=30),
                stale_after=timedelta(days=7),
            )
            assert item.effective_state(now=NOW) is state


class TestNonRawReference:
    """A reference is a locator/digest, never a payload."""

    @pytest.mark.parametrize(
        "good",
        [
            "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "path:.claude/skills/review/SKILL.md",
            "probe:memory/durable-recall#run-3",
            "redacted:aws-credential-detected (bytes withheld)",
            "interview:job-2/answer-4",
        ],
    )
    def test_locators_and_digests_accepted(self, good: str) -> None:
        assert make_item(reference=good).reference == good

    def test_empty_reference_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_item(reference="")

    def test_multiline_raw_file_content_rejected(self) -> None:
        raw = "# CLAUDE.md\n\nAlways run the linter.\nNever push to main.\n"
        with pytest.raises(ValidationError):
            make_item(reference=raw)

    def test_single_newline_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_item(reference="path:a\nb")

    def test_carriage_return_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_item(reference="path:a\rb")

    def test_control_characters_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_item(reference="path:a\x00b")

    def test_overlong_reference_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_item(reference="x" * (REFERENCE_MAX_LENGTH + 1))

    def test_pem_key_material_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_item(reference="-----BEGIN RSA PRIVATE KEY----- MIIEow...")

    def test_prose_payload_rejected(self) -> None:
        """A long run of prose is file content wearing a reference field."""
        prose = (
            "the quick brown fox jumps over the lazy dog and then continues "
            "running through the configuration explaining every step of the "
            "workflow in detail so that anyone reading this later understands"
        )
        with pytest.raises(ValidationError):
            make_item(reference=prose)

    @given(
        st.text(max_size=100),
        st.sampled_from(["\n", "\r", "\x00"]),
        st.text(max_size=100),
    )
    def test_any_reference_with_line_breaks_or_nul_is_rejected(
        self, before: str, bad_char: str, after: str
    ) -> None:
        with pytest.raises(ValidationError):
            make_item(reference=before + bad_char + after)

    @given(st.integers(min_value=REFERENCE_MAX_LENGTH + 1, max_value=REFERENCE_MAX_LENGTH * 4))
    def test_any_overlong_reference_is_rejected(self, size: int) -> None:
        with pytest.raises(ValidationError):
            make_item(reference="a" * size)


class TestValidationBypassRoutes:
    """Adversarial M1 finding: R2's non-raw-reference rule must hold on the
    validation-skipping routes too.

    ``model_construct`` and ``model_copy`` skip validators by design, so a
    raw payload could be smuggled into a ``reference`` and serialized. The
    codebase already closes exactly these routes on ``AdapterContract``;
    the R2 boundary needs the same treatment.
    """

    def test_model_construct_rejects_a_raw_payload_reference(self) -> None:
        # single-line, so the key-marker rule is what refuses it
        with pytest.raises(ValueError, match="key/secret block markers"):
            EvidenceItem.model_construct(
                state=EvidenceState.OBSERVED,
                captured_at=datetime.now(UTC),
                reference="-----BEGIN OPENSSH PRIVATE KEY----- b3BlbnNzaC1rZXk=",
            )

    def test_model_construct_rejects_a_multiline_payload_reference(self) -> None:
        with pytest.raises(ValueError, match="line breaks or control characters"):
            EvidenceItem.model_construct(
                state=EvidenceState.OBSERVED,
                captured_at=datetime.now(UTC),
                reference="-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n",
            )

    def test_model_construct_accepts_a_real_locator(self) -> None:
        item = EvidenceItem.model_construct(
            state=EvidenceState.OBSERVED,
            captured_at=datetime.now(UTC),
            reference="probe:settings-present",
        )
        assert item.reference == "probe:settings-present"

    def test_model_copy_update_rejects_a_raw_payload_reference(self) -> None:
        item = EvidenceItem(
            state=EvidenceState.OBSERVED,
            captured_at=datetime.now(UTC),
            reference="probe:settings-present",
        )
        with pytest.raises(ValueError, match="line breaks or control characters"):
            item.model_copy(update={"reference": "line one\nline two\nline three"})


class TestImmutabilityAndClosedSchema:
    def test_items_are_frozen(self) -> None:
        item = make_item()
        with pytest.raises(ValidationError):
            item.state = EvidenceState.OBSERVED  # type: ignore[misc]

    def test_extra_fields_rejected(self) -> None:
        """Closed schema: no field without a declared meaning (G2 posture)."""
        with pytest.raises(ValidationError):
            make_item(raw_content="secret bytes")
