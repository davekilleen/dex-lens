"""G6 high-impact job classifier: deterministic, rule-based, fail closed.

Classifies a job description plus its Success Contract field text against
the closed nine-category vocabulary
(:class:`~capability_exchange.taxonomy.categories.HighImpactCategory`).

Honesty and determinism (pilot posture D8, fully local):

- No model call anywhere. Classification is keyword/stem/phrase matching
  over :mod:`capability_exchange.taxonomy.rules` — a heuristic, so every
  determination carries ``EvidenceState.INFERRED`` from the closed R2
  vocabulary, never ``observed``. Fail-closed outcomes carry
  ``EvidenceState.NOT_ASSESSED`` (nothing was meaningfully evaluated).
- Zero-false-negative design bias: rules over-match; false positives are
  acceptable and recorded by the corpus test, never gated on.

Fail closed (gates.md G6):

- Unclassifiable input (empty, non-text, no words) → high-impact.
- Ambiguous catch-all scope ("handle everything for me") → high-impact.
- Classifier error → the :class:`SessionClassifier` treats ALL jobs as
  high-impact for the rest of the session. Automation is the privilege
  that gets withdrawn, never the safety.

Nothing in this module is persisted or transmitted: classifications are
ephemeral in-session values (plain frozen dataclasses, outside the G2
serialization boundary by construction, with no inventory surface).
This module is read-only diagnosis machinery — it holds no write
capability and no mutating entry point.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from capability_exchange.evidence.states import EvidenceState
from capability_exchange.taxonomy.categories import HighImpactCategory
from capability_exchange.taxonomy.rules import AMBIGUOUS_SCOPE_PHRASES, RULE_PHRASES

__all__ = [
    "ClassificationBasis",
    "ImpactClassification",
    "SessionClassifier",
    "automated_adaptation_allowed",
    "classify_job",
    "classify_text",
]


class ClassificationBasis(StrEnum):
    """Closed vocabulary for how a classification was reached."""

    RULE_MATCH = "rule-match"  # one or more category rules matched (inferred)
    NO_MATCH = "no-match"  # evaluated, no rule matched (inferred benign)
    AMBIGUOUS_SCOPE = "ambiguous-scope"  # catch-all wording → fail closed
    UNCLASSIFIABLE = "unclassifiable"  # unusable input → fail closed
    CLASSIFIER_UNAVAILABLE = "classifier-unavailable"  # error → fail closed


@dataclass(frozen=True, slots=True)
class ImpactClassification:
    """One job's G6 classification. Ephemeral; never persisted/transmitted.

    Invariant (property-tested): ``high_impact`` is False only when
    ``basis`` is ``NO_MATCH`` and ``categories`` is empty. Every other
    basis — including every fail-closed path — is high-impact.

    ``matched_phrases`` contains only our own rule-phrase data, never an
    echo of the person's text.
    """

    high_impact: bool
    categories: frozenset[HighImpactCategory]
    basis: ClassificationBasis
    evidence_state: EvidenceState
    matched_phrases: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.categories and not self.high_impact:
            raise ValueError(
                "a classification with high-impact categories must be high-impact"
            )
        if not self.high_impact and self.basis is not ClassificationBasis.NO_MATCH:
            raise ValueError(
                "only an evaluated no-match classification may be non-high-impact; "
                f"basis {self.basis.value!r} fails closed to high-impact"
            )


def automated_adaptation_allowed(classification: ImpactClassification) -> bool:
    """Whether this job may ever reach the automated adaptation stage.

    High-impact jobs may be diagnosed (read-only) but never trigger
    automated adaptation — only a safe manual path or a reversible local
    draft (gates.md G6). This predicate is one of two independent layers;
    the G3 allowlist blocks high-impact operations separately (M4).
    """
    return not classification.high_impact


# --------------------------------------------------------------------------
# Normalization and rule compilation (deterministic, import-time)
# --------------------------------------------------------------------------

_NON_WORD = re.compile(r"[^a-z0-9]+")


def _normalize(text: str) -> str:
    """Accent-stripped, casefolded, punctuation-collapsed form of ``text``."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_WORD.sub(" ", stripped.casefold()).strip()


#: Up to three words may fall between consecutive phrase tokens.
_TOKEN_GAP = r"\w*\s+(?:\w+\s+){0,3}"


def _compile_phrase(phrase: str) -> re.Pattern[str]:
    tokens = _normalize(phrase).split()
    if not tokens:
        raise ValueError(f"rule phrase normalizes to nothing: {phrase!r}")
    return re.compile(r"\b" + _TOKEN_GAP.join(re.escape(t) for t in tokens) + r"\w*")


_CATEGORY_RULES: tuple[tuple[HighImpactCategory, str, re.Pattern[str]], ...] = tuple(
    (category, phrase, _compile_phrase(phrase))
    for category, phrases in RULE_PHRASES.items()
    for phrase in phrases
)

_AMBIGUOUS_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (phrase, _compile_phrase(phrase)) for phrase in AMBIGUOUS_SCOPE_PHRASES
)

#: Fewer normalized words than this cannot describe a boundable job.
_MIN_CLASSIFIABLE_WORDS = 2

