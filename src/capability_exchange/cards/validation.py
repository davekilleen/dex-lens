"""Structural and hostile-content validation for Capability Cards (G4/R5)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from capability_exchange.cards.model import CapabilityCard

__all__ = [
    "CardScanner",
    "CardValidationError",
    "ReasonCode",
    "ValidationIssue",
    "scan_card",
    "scan_text",
    "require_valid_card",
    "validate_card",
]


class ReasonCode(StrEnum):
    """Stable, machine-readable hostile/structural validation reasons."""

    MISSING_DECLARATION = "missing-declaration"
    SCHEMA = "schema-invalid"
    FORBIDDEN_FIELD = "forbidden-field"
    ATTACHMENT_FORBIDDEN = "attachment-forbidden"
    SELF_TRUST_FORBIDDEN = "self-trust-forbidden"
    SECRET = "secret"
    RAW_PERSONAL_EXAMPLE = "raw-personal-example"
    UNIQUE_PATH = "unique-filesystem-path"
    THIRD_PARTY_CONFIDENTIAL = "third-party-confidential"
    PII = "pii"
    PROMPT_INJECTION = "prompt-injection"
    UNSAFE_INSTRUCTION = "unsafe-instruction"


class ValidationIssue:
    """One validation finding, safe to show without echoing the payload."""

    __slots__ = ("path", "reason", "message")

    def __init__(self, path: str, reason: ReasonCode, message: str) -> None:
        self.path = path
        self.reason = reason
        self.message = message

    def __repr__(self) -> str:
        return f"ValidationIssue(path={self.path!r}, reason={self.reason.value!r})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ValidationIssue)
            and self.path == other.path
            and self.reason == other.reason
            and self.message == other.message
        )

    def __hash__(self) -> int:
        return hash((self.path, self.reason, self.message))


class CardValidationError(ValueError):
    """Card validation failed; messages contain reason codes, never values."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        joined = "; ".join(f"{issue.path}: {issue.reason.value}" for issue in issues)
        super().__init__(f"Capability Card validation failed: {joined}")

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(issue.reason.value for issue in self.issues))


# The patterns intentionally identify classes of content, not exact payloads;
# the Card schema remains an exchange recipe and never stores the raw source.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:bearer|token|password|passwd|secret)\s*[:=]\s*\S+", re.I),
    # Credential-shaped high-entropy tokens are rejected even when their
    # vendor prefix is unknown.  The token must be compact and varied so
    # ordinary prose does not become a secret finding by accident.
    re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b"),
)
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:\+?\d[\d .()-]{7,}\d)\b"),
    re.compile(
        r"\b\d{1,5}[A-Za-z]?\s+[A-Z][A-Za-z]+\s+"
        r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Boulevard|Blvd)\b",
        re.I,
    ),
    re.compile(r"\b(?:full\s+name|phone|mobile|home\s+address)\s*[:=]", re.I),
)
_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/(?:Users|home|var/folders)/[^\s/]+(?:/[^\s]*)?", re.I),
    re.compile(r"(?:^|[\s(])~/(?:[^\s)]+)", re.I),
    re.compile(r"/(?:private|tmp|etc|srv|opt|Volumes|mnt|root)/[^\s/]+(?:/[^\s]*)?", re.I),
    re.compile(r"\b[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s]+", re.I),
)
_CONFIDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:third[- ]party|client|customer)\s+(?:confidential|private|internal)\b", re.I),
    re.compile(r"\b(?:confidential|internal only|under nda)\b", re.I),
    re.compile(
        r"\b(?:confidential|proprietary)\s+(?:client|customer|third-party|internal)\b",
        re.I,
    ),
    re.compile(r"\b(?:client|customer|third-party)\s+(?:data|material|boilerplate)\b", re.I),
    re.compile(
        r"\b(?:client|customer|third[- ]party|vendor|partner|employer)\b"
        r"[^.\n]{0,80}\b(?:confidential|proprietary|internal|nda)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:confidential|proprietary|internal|nda)\b"
        r"[^.\n]{0,80}\b(?:client|customer|third[- ]party|vendor|partner|employer)\b",
        re.I,
    ),
)
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bignore\s+(?:(?:all|any|the)\s+)?(?:previous|prior|above) instructions\b", re.I),
    re.compile(r"\bwhen (?:summarizing|reviewing|importing) .*\b(?:approve|trust|execute)\b", re.I),
    re.compile(r"\b(?:system prompt|developer message|jailbreak)\b", re.I),
)
_UNSAFE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:disable|bypass|weaken|turn off)\s+(?:security|authentication|checks?)\b", re.I
    ),
    re.compile(r"\bchmod\s+777\b", re.I),
    re.compile(r"\brm\s+-rf\b", re.I),
    re.compile(r"\b(?:curl|wget)\b[^\n|]{0,200}\|\s*(?:sh|bash)\b", re.I),
    re.compile(
        r"\b(?:send|publish|delete|overwrite)\b[^.\n]{0,100}\b(?:automatically|without approval)\b",
        re.I,
    ),
)


def _flatten_strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, Mapping):
        result: list[tuple[str, str]] = []
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            result.extend(_flatten_strings(item, child))
        return result
    if isinstance(value, (tuple, list)):
        result = []
        for index, item in enumerate(value):
            result.extend(_flatten_strings(item, f"{path}[{index}]"))
        return result
    return []


