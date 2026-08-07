"""G6 labeled-corpus tests (gates.md G6 test strategy a).

Gated: ZERO false negatives — every labeled high-impact entry routes to
high-impact, and at least one of its labeled categories is detected.

Recorded, never gated: the false-positive rate over the genuinely-benign
entries. It is printed honestly in the test output (`pytest -s` or on
failure) and attached as a user property so the run records it; asserting
a ceiling on it is explicitly NOT part of G6.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

import pytest

from capability_exchange.taxonomy.categories import HighImpactCategory
from capability_exchange.taxonomy.classifier import classify_job
from capability_exchange.taxonomy.corpus import CorpusEntry, load_corpus

MIN_EXAMPLES_PER_CATEGORY = 15
MIN_BENIGN_EXAMPLES = 30
MIN_NON_ENGLISH_LANGUAGES = 2


@pytest.fixture(scope="module")
def corpus() -> tuple[CorpusEntry, ...]:
    return load_corpus()


class TestCorpusShape:
    def test_at_least_fifteen_examples_per_category(
        self, corpus: tuple[CorpusEntry, ...]
    ) -> None:
        counts: Counter[HighImpactCategory] = Counter()
        for entry in corpus:
            counts.update(entry.categories)
        for category in HighImpactCategory:
            assert counts[category] >= MIN_EXAMPLES_PER_CATEGORY, category

    def test_at_least_thirty_genuinely_benign_jobs(
        self, corpus: tuple[CorpusEntry, ...]
    ) -> None:
        benign = [entry for entry in corpus if not entry.high_impact]
        assert len(benign) >= MIN_BENIGN_EXAMPLES

    def test_every_category_has_all_three_phrasing_kinds(
        self, corpus: tuple[CorpusEntry, ...]
    ) -> None:
        phrasings: dict[HighImpactCategory, set[str]] = {c: set() for c in HighImpactCategory}
        for entry in corpus:
            for category in entry.categories:
                phrasings[category].add(entry.phrasing)
        for category, kinds in phrasings.items():
            assert kinds == {"plain", "euphemistic", "multilingual"}, category

    def test_at_least_two_non_english_languages(
        self, corpus: tuple[CorpusEntry, ...]
    ) -> None:
        languages = {entry.language for entry in corpus} - {"en"}
        assert len(languages) >= MIN_NON_ENGLISH_LANGUAGES


class TestG6ZeroFalseNegatives:
    def test_zero_false_negatives_across_the_labeled_corpus(
        self, corpus: tuple[CorpusEntry, ...]
    ) -> None:
        misses: list[str] = []
        for entry in corpus:
            if not entry.high_impact:
                continue
            result = classify_job(entry.text)
            if not result.high_impact:
                misses.append(f"{entry.entry_id}: not routed high-impact")
            elif not (entry.categories & result.categories):
                found = sorted(c.value for c in result.categories)
                wanted = sorted(c.value for c in entry.categories)
                misses.append(f"{entry.entry_id}: wanted one of {wanted}, got {found}")
        assert not misses, "G6 false negatives (gated at zero):\n" + "\n".join(misses)

    def test_false_positive_rate_is_recorded_not_gated(
        self,
        corpus: tuple[CorpusEntry, ...],
        record_property: Callable[[str, object], None],
    ) -> None:
        benign = [entry for entry in corpus if not entry.high_impact]
        false_positives = [
            entry.entry_id for entry in benign if classify_job(entry.text).high_impact
        ]
        rate = len(false_positives) / len(benign)
        record_property("g6_false_positive_rate", rate)
        record_property("g6_false_positives", false_positives)
        print(
            f"\nG6 corpus false-positive rate (recorded, not gated): "
            f"{len(false_positives)}/{len(benign)} = {rate:.1%}"
            + (f"; misrouted benign entries: {false_positives}" if false_positives else "")
        )
        # The honest bound: a rate is a rate. Nothing else is asserted.
        assert 0.0 <= rate <= 1.0
