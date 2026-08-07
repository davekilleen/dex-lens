"""G6 closed nine-category vocabulary tests (module M-C slice).

Gate source of truth: docs/handoff/sources/gates.md G6 — jobs involving
sending messages, money/purchasing, permissions, deletion, credentials,
health, legal, financial decisions, or third-party confidential data are
high-impact.
"""

from __future__ import annotations

from capability_exchange.taxonomy.categories import HighImpactCategory

G6_VOCABULARY = {
    "sending-messages",
    "money-purchasing",
    "permissions",
    "deletion",
    "credentials",
    "health",
    "legal",
    "financial-decisions",
    "third-party-confidential-data",
}


class TestClosedVocabulary:
    def test_exactly_the_nine_g6_categories(self) -> None:
        assert {member.value for member in HighImpactCategory} == G6_VOCABULARY
        assert len(HighImpactCategory) == 9

    def test_values_are_stable_machine_readable_identifiers(self) -> None:
        for member in HighImpactCategory:
            assert member.value == member.value.strip().lower()
            assert " " not in member.value

    def test_unknown_value_is_rejected(self) -> None:
        # The vocabulary is closed: no coercion path admits a tenth category.
        import pytest

        with pytest.raises(ValueError):
            HighImpactCategory("gardening")
