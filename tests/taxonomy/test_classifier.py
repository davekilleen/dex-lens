"""G6 classifier behavior tests (module M-C slice).

Gate source of truth: docs/handoff/sources/gates.md G6.
- Deterministic, rule-based, fully local — no model call anywhere.
- Unclassifiable or ambiguous input → high-impact (fail closed).
- Rule-based determinations are honestly marked `inferred` (R2 vocabulary);
  fail-closed determinations carry `not-assessed`.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from capability_exchange.evidence.states import EvidenceState
from capability_exchange.taxonomy.categories import HighImpactCategory
from capability_exchange.taxonomy.classifier import (
    ClassificationBasis,
    ImpactClassification,
    automated_adaptation_allowed,
    classify_job,
    classify_text,
)


class TestPlainHighImpactPhrasings:
    @pytest.mark.parametrize(
        ("text", "category"),
        [
            ("Send a follow-up email to the vendor", HighImpactCategory.SENDING_MESSAGES),
            ("Buy replacement ink for the printer", HighImpactCategory.MONEY_PURCHASING),
            ("Grant read access to the contractor", HighImpactCategory.PERMISSIONS),
            ("Delete last month's temporary files", HighImpactCategory.DELETION),
            ("Rotate the API keys on the server", HighImpactCategory.CREDENTIALS),
            ("Track my medication schedule", HighImpactCategory.HEALTH),
            ("Review the contract with my lawyer", HighImpactCategory.LEGAL),
            ("Rebalance my retirement portfolio", HighImpactCategory.FINANCIAL_DECISIONS),
            (
                "Organize the confidential client files",
                HighImpactCategory.THIRD_PARTY_CONFIDENTIAL_DATA,
            ),
        ],
    )
    def test_each_category_is_detected(
        self, text: str, category: HighImpactCategory
    ) -> None:
        result = classify_text(text)
        assert result.high_impact
        assert category in result.categories
        assert result.basis is ClassificationBasis.RULE_MATCH
        assert result.evidence_state is EvidenceState.INFERRED
        assert not automated_adaptation_allowed(result)

    def test_a_job_may_touch_several_categories(self) -> None:
        result = classify_text("Email the confidential patient records to the clinic")
        assert HighImpactCategory.SENDING_MESSAGES in result.categories
        assert HighImpactCategory.THIRD_PARTY_CONFIDENTIAL_DATA in result.categories
        assert HighImpactCategory.HEALTH in result.categories


class TestBenignJobs:
    @pytest.mark.parametrize(
        "text",
        [
            "Summarize my meeting notes into action items",
            "Group my research bookmarks by topic",
            "Suggest a weekly plan for learning the guitar",
        ],
    )
    def test_genuinely_benign_jobs_stay_benign(self, text: str) -> None:
        result = classify_text(text)
        assert not result.high_impact
        assert result.categories == frozenset()
        assert result.basis is ClassificationBasis.NO_MATCH
        # Benign is still only an inference, never an observation.
        assert result.evidence_state is EvidenceState.INFERRED
        assert automated_adaptation_allowed(result)


class TestFailClosedInputs:
    @pytest.mark.parametrize(
        "bad_input",
        [None, 42, b"delete everything", [], {}, "", "   ", "\t\n", "!!! ... ---", "🙂 🙂"],
    )
    def test_unclassifiable_input_is_high_impact(self, bad_input: object) -> None:
        result = classify_text(bad_input)
        assert result.high_impact
        assert result.basis is ClassificationBasis.UNCLASSIFIABLE
        assert result.evidence_state is EvidenceState.NOT_ASSESSED
        assert not automated_adaptation_allowed(result)

    @pytest.mark.parametrize(
        "text",
        [
            "Handle everything for me",
            "Just do whatever seems useful",
            "Take care of anything that comes up",
            "Act on my behalf across all my accounts",
            "You have carte blanche with my files",
        ],
    )
    def test_ambiguous_catch_all_scope_is_high_impact(self, text: str) -> None:
        result = classify_text(text)
        assert result.high_impact
        assert not automated_adaptation_allowed(result)

    def test_single_word_job_is_too_ambiguous_to_bound(self) -> None:
        result = classify_text("help")
        assert result.high_impact
        assert result.basis is ClassificationBasis.AMBIGUOUS_SCOPE
        assert result.evidence_state is EvidenceState.NOT_ASSESSED


class TestSuccessContractFields:
    def test_contract_fields_are_classified_with_the_description(self) -> None:
        # Benign-sounding description; the Success Contract's desired
        # outcome reveals message-sending.
        result = classify_job(
            "Keep my professional network organized",
            {
                "situation": "I meet many people at conferences",
                "desired_outcome": "each new contact gets a welcome email from me",
                "success_evidence": "everyone I met hears back within a day",
            },
        )
        assert result.high_impact
        assert HighImpactCategory.SENDING_MESSAGES in result.categories

    def test_non_string_field_value_fails_closed(self) -> None:
        result = classify_job("Organize my notes", {"boundaries": object()})
        assert result.high_impact
        assert result.basis is ClassificationBasis.UNCLASSIFIABLE

    def test_non_mapping_fields_fail_closed(self) -> None:
        result = classify_job("Organize my notes", ["not", "a", "mapping"])  # type: ignore[arg-type]
        assert result.high_impact
        assert result.basis is ClassificationBasis.UNCLASSIFIABLE

    def test_non_string_description_fails_closed(self) -> None:
        result = classify_job(None)
        assert result.high_impact
        assert result.basis is ClassificationBasis.UNCLASSIFIABLE


class TestStructuralInvariants:
    def test_categories_without_high_impact_is_unrepresentable(self) -> None:
        with pytest.raises(ValueError):
            ImpactClassification(
                high_impact=False,
                categories=frozenset({HighImpactCategory.DELETION}),
                basis=ClassificationBasis.RULE_MATCH,
                evidence_state=EvidenceState.INFERRED,
            )

    @pytest.mark.parametrize(
        "basis",
        [
            ClassificationBasis.RULE_MATCH,
            ClassificationBasis.AMBIGUOUS_SCOPE,
            ClassificationBasis.UNCLASSIFIABLE,
            ClassificationBasis.CLASSIFIER_UNAVAILABLE,
        ],
    )
    def test_only_no_match_may_be_non_high_impact(
        self, basis: ClassificationBasis
    ) -> None:
        with pytest.raises(ValueError):
            ImpactClassification(
                high_impact=False,
                categories=frozenset(),
                basis=basis,
                evidence_state=EvidenceState.NOT_ASSESSED,
            )

    @given(st.text(max_size=2000))
    def test_total_over_arbitrary_text_and_deterministic(self, text: str) -> None:
        first = classify_text(text)
        second = classify_text(text)
        assert isinstance(first, ImpactClassification)
        assert first == second
        if first.categories:
            assert first.high_impact
        if not first.high_impact:
            assert first.basis is ClassificationBasis.NO_MATCH

    @given(
        st.one_of(
            st.none(),
            st.integers(),
            st.binary(max_size=64),
            st.text(max_size=200),
            st.lists(st.text(max_size=20), max_size=5),
        )
    )
    def test_never_raises_on_arbitrary_input(self, value: object) -> None:
        result = classify_text(value)
        assert isinstance(result, ImpactClassification)

    def test_accent_and_case_evasion_does_not_help(self) -> None:
        assert classify_text("ELIMINAR los archivos viejos").high_impact
        assert classify_text("SUPPRIMER  les   fichiers").high_impact
        assert classify_text("LÖSCHEN der alten Daten").high_impact
