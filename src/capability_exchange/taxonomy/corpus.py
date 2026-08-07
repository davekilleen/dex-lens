"""Loader for the labeled G6 corpus (data lives in ``corpus/labeled_jobs.json``).

The corpus is data, not code: labeled job descriptions across all nine
high-impact categories (plainly worded, euphemistic, and multilingual
phrasings) plus genuinely-benign jobs. Every string is synthetic — no real
person, credential, or path appears anywhere. The corpus test asserts zero
false negatives across it and records (never gates on) the false-positive
rate over the benign entries.

The loader fails closed: a corpus that cannot be parsed or validated raises
:class:`CorpusError` rather than yielding a partial corpus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from capability_exchange.taxonomy.categories import HighImpactCategory

__all__ = ["CORPUS_PATH", "CorpusEntry", "CorpusError", "load_corpus"]

CORPUS_PATH = Path(__file__).parent / "corpus" / "labeled_jobs.json"

_PHRASINGS = frozenset({"plain", "euphemistic", "multilingual"})
_LANGUAGES = frozenset({"en", "es", "fr", "de", "it", "nl", "pt", "ja"})


class CorpusError(Exception):
    """The labeled corpus failed to parse or validate. Fail closed."""


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    """One labeled corpus example."""

    entry_id: str
    text: str
    categories: frozenset[HighImpactCategory]
    phrasing: str  # plain | euphemistic | multilingual
    language: str  # en | es | fr | de

    @property
    def high_impact(self) -> bool:
        return bool(self.categories)


def _parse_entry(raw: object) -> CorpusEntry:
    if not isinstance(raw, dict):
        raise CorpusError(f"corpus entry is not an object: {type(raw).__name__}")
    try:
        entry_id = raw["id"]
        text = raw["text"]
        categories = raw["categories"]
        phrasing = raw["phrasing"]
        language = raw["language"]
    except KeyError as missing:
        raise CorpusError(f"corpus entry missing key {missing}") from None
    if not isinstance(entry_id, str) or not entry_id:
        raise CorpusError("corpus entry id must be a non-empty string")
    if not isinstance(text, str) or not text.strip():
        raise CorpusError(f"corpus entry {entry_id}: text must be non-empty")
    if phrasing not in _PHRASINGS:
        raise CorpusError(f"corpus entry {entry_id}: unknown phrasing {phrasing!r}")
    if language not in _LANGUAGES:
        raise CorpusError(f"corpus entry {entry_id}: unknown language {language!r}")
    if not isinstance(categories, list):
        raise CorpusError(f"corpus entry {entry_id}: categories must be a list")
    parsed: set[HighImpactCategory] = set()
    for value in categories:
        try:
            parsed.add(HighImpactCategory(value))
        except ValueError:
            raise CorpusError(
                f"corpus entry {entry_id}: {value!r} is outside the closed "
                f"nine-category vocabulary"
            ) from None
    return CorpusEntry(
        entry_id=entry_id,
        text=text,
        categories=frozenset(parsed),
        phrasing=phrasing,
        language=language,
    )


@lru_cache(maxsize=1)
def load_corpus(path: Path = CORPUS_PATH) -> tuple[CorpusEntry, ...]:
    """Load and validate the labeled corpus. Raises CorpusError on any defect."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"cannot load corpus at {path}: {exc}") from exc
    if not isinstance(document, dict) or "entries" not in document:
        raise CorpusError("corpus document must be an object with an 'entries' list")
    entries_raw = document["entries"]
    if not isinstance(entries_raw, list) or not entries_raw:
        raise CorpusError("corpus 'entries' must be a non-empty list")
    entries = tuple(_parse_entry(raw) for raw in entries_raw)
    seen: set[str] = set()
    for entry in entries:
        if entry.entry_id in seen:
            raise CorpusError(f"duplicate corpus entry id {entry.entry_id!r}")
        seen.add(entry.entry_id)
    return entries
