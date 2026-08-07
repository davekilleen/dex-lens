"""Versioned Host Adapter contract (HANDOFF 2.3 M-A; gates.md G1).

A Host Adapter is a system-specific interpreter mapping one environment's
evidence into the provider-neutral Job Map and Capability Map contracts —
never a universal scanner. Its contract declares, machine-readably and up
front: discoverable roots, explicit read scope, denied paths, symlink and
archive policy, supported evidence probes, the version detection method,
and whether the host is Diagnose-only or Adapt-capable.

Two rules are load-bearing here:

- **Diagnose-only by default.** A host with no explicit ownership/mutation
  contract is Diagnose-only — the hard boundary from #348: "no host-specific
  ownership and rewind contract means Diagnose-only."
- **Adapt-capable is unrepresentable in M1.** The mutation contract is a
  forward-declared type (:class:`MutationContractRef`) that cannot be
  constructed until M4 builds the real host-specific mutation contract, so
  no code path can produce an Adapt-capable contract today.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, final

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_exchange.boundary.serialization import InventoriedModel

__all__ = [
    "AdaptCapableUnrepresentableError",
    "AdapterContract",
    "AdapterMode",
    "ArchivePolicy",
    "MutationContractRef",
    "MutationContractUnavailableError",
    "SymlinkPolicy",
    "VersionDetectionMethod",
]


class MutationContractUnavailableError(Exception):
    """The host-specific mutation contract does not exist yet (M4 builds it)."""


class AdaptCapableUnrepresentableError(Exception):
    """Adapt-capable was requested without a mutation contract to back it."""


class AdapterMode(StrEnum):
    """Diagnose-only vs Adapt-capable status of a host.

    Diagnose-only is the default and, in M1, the only representable mode.
    """

    DIAGNOSE_ONLY = "diagnose-only"
    ADAPT_CAPABLE = "adapt-capable"


class SymlinkPolicy(StrEnum):
    """Closed symlink-handling vocabulary (G1 item d).

    Both members are containment-preserving; there is deliberately no
    "follow" member — a symlink escaping the allowlist is always rejected.
    """

    RESOLVE_AND_REJECT_ESCAPES = "resolve-and-reject-escapes"
    REFUSE_ALL = "refuse-all"


class ArchivePolicy(StrEnum):
    """Closed archive-handling vocabulary.

    There is deliberately no extracting member: unpacking an archive during
    inspection would read content outside the canonicalized allowlist.
    """

    DO_NOT_OPEN = "do-not-open"
    LIST_NAMES_ONLY = "list-names-only"


class VersionDetectionMethod(StrEnum):
    """Closed version-detection vocabulary.

    Deliberately no command/exec member: G1 forbids arbitrary shell from the
    inspection process, so a version detection method that runs the host's
    own binary is unrepresentable. An undetectable version is ``unknown`` —
    honest, not guessed.
    """

    FILE_MARKER = "file-marker"
    PACKAGE_MANIFEST = "package-manifest"
    USER_REPORTED = "user-reported"
    UNKNOWN = "unknown"


@final
class MutationContractRef(InventoriedModel):
    """Forward declaration of the host-specific mutation contract.

    M4 builds the real thing (ownership, preconditions, backup, verification,
    receipts, rewind — HANDOFF 2.3 M-F). Until then this type cannot be
    constructed by any route — ``__init__``, ``model_validate``, and
    ``model_construct`` all refuse — which makes Adapt-capable structurally
    unrepresentable rather than merely discouraged.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _unconstructable_in_m1(cls, value: object) -> object:
        raise MutationContractUnavailableError(
            "the host-specific mutation contract is forward-declared and cannot "
            "be constructed in M1; M4 builds it. Until then every host is "
            "Diagnose-only."
        )

    @classmethod
    def model_construct(cls, *args: Any, **kwargs: Any) -> MutationContractRef:
        raise MutationContractUnavailableError(
            "the host-specific mutation contract cannot be constructed in M1, "
            "including via model_construct; M4 builds it."
        )


_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _path_parts(raw: str, field: str) -> tuple[str, ...]:
    """Parse a declared path into components, or raise ``ValueError``.

    Paths must be absolute (``/...``) or home-anchored (``~/...``); no
    relative paths, no ``.``/``..`` components, no control characters, no
    backslashes. Bare ``/`` (the whole filesystem) is never an explicit
    scope, and bare ``~`` (the whole home) is never a discoverable root or
    read scope.
    """
    if not raw or raw != raw.strip():
        raise ValueError(f"{field} entry {raw!r} is empty or has surrounding whitespace")
    if _CONTROL_RE.search(raw) or "\\" in raw:
        raise ValueError(f"{field} entry {raw!r} contains control characters or backslashes")
    if raw == "/":
        raise ValueError(f"{field} entry '/': the entire filesystem is never an explicit scope")
    if raw == "~":
        if field == "denied_paths":
            return ("~",)
        raise ValueError(
            f"{field} entry '~': the entire home directory is not an explicit "
            f"{field.replace('_', ' ')}"
        )
    if raw.startswith("~/"):
        head, rest = ("~",), raw[2:]
    elif raw.startswith("/"):
        head, rest = ("/",), raw[1:]
    else:
        raise ValueError(f"{field} entry {raw!r} must be absolute or '~/'-anchored")
    parts = rest.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(
            f"{field} entry {raw!r} contains empty, '.', or '..' components; "
            f"declared paths are canonical, never traversals"
        )
    return head + tuple(parts)


