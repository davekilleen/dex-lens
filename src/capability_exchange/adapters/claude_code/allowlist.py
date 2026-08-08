"""Canonicalized real-path allowlist (gates.md G1 items b and d).

Every path is resolved to its real path (``os.path.realpath``, strict)
**before** any read; reads outside the approved canonical set are refused.
Symlinks whose target escapes the allowlist and hard links whose other
names cannot be proven in-scope are rejected with an honest exclusion
record. Mount-point and ignored-file policy are explicit:

- **Mount points:** collection never crosses a mount boundary *inside* an
  approved root — not a device boundary, a mount boundary. A foreign
  filesystem changes ``st_dev`` and is caught by that; a **bind mount**
  within one filesystem does not, so device comparison alone is not enough
  (see :meth:`CanonicalAllowlist._refresh_mount_topology` for exactly why
  the obvious checks miss it). Every mount at or below an approved root is
  refused ``mount-point-crossing``.
- **Ignored directories:** VCS internals and dependency trees
  (:data:`IGNORED_DIRECTORY_NAMES`) are pruned for bounded collection and
  each pruning is recorded — never silent.
- **Ignored files:** files a VCS would ignore (e.g. ``.gitignore``\\ d) are
  **not** skipped. They are inspected under the same allowlist and secret
  redaction, because skipping them would miss planted secrets (G1 hostile
  fixture 3).

Fail closed: a path whose resolution is ambiguous (racy symlink, resolution
error) is marked ``ambiguous`` — the snapshot layer aborts the whole
inspection on it rather than best-effort reading (G1 fail-closed rule).
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "IGNORED_DIRECTORY_NAMES",
    "MOUNTINFO_PATH",
    "AllowlistError",
    "CanonicalAllowlist",
    "PathDecision",
    "PathVerdict",
    "SurveyOutcome",
    "read_mount_points",
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


#: Where Linux publishes this process's complete mount table — bind mounts
#: included, which is the whole point. Module-level so a test can point the
#: reader at a captured table instead of the live one.
MOUNTINFO_PATH = "/proc/self/mountinfo"

#: ``mountinfo`` octal-escapes exactly these four characters in path fields.
_MOUNTINFO_ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


def _unescape_mountinfo_field(field: str) -> str:
    head, *rest = field.split("\\")
    parts = [head]
    for chunk in rest:
        replacement = _MOUNTINFO_ESCAPES.get(chunk[:3])
        if replacement is None:
            # An escape the kernel does not emit: the line is not the format
            # we know how to read, and a mount we cannot parse is a mount we
            # cannot rule out.
            raise AllowlistError(
                f"unparseable escape in mount table field {field!r} — "
                f"refusing to inspect (fail closed)"
            )
        parts.append(replacement + chunk[3:])
    return "".join(parts)


def read_mount_points(path: str = MOUNTINFO_PATH) -> frozenset[str]:
    """Every mount point in this process's mount namespace (Linux).

    Field 5 of each ``/proc/self/mountinfo`` line is the mount point as an
    absolute path built from dentries — already free of symlinks, which is
    exactly the form the allowlist compares canonical paths against.

    Every line is shape-checked before its mount point is trusted (mount id,
    parent id, ``major:minor``, an absolute mount point, and the ``-``
    separator that ends the optional fields). The *root* field is
    deliberately not required to be a path: pseudo-filesystems put things
    like ``net:[4026532534]`` there, and a check that rejected real kernel
    output would turn every inspection on a host running containers into a
    refusal.

    Raises :class:`OSError` when the table cannot be read and
    :class:`AllowlistError` when a line does not parse; both are fail-closed
    conditions for the caller. A table this code
    does not understand must never read as "no mounts here".
    """
    with open(path, encoding="utf-8", errors="surrogateescape") as handle:
        lines = handle.read().splitlines()
    points: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        fields = line.split(" ")
        well_formed = (
            len(fields) >= 10
            and fields[0].isdigit()
            and fields[1].isdigit()
            and fields[2].count(":") == 1
            and fields[4].startswith("/")
            and "-" in fields[6:]
        )
        if not well_formed:
            raise AllowlistError(
                f"unparseable mount table line {line!r} — refusing to inspect (fail closed)"
            )
        points.add(_unescape_mountinfo_field(fields[4]))
    return frozenset(points)


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
        self._mount_points: frozenset[str] = frozenset()
        self._refresh_mount_topology()

    def _refresh_mount_topology(self) -> None:
        """Record every mount point sitting strictly below an approved root.

        Why the kernel's mount table and not ``st_dev`` or
        ``os.path.ismount``. ``mount --bind ~/.ssh <root>/subdir`` inside a
        single filesystem produces a directory that:

        * keeps the approved root's ``st_dev`` — the device comparison in
          :meth:`evaluate` passes;
        * has an ``st_ino`` of its own, different from its parent's —
          ``posixpath.ismount`` returns True only on a device change or when
          ``st_ino == parent st_ino`` (a filesystem root), so it returns
          False;
        * is not a symlink — ``realpath`` does not unwind a bind mount.

        Every check the adapter had therefore said "in scope", and every byte
        of the bound-in credentials was admitted with no exclusion record.
        The mount table is the one place the kernel admits the mount exists,
        so it is the check that actually closes gates.md G1 fixture (2).

        A mount at an approved root *itself* is deliberately not refused:
        that is the path the person named at consent time, and it is what
        every device comparison below is anchored to. A mount *inside* it is
        a scope the person never approved.

        Re-read rather than cached-forever: the topology is established
        before any read and refreshed at the top of :meth:`survey`, so a
        mount landing between consent and collection is still seen.
        """
        if sys.platform != "linux":
            # No /proc mount table here. macOS has no unprivileged bind mount
            # at all (no `mount_nullfs`; APFS firmlinks are system-owned), and
            # the FUSE re-exports that come closest always present a distinct
            # `st_dev`, which the device comparison already refuses. The
            # dirent-inode cross-check in `survey` is the OS-independent
            # backstop. Stated here so the limit is auditable rather than
            # assumed (HANDOFF 5.5) — it is a reasoned limit, not a gap.
            self._mount_points = frozenset()
            return
        try:
            table = read_mount_points(MOUNTINFO_PATH)
        except OSError as exc:
            raise AllowlistError(
                f"the kernel mount table at {MOUNTINFO_PATH} cannot be read "
                f"({type(exc).__name__}): a bind mount inside an approved root "
                f"cannot be ruled out — refusing to inspect (fail closed)"
            ) from exc
        self._mount_points = frozenset(
            point
            for point in table
            for root in self._roots
            if point != root and _is_within(point, root)
        )

    @property
    def mount_points_inside_scope(self) -> tuple[str, ...]:
        """Mount points found strictly below an approved root, sorted.

        Non-empty means the approved scope has had a foreign filesystem or a
        bind mount grafted into it; everything at or below each entry is
        refused.
        """
        return tuple(sorted(self._mount_points))

    def _under_mount_inside_scope(self, canonical_path: str) -> bool:
        return any(_is_within(canonical_path, point) for point in self._mount_points)

    def _is_mount_point(self, canonical_path: str, dirent_inode: int | None = None) -> bool:
        """Does something sit mounted on ``canonical_path``?

        Three independent signals, any one of which is enough (fail closed):

        1. the kernel mount table — authoritative, and the only signal that
           sees a same-device bind mount from the outside (Linux);
        2. ``readdir`` inode vs ``stat`` inode. The parent directory's entry
           still names the *covered* directory's inode, while ``stat``
           traverses the mount and reports the mounted filesystem's root
           inode. A mismatch means a mount, on any POSIX host, with no
           ``/proc`` needed — this is the layer that carries macOS. Platforms
           that cannot supply a real ``d_ino`` fall back to ``st_ino`` and the
           signal simply never fires; it never fires falsely;
        3. ``os.path.ismount`` — device change or filesystem root, kept for
           what (1) and (2) cannot see.
        """
        if canonical_path in self._mount_points:
            return True
        if dirent_inode is not None:
            try:
                if os.stat(canonical_path, follow_symlinks=False).st_ino != dirent_inode:
                    return True
            except OSError:
                # Cannot compare ⇒ cannot rule a mount out.
                return True
        return os.path.ismount(canonical_path)

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
        except OSError as exc:
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
        if self._under_mount_inside_scope(real):
            # At or below a mount grafted into the approved scope. A bind
            # mount keeps the root's device, so the comparison above passed
            # and `real` looks perfectly in-scope; without this check every
            # byte behind it is admitted with no exclusion record.
            return refusal("mount-point-crossing")
        if (
            real != root
            and stat.S_ISDIR(metadata.st_mode)
            and self._is_mount_point(real)
        ):
            # The root itself is the scope the person named; anything else
            # that is a mount point is a scope they did not approve.
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

        The mount topology is re-read first: a mount grafted into the scope
        between allowlist construction and this walk must still be refused.
        """
        self._refresh_mount_topology()
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
                # The directory entries' own inode numbers, as `readdir`
                # reports them. A mount hides its mount point's inode behind
                # the mounted filesystem's root inode, so entry inode != stat
                # inode is a mount — see `_is_mount_point` signal (2).
                dirent_inodes: dict[str, int] = {}
                try:
                    with os.scandir(current_dir) as entries:
                        for entry in entries:
                            dirent_inodes[entry.name] = entry.inode()
                except OSError as error:
                    on_walk_error(error)

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
                    if self._is_mount_point(full, dirent_inodes.get(name)):
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
