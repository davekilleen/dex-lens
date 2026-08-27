"""Shared credential-name vocabulary for local trust-boundary screening."""

from __future__ import annotations

import re

__all__ = ["CREDENTIAL_NAME_PATTERN_BYTES", "has_credential_name_marker"]

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


def has_credential_name_marker(value: str) -> bool:
    """Whether a path segment contains a canonical credential-name marker."""

    return _CREDENTIAL_SEGMENT.search(value) is not None
