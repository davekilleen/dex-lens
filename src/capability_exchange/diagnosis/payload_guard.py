"""Shared wire guards for every diagnosis adapter.

The MCP server and the CLI accept the same specialist payloads, so they must
refuse the same ones, in the same way, before the engine sees them. A payload
the engine never sees costs no specialist retry; one that reaches the engine
and fails validation burns an attempt. Detection therefore lives here, ahead
of both adapters, and each adapter translates the refusal into its own error
shape without echoing the offending value.
"""

from __future__ import annotations

import re

from capability_exchange.diagnosis.specialists import (
    SpecialistProposal as EngineProposal,
)

__all__ = [
    "ABSOLUTE_PATH",
    "SESSION_CANARY",
    "HostilePayloadError",
    "parse_specialist_proposal",
    "refuse_hostile_payload",
    "string_values",
]

SESSION_CANARY = "INVENTED_SESSION_CANARY_NEVER_RETAIN"

# The guard refuses absolute-path SHAPE, not substrings. A guarded prefix
# counts only where an absolute path can actually start: at the beginning of
# the string, or immediately after a non-path boundary character — whitespace,
# a quote, an opening bracket, ``=`` or ``:`` — the ways an absolute path is
# embedded in surrounding text. It never counts mid-relative-path after a
# path segment, so a vault folder named ``private``, ``home`` or ``Users``
# below the root (``notes/private/journal.md``) stays diagnosable: every
# relative reference provenance validation accepts must pass this guard.
#
# The vocabulary deliberately has no bare ``/var/`` or ``/tmp/``: macOS
# temporary directories live under ``/var/folders/...`` and Linux test
# fixtures under ``/tmp/...``. Fedora Silverblue's real home is covered
# explicitly as ``/var/home/``.
_ABSOLUTE_PREFIXES = (
    "/Users/",
    "/home/",
    "/private/",
    "/root/",
    "/srv/",
    "/opt/",
    "/Volumes/",
    "/var/home/",
)
_BOUNDARY = r"(?:^|(?<=[\s\"'`([{<=:]))"
ABSOLUTE_PATH = re.compile(
    _BOUNDARY
    + "(?:"
    + "|".join(re.escape(prefix) for prefix in _ABSOLUTE_PREFIXES)
    + r")|[A-Za-z]:\\"
)

REMOVE_SECRET = "remove_secret"
REMOVE_ABSOLUTE_PATH = "remove_absolute_path"


class HostilePayloadError(ValueError):
    """A payload carried secret material or an absolute path.

    The offending text is deliberately not attached. Adapters report the
    ``required_step`` and their own constant wording so a hostile value can
    never be echoed back through an error message.
    """

    def __init__(self, required_step: str) -> None:
        super().__init__(required_step)
        self.required_step = required_step


def string_values(payload: object) -> list[str]:
    """Every string reachable in a decoded payload, keys included."""

    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        found: list[str] = []
        for key, value in payload.items():
            if isinstance(key, str):
                found.append(key)
            found.extend(string_values(value))
        return found
    if isinstance(payload, list | tuple):
        found = []
        for item in payload:
            found.extend(string_values(item))
        return found
    return []


def refuse_hostile_payload(payload: object) -> None:
    """Raise when a payload carries a session canary or an absolute path."""

    for text in string_values(payload):
        if SESSION_CANARY in text:
            raise HostilePayloadError(REMOVE_SECRET)
        if ABSOLUTE_PATH.search(text):
            raise HostilePayloadError(REMOVE_ABSOLUTE_PATH)


_PROPOSAL_FIELDS = frozenset(EngineProposal.model_fields)

_SCHEMA_REFUSAL = "specialist proposal is not a closed typed payload"


def _invalid_field_names(exc: Exception) -> tuple[str, ...]:
    """Known proposal field names a validation failure points at.

    Only names already declared on the closed proposal model are ever
    returned, so a refusal can name what failed without repeating any
    submitted key or value.
    """

    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return ()
    try:
        details = errors()
    except Exception:
        return ()
    names: set[str] = set()
    for item in details:
        location = item.get("loc") or ()
        head = location[0] if location else None
        if isinstance(head, str) and head in _PROPOSAL_FIELDS:
            names.add(head)
    return tuple(sorted(names))


def _schema_refusal_message(exc: Exception) -> str:
    """Fixed rule text plus the failing field names — never pydantic's messages.

    Pydantic error strings can embed the submitted input values, so they are
    deliberately not consulted; only field names from the closed model are.
    """

    names = _invalid_field_names(exc)
    if names:
        return f"{_SCHEMA_REFUSAL} (invalid fields: {', '.join(names)})"
    return _SCHEMA_REFUSAL


def parse_specialist_proposal(payload: object) -> EngineProposal:
    """Refuse unknown wire fields, then validate the typed proposal schema."""

    if not isinstance(payload, dict):
        raise ValueError(_SCHEMA_REFUSAL)
    if set(payload) - _PROPOSAL_FIELDS:
        raise ValueError("unknown fields are forbidden on specialist proposals")
    try:
        return EngineProposal.model_validate(payload)
    except Exception as exc:
        raise ValueError(_schema_refusal_message(exc)) from exc
