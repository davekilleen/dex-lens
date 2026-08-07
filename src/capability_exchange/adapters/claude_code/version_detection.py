"""Claude Code installation-shape and version detection (read-only, honest).

Detection consults **only the immutable snapshot** — file presence and
names, never file content, and never the host's own binary (G1 forbids
arbitrary shell, so ``VersionDetectionMethod`` has no exec member by
construction). What cannot be proven from the approved scope is reported
as Unknown, honestly, rather than guessed.

At M1 the version itself is always Unknown: no file marker inside a local
folder-based Claude Code scope proves the installed version without
executing the host binary or interpreting untrusted file content as fact.
The shape (which configuration artifacts exist) is provable from presence
alone and is reported with method ``file-marker``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from capability_exchange.adapter import VersionDetectionMethod
from capability_exchange.adapters.claude_code.snapshot import InspectionSnapshot

__all__ = [
    "InstallationMarker",
    "InstallationShape",
    "detect_installation",
]

#: File names that mark a Claude Code configuration surface.
_SETTINGS_BASENAME = "settings.json"
_INSTRUCTIONS_BASENAME = "CLAUDE.md"
_SKILL_BASENAME = "SKILL.md"


class InstallationMarker(StrEnum):
    """Closed vocabulary for the provable installation shape."""

    CONFIGURED = "configured"  # settings artifacts present in scope
    INSTRUCTIONS_ONLY = "instructions-only"  # CLAUDE.md but no settings
    UNKNOWN = "unknown"  # nothing provable from the approved scope


@dataclass(frozen=True, slots=True)
class InstallationShape:
    """What the snapshot proves about the Claude Code installation."""

    marker: InstallationMarker
    method: VersionDetectionMethod
    #: Always ``None`` at M1: an unprovable version is Unknown, not guessed.
    version: str | None
    detail: str

    @property
    def version_known(self) -> bool:
        return self.version is not None


def _has_entry_named(snapshot: InspectionSnapshot, basename: str) -> bool:
    return bool(snapshot.entries_named(basename))


def _has_settings(snapshot: InspectionSnapshot) -> bool:
    """A ``settings.json`` at scope root or inside a ``.claude`` directory."""
    for entry in snapshot.entries_named(_SETTINGS_BASENAME):
        parents = entry.relative_path.split("/")[:-1]
        if not parents or ".claude" in parents:
            return True
    return False


def detect_installation(snapshot: InspectionSnapshot) -> InstallationShape:
    """Detect the installation shape from snapshot presence data only."""
    has_settings = _has_settings(snapshot)
    has_instructions = _has_entry_named(snapshot, _INSTRUCTIONS_BASENAME)
    has_skills = _has_entry_named(snapshot, _SKILL_BASENAME)

    if has_settings or has_skills:
        return InstallationShape(
            marker=InstallationMarker.CONFIGURED,
            method=VersionDetectionMethod.FILE_MARKER,
            version=None,
            detail=(
                "Claude Code configuration artifacts present in the approved "
                "scope; version not provable without executing the host "
                "binary, so it is Unknown"
            ),
        )
    if has_instructions:
        return InstallationShape(
            marker=InstallationMarker.INSTRUCTIONS_ONLY,
            method=VersionDetectionMethod.FILE_MARKER,
            version=None,
            detail=(
                "instructions file present but no settings or skills in the "
                "approved scope; version Unknown"
            ),
        )
    return InstallationShape(
        marker=InstallationMarker.UNKNOWN,
        method=VersionDetectionMethod.UNKNOWN,
        version=None,
        detail=(
            "no Claude Code markers provable from the approved scope; "
            "shape and version are Unknown, honestly"
        ),
    )
