"""Canonicalized real-path allowlist (gates.md G1 items b and d).

Every path is resolved to its real path (``os.path.realpath``, strict)
**before** any read; reads outside the approved canonical set are refused.
Symlinks whose target escapes the allowlist and hard links whose other
names cannot be proven in-scope are rejected with an honest exclusion
record. Mount-point and ignored-file policy are explicit:

- **Mount points:** collection never crosses a device boundary. A directory
  or file on a different device than its approved root is refused
  (``mount-point-crossing``) — bind mounts and foreign filesystems inside
  an approved root are not silently swept in.
- **Ignored directories:** VCS internals and dependency trees
  (:data:`IGNORED_DIRECTORY_NAMES`) are pruned for bounded collection and
  each pruning is recorded — never silent.
- **Ignored files:** files a VCS would ignore (e.g. ``.gitignore``\\ d) are
  **not** skipped. They are inspected under the same allowlist and secret
  redaction, because skipping them would miss planted secrets (G1 hostile
  fixture 3).

Fail closed: a path whose resolution is ambiguous (racy symlink, unexpected
resolution error) is marked ``ambiguous`` — the snapshot layer aborts the
whole inspection on it rather than best-effort reading (G1 fail-closed
rule). Ambiguity is reserved for genuinely uncertain outcomes: a dangling
symlink (``absent``) and a symlink loop (``blocked``) are unambiguous
answers and become honest per-path exclusions, because aborting on them
would let any inspected system disable the deep adapter with one broken
link — a downgrade the person did not choose.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "IGNORED_DIRECTORY_NAMES",
    "AllowlistError",
    "CanonicalAllowlist",
    "PathDecision",
    "PathVerdict",
    "SurveyOutcome",
]


class AllowlistError(Exception):
    """The allowlist itself could not be established. Fail closed: no reads."""


class PathVerdict(StrEnum):
    """Closed verdict vocabulary for one evaluated path."""

    ADMITTED = "admitted"
    BLOCKED = "blocked"  # maps to R2 state `blocked` in exclusion records
    ABSENT = "absent"  # maps to R2 state `absent` in exclusion records


#: Directories pruned during survey (bounded collection; each recorded).
IGNORED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".cache",
        ".git",
        ".tox",
        ".venv",
        "__pycache__",
        "dist",
        "node_modules",
        "vendor",
        "venv",
    }
)


@dataclass(frozen=True, slots=True)
class PathDecision:
    """The allowlist's verdict on one path, with an honest reason."""

    verdict: PathVerdict
    given_path: str
    canonical_path: str | None
    relative_path: str | None
    reason: str
    is_directory: bool = False
    ambiguous: bool = False

    @property
    def is_admitted(self) -> bool:
        return self.verdict is PathVerdict.ADMITTED


@dataclass(frozen=True, slots=True)
class SurveyOutcome:
    """Every decision a survey of the approved roots produced."""

    admitted_files: tuple[PathDecision, ...]
    excluded: tuple[PathDecision, ...]


