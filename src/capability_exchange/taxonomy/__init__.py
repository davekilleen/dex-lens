"""G6 high-impact job taxonomy (module M-C slice; gates.md G6).

A closed nine-category vocabulary, a deterministic rule-based classifier
biased for zero false negatives, a labeled corpus, and a per-session
fail-closed wrapper. Read-only diagnosis machinery: nothing here persists,
transmits, or mutates anything.
"""

from capability_exchange.taxonomy.categories import HighImpactCategory
from capability_exchange.taxonomy.classifier import (
    ClassificationBasis,
    ImpactClassification,
    SessionClassifier,
    automated_adaptation_allowed,
    classify_job,
    classify_text,
)
from capability_exchange.taxonomy.corpus import CorpusEntry, CorpusError, load_corpus

__all__ = [
    "ClassificationBasis",
    "CorpusEntry",
    "CorpusError",
    "HighImpactCategory",
    "ImpactClassification",
    "SessionClassifier",
    "automated_adaptation_allowed",
    "classify_job",
    "classify_text",
    "load_corpus",
]
