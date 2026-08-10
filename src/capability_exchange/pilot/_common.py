"""Small shared helpers for the M6 evidence tooling."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for an immutable record."""

    return datetime.now(UTC)


def canonical_json(value: Any) -> str:
    """Encode JSON deterministically for content-addressed records.

    Pydantic models should be passed through ``model_dump(mode='json')`` before
    calling this helper.  The fallback encoder exists for dates in small test
    fixtures and never includes object reprs (which are not stable hashes).
    """

    def default(item: Any) -> str:
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, set | frozenset):
            return json.dumps(sorted(item), separators=(",", ":"))
        return str(item)

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=default,
    )


def content_hash(value: Any) -> str:
    """SHA-256 hash of canonical JSON, represented as lowercase hex."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def hash_model(model: Any, *, exclude: set[str] | frozenset[str] = frozenset()) -> str:
    """Hash a pydantic model after excluding mutable/derived fields."""

    payload = model.model_dump(mode="json", exclude=set(exclude))
    return content_hash(payload)


def clean_text(value: str, *, label: str, max_length: int = 512) -> str:
    """Validate bounded, single-line metadata (never a raw evidence payload)."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty")
    if len(value) > max_length:
        raise ValueError(f"{label} exceeds {max_length} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{label} contains control characters")
    return value.strip()


def tuple_text(values: tuple[str, ...], *, label: str, max_items: int = 64) -> tuple[str, ...]:
    """Apply :func:`clean_text` to a bounded metadata list."""

    if len(values) > max_items:
        raise ValueError(f"{label} has too many entries")
    return tuple(clean_text(item, label=label) for item in values)


def as_mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping for tolerant test fixtures, or fail closed."""

    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError("expected a mapping or pydantic model")