def _canonical(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _is_within(path: str, ancestor: str) -> bool:
    return path == ancestor or path.startswith(ancestor + os.sep)


class CanonicalAllowlist:
    """The approved canonical read scope for one inspection.

    Construction canonicalizes and verifies every approved root; failure to
    establish any root is :class:`AllowlistError` — there is no partial
    allowlist and no read happens before the allowlist exists.
    """

    def __init__(
        self,
        approved_roots: Iterable[str | os.PathLike[str]],
        *,
        denied_paths: Iterable[str | os.PathLike[str]] = (),
        ignored_directory_names: frozenset[str] = IGNORED_DIRECTORY_NAMES,
    ) -> None:
        roots: list[str] = []
        devices: dict[str, int] = {}
        for raw in approved_roots:
            expanded = _canonical(os.fspath(raw))
            if expanded == os.sep:
                raise AllowlistError("the filesystem root is never an approved scope")
            if expanded == os.path.expanduser("~"):
                raise AllowlistError("the whole home directory is never an approved scope")
            try:
                real = os.path.realpath(expanded, strict=True)
                metadata = os.stat(real, follow_symlinks=False)
            except OSError as exc:
                raise AllowlistError(
                    f"approved root {expanded!r} cannot be canonicalized: "
                    f"{type(exc).__name__} — refusing to inspect (fail closed)"
                ) from exc
            if not stat.S_ISDIR(metadata.st_mode):
                raise AllowlistError(
                    f"approved root {expanded!r} is not a directory — refusing (fail closed)"
                )
            roots.append(real)
            devices[real] = metadata.st_dev
        if not roots:
            raise AllowlistError("an empty allowlist admits nothing; refusing to inspect")
        self._roots: tuple[str, ...] = tuple(sorted(set(roots)))
        self._root_devices = devices
        self._denied: tuple[str, ...] = tuple(
            sorted(
                os.path.realpath(_canonical(os.fspath(raw)), strict=False)
                for raw in denied_paths
            )
        )
        self._ignored_directory_names = ignored_directory_names

    @property
    def approved_roots(self) -> tuple[str, ...]:
        """The canonical approved roots (real paths)."""
        return self._roots

    @property
    def denied_canonical_paths(self) -> tuple[str, ...]:
        return self._denied

    def _root_containing(self, canonical_path: str) -> str | None:
        for root in self._roots:
            if _is_within(canonical_path, root):
                return root
        return None

    def _denied_by(self, canonical_path: str) -> str | None:
        for denied in self._denied:
            if _is_within(canonical_path, denied):
                return denied
        return None

    def evaluate(self, path: str | os.PathLike[str]) -> PathDecision:
        """Resolve ``path`` to its real path and decide, before any read.

        The decision is the only doorway to a read: the snapshot layer reads
        exclusively through admitted decisions' canonical paths.
        """
        given = os.fspath(path)
        absolute = _canonical(given)

        def refusal(
            reason: str, *, verdict: PathVerdict = PathVerdict.BLOCKED, ambiguous: bool = False
        ) -> PathDecision:
            return PathDecision(
                verdict=verdict,
                given_path=given,
                canonical_path=None,
                relative_path=None,
                reason=reason,
                ambiguous=ambiguous,
            )

        if not os.path.lexists(absolute):
            return refusal("not-found", verdict=PathVerdict.ABSENT)
        try:
            real = os.path.realpath(absolute, strict=True)
        except FileNotFoundError:
            # A dangling symlink: the name exists, the target verifiably does
            # not. That is unambiguous absence, not runtime ambiguity — an
            # honest `absent` exclusion. Treating it as ambiguous would abort
            # the whole inspection, letting any inspected system disable the
            # deep adapter with a single broken link.
            return refusal("dangling-symlink", verdict=PathVerdict.ABSENT)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                # A symlink loop is unambiguously unresolvable: honest
                # `blocked` exclusion, not an inspection-wide abort.
                return refusal("symlink-loop")
            return refusal(f"resolution-ambiguous:{type(exc).__name__}", ambiguous=True)

        root = self._root_containing(real)
        if root is None:
            if self._root_containing(absolute) is not None:
                return refusal("symlink-escape")
            return refusal("outside-allowlist")

        denied = self._denied_by(real) or self._denied_by(absolute)
        if denied is not None:
            return refusal("denied-path")

        try:
            metadata = os.stat(real, follow_symlinks=False)
        except OSError as exc:
            return refusal(f"resolution-ambiguous:{type(exc).__name__}", ambiguous=True)
        if stat.S_ISLNK(metadata.st_mode):
            # realpath said fully resolved, but the path is a link now: a
            # race is runtime ambiguity, which aborts the inspection.
            return refusal("resolution-ambiguous:symlink-race", ambiguous=True)
        if metadata.st_dev != self._root_devices[root]:
            return refusal("mount-point-crossing")
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1:
            # Another hard link to these bytes may live outside the
            # allowlist; that cannot be proven from here. Fail closed.
            return refusal("hardlink-ambiguous")
        if not stat.S_ISREG(metadata.st_mode) and not stat.S_ISDIR(metadata.st_mode):
            return refusal("special-file")

        return PathDecision(
            verdict=PathVerdict.ADMITTED,
            given_path=given,
            canonical_path=real,
            relative_path=os.path.relpath(real, root),
            reason="within-approved-scope",
            is_directory=stat.S_ISDIR(metadata.st_mode),
        )

    def survey(self) -> SurveyOutcome:
        """Walk the approved roots and decide every entry. Deterministic order.

        Symlinked directories are never descended (they are evaluated and
        recorded; in-scope targets are reached via their real paths under
        the same root). Ignored directories are pruned and recorded.
        """
        admitted: list[PathDecision] = []
        excluded: list[PathDecision] = []

        def note(decision: PathDecision) -> None:
            (admitted if decision.is_admitted else excluded).append(decision)

        def on_walk_error(error: OSError) -> None:
            # A directory that cannot be listed is an honest `blocked`
            # exclusion, never a silent gap in the inventory.
            failed = getattr(error, "filename", None) or "(unlistable directory)"
            excluded.append(
                PathDecision(
                    verdict=PathVerdict.BLOCKED,
                    given_path=str(failed),
                    canonical_path=None,
                    relative_path=None,
                    reason=f"walk-error:{type(error).__name__}",
                    is_directory=True,
                )
            )

        for root in self._roots:
            for current_dir, dirnames, filenames in os.walk(
                root, onerror=on_walk_error, followlinks=False
            ):
                kept: list[str] = []
                for name in sorted(dirnames):
                    full = os.path.join(current_dir, name)
                    if name in self._ignored_directory_names:
                        excluded.append(
                            PathDecision(
                                verdict=PathVerdict.BLOCKED,
                                given_path=full,
                                canonical_path=None,
                                relative_path=os.path.relpath(full, root),
                                reason="ignored-directory",
                                is_directory=True,
                            )
                        )
                        continue
                    if os.path.islink(full):
                        decision = self.evaluate(full)
                        if not decision.is_admitted:
                            excluded.append(decision)
                        # in-scope symlink targets are reached by real path;
                        # never descend through the link itself.
                        continue
                    if os.path.ismount(full):
                        excluded.append(
                            PathDecision(
                                verdict=PathVerdict.BLOCKED,
                                given_path=full,
                                canonical_path=None,
                                relative_path=os.path.relpath(full, root),
                                reason="mount-point-crossing",
                                is_directory=True,
                            )
                        )
                        continue
                    kept.append(name)
                dirnames[:] = kept
                for name in sorted(filenames):
                    decision = self.evaluate(os.path.join(current_dir, name))
                    if decision.is_admitted and decision.is_directory:
                        continue  # a file entry resolved to a directory: skip
                    note(decision)
        return SurveyOutcome(admitted_files=tuple(admitted), excluded=tuple(excluded))