def _structural_issues(payload: object) -> tuple[CapabilityCard | None, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    if isinstance(payload, CapabilityCard):
        return payload, issues
    if not isinstance(payload, Mapping):
        return None, [
            ValidationIssue("card", ReasonCode.SCHEMA, "Card must be a mapping or CapabilityCard")
        ]
    known = set(CapabilityCard.model_fields)
    for name in payload:
        if name not in known:
            reason = (
                ReasonCode.ATTACHMENT_FORBIDDEN
                if "attachment" in str(name).lower()
                else ReasonCode.SELF_TRUST_FORBIDDEN
                if name in {"trust", "reviewed", "trusted"}
                else ReasonCode.FORBIDDEN_FIELD
            )
            issues.append(
                ValidationIssue(str(name), reason, "field is not representable in a Card")
            )
    missing = sorted(known - set(payload))
    for name in missing:
        issues.append(
            ValidationIssue(name, ReasonCode.MISSING_DECLARATION, "required declaration is missing")
        )
    if issues:
        # Keep mapping errors visible, but a partially supplied object cannot
        # be safely scanned as a Card.  Still scan every supplied string so a
        # hostile value receives its specific reason rather than hiding behind
        # an unrelated missing/forbidden-field finding.
        issues.extend(_scan_strings(_flatten_strings(payload)))
        try:
            card = CapabilityCard.model_validate(payload)
        except ValidationError:
            card = None
        return card, issues
    try:
        return CapabilityCard.model_validate(payload), issues
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(item) for item in error.get("loc", ())) or "card"
            issues.append(
                ValidationIssue(location, ReasonCode.SCHEMA, "Card field failed schema validation")
            )
        return None, issues


def _scan_strings(values: list[tuple[str, str]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[tuple[str, ReasonCode]] = set()
    for path, text in values:
        checks = (
            (_SECRET_PATTERNS, ReasonCode.SECRET, "secret-shaped content is not allowed"),
            (_PII_PATTERNS, ReasonCode.PII, "personally identifying content is not allowed"),
            (_PATH_PATTERNS, ReasonCode.UNIQUE_PATH, "unique filesystem paths are not allowed"),
            (
                _CONFIDENTIAL_PATTERNS,
                ReasonCode.THIRD_PARTY_CONFIDENTIAL,
                "third-party confidential content is not allowed",
            ),
            (
                _INJECTION_PATTERNS,
                ReasonCode.PROMPT_INJECTION,
                "prompt-injection content is not allowed",
            ),
            (
                _UNSAFE_PATTERNS,
                ReasonCode.UNSAFE_INSTRUCTION,
                "unsafe instructions are not allowed",
            ),
        )
        for patterns, reason, message in checks:
            if any(pattern.search(text) for pattern in patterns) and (path, reason) not in seen:
                seen.add((path, reason))
                issues.append(ValidationIssue(path, reason, message))
        if re.search(
            r"\b(?:raw|personal)\s+(?:email|prompt|notes?|example|conversation|history)\b",
            text,
            re.I,
        ):
            reason = ReasonCode.RAW_PERSONAL_EXAMPLE
            if (path, reason) not in seen:
                seen.add((path, reason))
                issues.append(
                    ValidationIssue(path, reason, "raw personal examples are not allowed")
                )
    return issues


def _scan_content(card: CapabilityCard) -> list[ValidationIssue]:
    return _scan_strings(_flatten_strings(card.model_dump(mode="python")))


def scan_text(value: Any, *, path: str = "payload") -> tuple[ValidationIssue, ...]:
    """Scan partial disclosure text before it can be sent independently."""

    return tuple(_scan_strings(_flatten_strings(value, path)))


def validate_card(
    payload: CapabilityCard | Mapping[str, Any], *, raise_on_error: bool = False
) -> tuple[ValidationIssue, ...]:
    """Return structural and hostile-content findings for a Card.

    ``raise_on_error`` provides the submission boundary's fail-closed form;
    moderation uses the issue tuple so it can quarantine rather than execute
    a failed submission.
    """

    card, structural = _structural_issues(payload)
    issues = list(structural)
    if card is not None and not structural:
        issues.extend(_scan_content(card))
    result = tuple(issues)
    if result and raise_on_error:
        raise CardValidationError(result)
    return result


scan_card = validate_card


def require_valid_card(payload: CapabilityCard | Mapping[str, Any]) -> CapabilityCard:
    """Return a Card only when schema and hostile-content checks both pass.

    This is the mandatory boundary used by disclosure, consent, moderation,
    and lifecycle code.  It deliberately raises the same reason-coded error
    as ``validate_card(..., raise_on_error=True)`` so no caller can accidentally
    turn a warning into an outbound or persisted Card.
    """

    issues = validate_card(payload)
    if issues:
        raise CardValidationError(issues)
    if isinstance(payload, CapabilityCard):
        return payload
    # ``validate_card`` has already parsed a mapping; parsing once more keeps
    # this helper's return type explicit without retaining untrusted input.
    return CapabilityCard.model_validate(payload)


class CardScanner:
    """Explicit scanner port used before any human moderation review."""

    def scan(self, card: CapabilityCard) -> tuple[ValidationIssue, ...]:
        return validate_card(card)
