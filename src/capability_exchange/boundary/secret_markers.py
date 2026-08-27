"""Shared credential-name vocabulary for local trust-boundary screening."""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "CREDENTIAL_NAME_PATTERN_BYTES",
    "HIGH_CONFIDENCE_TOKEN_PATTERNS_BYTES",
    "SECRET_SHAPE_EXAMPLES",
    "SecretShapeExample",
    "has_credential_name_marker",
    "has_secret_shape_marker",
]

# Keep filename screening and Claude content redaction on one vocabulary.
# Boundaries are applied by ``has_credential_name_marker``; the content
# redactor deliberately embeds the same vocabulary inside variable names.
_CREDENTIAL_NAME_PATTERN = (
    r"(?:api[_-]?key|access[_-]?token|auth(?:orization)?|credential(?:s)?|"
    r"private[_-]?key|secret(?:s)?|passwd|password(?:s)?|token(?:s)?)"
)
CREDENTIAL_NAME_PATTERN_BYTES = _CREDENTIAL_NAME_PATTERN.encode("ascii")
_CREDENTIAL_SEGMENT = re.compile(
    rf"(?:^|[._-]){_CREDENTIAL_NAME_PATTERN}(?:$|[._-])",
    re.IGNORECASE,
)

_HIGH_CONFIDENCE_TOKEN_PATTERN_TEXT = (
    r"AKIA[0-9A-Z]{16}",
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}",
    r"gh[pousr]_[A-Za-z0-9_]{20,}",
    r"xox[abprs]-[A-Za-z0-9-]{10,}",
    r"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/=-]{20,}",
)
_HIGH_CONFIDENCE_TOKEN_PATTERNS_TEXT = tuple(
    re.compile(pattern) for pattern in _HIGH_CONFIDENCE_TOKEN_PATTERN_TEXT
)
HIGH_CONFIDENCE_TOKEN_PATTERNS_BYTES = tuple(
    re.compile(pattern.encode("ascii")) for pattern in _HIGH_CONFIDENCE_TOKEN_PATTERN_TEXT
)


@dataclass(frozen=True, slots=True)
class SecretShapeExample:
    """One canonical example used to hold both secret consumers aligned."""

    name: str
    path_fragment: str
    content_example: bytes
    secret_fragment: bytes


_ASSIGNED_SECRET = b"knownsecretvalue123"
SECRET_SHAPE_EXAMPLES = (
    *(
        SecretShapeExample(
            name=f"credential-{name}",
            path_fragment=marker,
            content_example=marker.encode("ascii") + b"=" + _ASSIGNED_SECRET,
            secret_fragment=_ASSIGNED_SECRET,
        )
        for name, marker in (
            ("api-key", "api_key"),
            ("access-token", "access-token"),
            ("auth", "auth"),
            ("authorization", "authorization"),
            ("credential", "credential"),
            ("private-key", "private_key"),
            ("secret", "secret"),
            ("passwd", "passwd"),
            ("password", "password"),
            ("token", "token"),
        )
    ),
    SecretShapeExample(
        name="aws-access-key",
        path_fragment="AKIAIOSFODNN7EXAMPLE",
        content_example=b"AKIAIOSFODNN7EXAMPLE",
        secret_fragment=b"AKIAIOSFODNN7EXAMPLE",
    ),
    SecretShapeExample(
        name="sk-api-key",
        path_fragment="sk-abcdefabcdefabcdefabcd",
        content_example=b"sk-abcdefabcdefabcdefabcd",
        secret_fragment=b"sk-abcdefabcdefabcdefabcd",
    ),
    SecretShapeExample(
        name="github-token",
        path_fragment="ghp_abcdefghijklmnopqrstuvwxyz012345",
        content_example=b"ghp_abcdefghijklmnopqrstuvwxyz012345",
        secret_fragment=b"ghp_abcdefghijklmnopqrstuvwxyz012345",
    ),
    SecretShapeExample(
        name="slack-token",
        path_fragment="xoxb-1234567890-abcdefghij",
        content_example=b"xoxb-1234567890-abcdefghij",
        secret_fragment=b"xoxb-1234567890-abcdefghij",
    ),
    SecretShapeExample(
        name="bearer-token",
        path_fragment="Bearer abcdefghijklmnopqrstuvwx",
        content_example=b"Authorization: Bearer abcdefghijklmnopqrstuvwx",
        secret_fragment=b"abcdefghijklmnopqrstuvwx",
    ),
    SecretShapeExample(
        name="pem-private-key",
        path_fragment="private_key.pem",
        content_example=(
            b"-----BEGIN PRIVATE KEY-----\nprivatekeymaterial\n-----END PRIVATE KEY-----"
        ),
        secret_fragment=b"privatekeymaterial",
    ),
)


def has_credential_name_marker(value: str) -> bool:
    """Whether a path segment contains a canonical credential-name marker."""

    return _CREDENTIAL_SEGMENT.search(value) is not None


def has_secret_shape_marker(value: str) -> bool:
    """Whether text contains a credential name or high-confidence token shape."""

    segments = re.split(r"[/\\]", value)
    return any(has_credential_name_marker(segment) for segment in segments) or any(
        pattern.search(value) is not None for pattern in _HIGH_CONFIDENCE_TOKEN_PATTERNS_TEXT
    )