#: A run of four or more single-character words ("d e l e t e ...") is
#: letter-spacing obfuscation: the text is deliberately unmatchable by stem
#: rules, so it cannot be honestly classified → ambiguous → high-impact.
_OBFUSCATED_RUN = re.compile(r"\b(?:\w\s+){3,}\w\b")


def _fail_closed(basis: ClassificationBasis) -> ImpactClassification:
    return ImpactClassification(
        high_impact=True,
        categories=frozenset(),
        basis=basis,
        evidence_state=EvidenceState.NOT_ASSESSED,
    )


# --------------------------------------------------------------------------
# Classification (pure functions; total over arbitrary input)
# --------------------------------------------------------------------------


def classify_text(text: object) -> ImpactClassification:
    """Classify one piece of job text. Total: never raises on any input.

    Non-string input, empty text, or text with no recognizable words is
    unclassifiable → high-impact (gates.md G6 fail closed).
    """
    if not isinstance(text, str):
        return _fail_closed(ClassificationBasis.UNCLASSIFIABLE)

    normalized = _normalize(text)
    words = normalized.split()
    if not words:
        return _fail_closed(ClassificationBasis.UNCLASSIFIABLE)

    matched_categories: set[HighImpactCategory] = set()
    matched_phrases: list[str] = []
    for category, phrase, pattern in _CATEGORY_RULES:
        if pattern.search(normalized):
            matched_categories.add(category)
            matched_phrases.append(phrase)

    if matched_categories:
        return ImpactClassification(
            high_impact=True,
            categories=frozenset(matched_categories),
            basis=ClassificationBasis.RULE_MATCH,
            evidence_state=EvidenceState.INFERRED,
            matched_phrases=tuple(matched_phrases),
        )

    ambiguous_hits = tuple(
        phrase for phrase, pattern in _AMBIGUOUS_RULES if pattern.search(normalized)
    )
    if ambiguous_hits:
        return ImpactClassification(
            high_impact=True,
            categories=frozenset(),
            basis=ClassificationBasis.AMBIGUOUS_SCOPE,
            evidence_state=EvidenceState.NOT_ASSESSED,
            matched_phrases=ambiguous_hits,
        )

    if len(words) < _MIN_CLASSIFIABLE_WORDS or _OBFUSCATED_RUN.search(normalized):
        # Too little text to bound a job honestly, or letter-spacing
        # obfuscation → ambiguous → high-impact.
        return _fail_closed(ClassificationBasis.AMBIGUOUS_SCOPE)

    return ImpactClassification(
        high_impact=False,
        categories=frozenset(),
        basis=ClassificationBasis.NO_MATCH,
        evidence_state=EvidenceState.INFERRED,
    )


def classify_job(
    description: object,
    contract_fields: Mapping[str, object] | None = None,
) -> ImpactClassification:
    """Classify a job from its description plus Success Contract field text.

    ``contract_fields`` maps Success Contract field names (Situation,
    Desired outcome, Success evidence, Boundaries, Importance/cadence) to
    their text. Field names are ignored; every value contributes. A
    non-string field value makes the whole job unclassifiable → high-impact
    (we cannot claim to have evaluated text we could not read).
    """
    if not isinstance(description, str):
        return _fail_closed(ClassificationBasis.UNCLASSIFIABLE)

    parts: list[str] = [description]
    if contract_fields is not None:
        if not isinstance(contract_fields, Mapping):
            return _fail_closed(ClassificationBasis.UNCLASSIFIABLE)
        for value in contract_fields.values():
            if not isinstance(value, str):
                return _fail_closed(ClassificationBasis.UNCLASSIFIABLE)
            parts.append(value)

    return classify_text("\n".join(parts))


# --------------------------------------------------------------------------
# Session wrapper: classifier down → ALL jobs high-impact for the session
# --------------------------------------------------------------------------

_SESSION_FAIL_CLOSED = _fail_closed(ClassificationBasis.CLASSIFIER_UNAVAILABLE)


class SessionClassifier:
    """Per-session G6 classifier that fails closed permanently on error.

    Any exception from the underlying classification function marks the
    whole session failed: that classification and every later one in the
    session returns high-impact with basis ``CLASSIFIER_UNAVAILABLE``
    (gates.md G6: "Classifier unavailable or errors → all jobs treated as
    high-impact for that session"). Recovery requires a new session.
    """

    def __init__(
        self,
        classify_fn: Callable[
            [object, Mapping[str, object] | None], ImpactClassification
        ] = classify_job,
    ) -> None:
        self._classify_fn = classify_fn
        self._failed = False

    @property
    def failed(self) -> bool:
        """Whether this session has permanently failed closed."""
        return self._failed

    def classify(
        self,
        description: object,
        contract_fields: Mapping[str, object] | None = None,
    ) -> ImpactClassification:
        if self._failed:
            return _SESSION_FAIL_CLOSED
        try:
            result = self._classify_fn(description, contract_fields)
        except Exception:
            self._failed = True
            return _SESSION_FAIL_CLOSED
        if not isinstance(result, ImpactClassification):
            # A wrong-typed result is a classifier defect: same failure mode.
            self._failed = True
            return _SESSION_FAIL_CLOSED
        return result
