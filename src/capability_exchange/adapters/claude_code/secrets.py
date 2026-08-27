"""Secret redaction at collection time (gates.md G1 item d).

Secret-shaped content is redacted **at collection**: raw secret bytes never
enter the snapshot, the envelope, or any other structure — only a redacted
mark survives. This mirrors dex-core's customization-assessor discipline
(clean-room reimplementation; no dex-core import).

Recognized shapes: AWS access key ids, ``sk-`` API keys, GitHub tokens,
Slack tokens, Bearer tokens, PEM private-key blocks (including unterminated
ones — fail closed to end-of-content), and credential-style assignments
(``API_KEY=...``, ``password: ...``). Environment references (``$VAR``),
placeholders (``changeme``, ``your-key-here``), and bare ALL-CAPS constant
names are not secrets and are left alone.

The scan operates on bytes with fixed patterns. It never decodes, parses,
or interprets the content as anything else — inspected file content is
untrusted data (G1 item e) and this module treats it purely as bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from capability_exchange.boundary.secret_markers import CREDENTIAL_NAME_PATTERN_BYTES

__all__ = [
    "REDACTION_MARK",
    "RedactionOutcome",
    "contains_secret_shape",
    "redact_secret_content",
]

#: What survives in place of secret bytes. Fixed and content-free.
REDACTION_MARK = b"[REDACTED-SECRET]"

#: High-confidence token shapes. Each match is redacted whole. Distinctive
#: prefixes (AKIA, gh*_, xox*) match without word boundaries — a key glued
#: to surrounding noise must still never survive (fail closed; hypothesis
#: property test), and over-redaction is the acceptable direction. ``sk-``
#: keeps a lookbehind because it occurs inside ordinary hyphenated prose
#: (task-, risk-, desk-); the assignment pattern below still catches
#: credential-style uses of such values.
_TOKEN_PATTERNS: tuple[re.Pattern[bytes], ...] = (
    re.compile(rb"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),  # sk- style API key
    re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),  # GitHub token
    re.compile(rb"xox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack token
    re.compile(rb"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/=-]{20,}"),  # Bearer token
)

#: PEM private-key block. An unterminated block redacts to end-of-content —
#: fail closed rather than leave a partial key in the snapshot.
_PEM_BLOCK = re.compile(
    rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    rb".*?"
    rb"(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)

#: Credential-style assignment: the *value* group is what gets redacted.
_ASSIGNMENT = re.compile(
    rb"(?im)^[ \t]*(?:export[ \t]+)?"
    rb"[A-Za-z0-9_-]*" + CREDENTIAL_NAME_PATTERN_BYTES + rb"[A-Za-z0-9_-]*[ \t]*[:=][ \t]*"
    rb"(?:\"([^\"\n]+)\"|'([^'\n]+)'|([^\s#]+))"
)

#: Assignment values that are references or placeholders, not secrets.
_ENV_REFERENCE = re.compile(rb"^(?:\$[A-Za-z_][A-Za-z0-9_]*|\$\{[A-Za-z_][A-Za-z0-9_]*\})$")
_PLACEHOLDER = re.compile(
    rb"(?i)^(?:none|null|true|false|change[-_]?me|example|placeholder|"
    rb"replace[-_]?me|todo|xxx+|your[-_].*)$"
)
_CONSTANT_NAME = re.compile(rb"^[A-Z][A-Z0-9_]*$")
_MIN_ASSIGNED_SECRET_LENGTH = 8


def _assignment_value_span(match: re.Match[bytes]) -> tuple[int, int] | None:
    """The (start, end) of a credential-shaped assignment's secret value."""
    for group_index in (1, 2, 3):
        if match.group(group_index) is not None:
            value = match.group(group_index).strip()
            if (
                len(value) >= _MIN_ASSIGNED_SECRET_LENGTH
                and _ENV_REFERENCE.fullmatch(value) is None
                and _PLACEHOLDER.fullmatch(value) is None
                and _CONSTANT_NAME.fullmatch(value) is None
            ):
                return match.span(group_index)
            return None
    return None


def _secret_spans(raw: bytes) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in (*_TOKEN_PATTERNS, _PEM_BLOCK):
        spans.extend(match.span() for match in pattern.finditer(raw))
    for match in _ASSIGNMENT.finditer(raw):
        value_span = _assignment_value_span(match)
        if value_span is not None:
            spans.append(value_span)
    if not spans:
        return []
    spans.sort()
    merged: list[tuple[int, int]] = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


@dataclass(frozen=True, slots=True)
class RedactionOutcome:
    """Redacted content plus how many secret spans were removed.

    ``content`` never contains the original secret bytes; the raw input is
    the caller's to discard, and nothing here retains a reference to it.
    """

    content: bytes
    redaction_count: int


def redact_secret_content(raw: bytes) -> RedactionOutcome:
    """Redact every secret-shaped span in ``raw``. Total; never raises.

    Called at collection time, before content enters any structure. The
    return value is safe to hold in the inspection snapshot; the raw bytes
    must not be stored anywhere.
    """
    spans = _secret_spans(raw)
    if not spans:
        return RedactionOutcome(content=raw, redaction_count=0)
    pieces: list[bytes] = []
    cursor = 0
    for start, end in spans:
        pieces.append(raw[cursor:start])
        pieces.append(REDACTION_MARK)
        cursor = end
    pieces.append(raw[cursor:])
    return RedactionOutcome(content=b"".join(pieces), redaction_count=len(spans))


def contains_secret_shape(raw: bytes) -> bool:
    """Whether ``raw`` contains at least one secret-shaped span."""
    return bool(_secret_spans(raw))