def _is_under(child: tuple[str, ...], ancestor: tuple[str, ...]) -> bool:
    """Whether ``child`` equals or lies under ``ancestor``, by component."""
    return len(child) >= len(ancestor) and child[: len(ancestor)] == ancestor


def _require_unique(values: tuple[str, ...], field: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field} contains duplicate entries")


@final
class AdapterContract(InventoriedModel):
    """The versioned declaration one Host Adapter ships and is held to.

    Frozen and closed: the conformance suite (M1) validates real adapters
    against exactly what is declared here, and the contract itself lives
    inside the G2 typed serialization boundary (every field inventoried;
    ephemeral, never transmitted).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Stable kebab-case adapter identity (e.g. ``claude-code-macos``).
    adapter_id: str
    #: Contract version (semver). A changed contract is a new version.
    contract_version: str
    #: Where discovery may start. Explicit, canonical, never ``/`` or ``~``.
    discoverable_roots: tuple[str, ...] = Field(min_length=1)
    #: The explicit read scope. Every entry must fall under a declared root.
    read_scope: tuple[str, ...] = Field(min_length=1)
    #: Paths never read even inside scope (secrets, credentials, ...).
    denied_paths: tuple[str, ...] = ()
    #: Symlink handling (closed vocabulary; escapes always rejected).
    symlink_policy: SymlinkPolicy
    #: Archive handling (closed vocabulary; extraction unrepresentable).
    archive_policy: ArchivePolicy
    #: The evidence probes this adapter supports (kebab-case ids).
    evidence_probes: tuple[str, ...] = Field(min_length=1)
    #: How the host's version is detected (closed vocabulary; no exec).
    version_detection: VersionDetectionMethod
    #: Diagnose-only by default. Adapt-capable requires a mutation contract.
    mode: AdapterMode = AdapterMode.DIAGNOSE_ONLY
    #: Forward-declared in M1: unconstructable, so always ``None`` today.
    mutation_contract: MutationContractRef | None = None

    @field_validator("adapter_id")
    @classmethod
    def _kebab_adapter_id(cls, value: str) -> str:
        if not _KEBAB_RE.match(value):
            raise ValueError(f"adapter_id {value!r} must be kebab-case")
        return value

    @field_validator("contract_version")
    @classmethod
    def _semver_version(cls, value: str) -> str:
        if not _SEMVER_RE.match(value):
            raise ValueError(f"contract_version {value!r} must be MAJOR.MINOR.PATCH")
        return value

    @field_validator("evidence_probes")
    @classmethod
    def _kebab_unique_probes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for probe_id in value:
            if not _KEBAB_RE.match(probe_id):
                raise ValueError(f"evidence probe id {probe_id!r} must be kebab-case")
        _require_unique(value, "evidence_probes")
        return value

    @model_validator(mode="after")
    def _coherent_and_diagnose_only_backed(self) -> AdapterContract:
        _require_unique(self.discoverable_roots, "discoverable_roots")
        _require_unique(self.read_scope, "read_scope")
        _require_unique(self.denied_paths, "denied_paths")

        roots = [_path_parts(root, "discoverable_roots") for root in self.discoverable_roots]
        denied = [
            (raw, _path_parts(raw, "denied_paths")) for raw in self.denied_paths
        ]
        for raw_scope in self.read_scope:
            scope = _path_parts(raw_scope, "read_scope")
            if not any(_is_under(scope, root) for root in roots):
                raise ValueError(
                    f"read_scope entry {raw_scope!r} falls under no discoverable root; "
                    f"the read scope must be explicit and rooted"
                )
            for raw_denied, denied_parts in denied:
                if _is_under(scope, denied_parts):
                    raise ValueError(
                        f"read_scope entry {raw_scope!r} is entirely denied by "
                        f"{raw_denied!r}; a dead scope entry is incoherent — "
                        f"remove the scope entry or narrow the denial"
                    )

        self._assert_adapt_capable_backed()
        return self

    def _assert_adapt_capable_backed(self) -> None:
        """Refuse Adapt-capable without a mutation contract. Fail closed."""
        mode = self.mode
        if not isinstance(mode, AdapterMode):
            try:
                mode = AdapterMode(str(mode))
            except ValueError as exc:
                raise AdaptCapableUnrepresentableError(
                    f"unknown adapter mode {self.mode!r}; an unverifiable mode "
                    f"cannot be treated as Diagnose-only silently — refused"
                ) from exc
        if mode is AdapterMode.ADAPT_CAPABLE and self.mutation_contract is None:
            raise AdaptCapableUnrepresentableError(
                'Adapt-capable requires a host-specific ownership and mutation '
                'contract: "no host-specific ownership and rewind contract means '
                'Diagnose-only" (#348). The mutation contract is forward-declared '
                'and cannot be constructed until M4, so this host is Diagnose-only.'
            )

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> AdapterContract:
        # model_construct skips validation by design; the Diagnose-only
        # boundary must hold even on that route.
        contract = super().model_construct(_fields_set, **values)
        contract._assert_adapt_capable_backed()
        return contract

    def model_copy(
        self, *, update: dict[str, Any] | None = None, deep: bool = False
    ) -> AdapterContract:
        # model_copy also skips validation; an escalating update
        # (mode=adapt-capable) must refuse the same way.
        copied = super().model_copy(update=update, deep=deep)
        copied._assert_adapt_capable_backed()
        return copied
