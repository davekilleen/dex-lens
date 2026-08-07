"""The model/UI-facing diagnosis surface: read, preview, bounded status ONLY.

Mirrors dex-core's ``core/mcp/customization_migration_server.py`` read-only
pattern: the surface exposed to a model or UI holds assessment reads,
bounded previews, and status — and nothing that writes to a host system.

Non-negotiable boundary 1 (HANDOFF 3.5): diagnosis is read-only, and the
reused Doctor/assessor grammars' mutating paths (heal, adopt, any
model-exposed write tool) must not exist on the diagnosis side. This module
enforces that structurally: :func:`assert_read_only_surface` scans every
public callable the adapter package defines and refuses any name that
denotes a mutating operation. The package runs the scan at import time, and
the test suite runs it again with hostile fixture modules.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import sys
from collections.abc import Iterable, Iterator
from types import FunctionType, ModuleType
from typing import final

from capability_exchange.adapter.envelope import (
    AdapterResultEnvelope,
    InstrumentHealth,
    ProbeResult,
)
from capability_exchange.evidence import EvidenceItem

__all__ = [
    "MUTATING_NAME_TOKENS",
    "PREVIEW_LIMIT_DEFAULT",
    "PREVIEW_LIMIT_MAX",
    "DiagnosisSurface",
    "PreviewBoundError",
    "ProbeNotFoundError",
    "ReadOnlySurfaceViolation",
    "assert_read_only_surface",
]


class ProbeNotFoundError(LookupError):
    """The requested probe id is not in the envelope. Honest refusal."""


class PreviewBoundError(ValueError):
    """A preview was requested outside the bounded limits. Honest refusal."""


class ReadOnlySurfaceViolation(Exception):
    """A public callable on the diagnosis surface names a mutating operation."""


PREVIEW_LIMIT_DEFAULT = 10
PREVIEW_LIMIT_MAX = 50


@final
class DiagnosisSurface:
    """Read, preview, and bounded-status operations over one envelope.

    This is the complete model/UI-facing surface of the adapter package:
    every operation returns frozen data derived from an already-collected
    :class:`AdapterResultEnvelope`. Nothing here touches a host system.
    """

    def __init__(self, envelope: AdapterResultEnvelope) -> None:
        self._envelope = envelope
        self._by_id = {probe.probe_id: probe for probe in envelope.probes}

    def read_envelope(self) -> AdapterResultEnvelope:
        """The full (frozen) envelope."""
        return self._envelope

    def read_probe(self, probe_id: str) -> ProbeResult:
        """One probe's result, or an honest refusal for an unknown id."""
        probe = self._by_id.get(probe_id)
        if probe is None:
            raise ProbeNotFoundError(
                f"no probe {probe_id!r} in this envelope; known probes: "
                f"{sorted(self._by_id)}"
            )
        return probe

    def preview_evidence(
        self, probe_id: str, *, limit: int = PREVIEW_LIMIT_DEFAULT
    ) -> tuple[EvidenceItem, ...]:
        """A bounded preview of one probe's evidence items.

        Limits outside ``1..PREVIEW_LIMIT_MAX`` are refused, not clamped —
        silently shrinking or growing a request would be dishonest about
        what was previewed.
        """
        if not 1 <= limit <= PREVIEW_LIMIT_MAX:
            raise PreviewBoundError(
                f"preview limit must be between 1 and {PREVIEW_LIMIT_MAX}, "
                f"got {limit}; the preview surface is bounded by contract"
            )
        return self.read_probe(probe_id).evidence[:limit]

    def status(self) -> dict[str, int]:
        """Bounded status: counts only, never evidence content."""
        counts = self._envelope.health_counts()
        return {
            "probes": len(self._envelope.probes),
            **{health.value: counts[health] for health in InstrumentHealth},
        }


# ---------------------------------------------------------------------------
# Structural read-only assertion (non-negotiable boundary 1)
# ---------------------------------------------------------------------------

_ADAPTER_PACKAGE = "capability_exchange.adapter"

#: Name tokens that denote a mutating operation. A public callable or
#: property in the adapter package whose name contains any of these tokens
#: is a boundary violation, whatever its body does.
MUTATING_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "write", "writes", "put", "post", "send", "upload", "push", "publish",
        "delete", "remove", "erase", "unlink", "rmdir", "truncate", "purge",
        "create", "make", "mkdir", "insert", "append", "add", "set", "assign",
        "apply", "install", "uninstall", "update", "upgrade", "modify",
        "patch", "edit", "mutate", "mutating", "chmod", "chown", "rename",
        "move", "migrate", "adopt", "heal", "repair", "fix", "execute",
        "exec", "spawn", "shell", "invoke", "run", "save", "persist", "store",
        "transmit", "share", "commit", "rollback", "undo", "restore",
        "revert", "overwrite", "replace", "inject",
    }
)

_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def _name_tokens(name: str) -> frozenset[str]:
    tokens: list[str] = []
    for chunk in name.split("_"):
        tokens.extend(match.lower() for match in _CAMEL_RE.findall(chunk))
    return frozenset(tokens)


def _class_member_names(cls: type) -> Iterator[str]:
    """Public callables/properties a class itself defines (not inherited)."""
    for attr_name, attr in vars(cls).items():
        if attr_name.startswith("_"):
            continue
        if isinstance(attr, FunctionType | classmethod | staticmethod | property):
            yield attr_name


def _surface_names(module: ModuleType) -> Iterator[tuple[str, str]]:
    """(qualified name, bare name) of every entry point the module defines."""
    for name, obj in vars(module).items():
        if name.startswith("_"):
            continue
        defined_in = getattr(obj, "__module__", None)
        if not (defined_in or "").startswith(_ADAPTER_PACKAGE):
            continue  # foreign re-exports are not this package's entry points
        if inspect.isfunction(obj):
            yield f"{module.__name__}.{name}", name
        elif inspect.isclass(obj):
            yield f"{module.__name__}.{name}", name
            for member_name in _class_member_names(obj):
                yield f"{module.__name__}.{name}.{member_name}", member_name


def _adapter_modules() -> list[ModuleType]:
    package = sys.modules.get(_ADAPTER_PACKAGE) or importlib.import_module(_ADAPTER_PACKAGE)
    modules = [package]
    for info in pkgutil.iter_modules(package.__path__, prefix=f"{_ADAPTER_PACKAGE}."):
        modules.append(importlib.import_module(info.name))
    return modules


def assert_read_only_surface(modules: Iterable[ModuleType] | None = None) -> None:
    """Refuse any mutating entry point on the diagnosis surface.

    Scans every public function, class, method, classmethod, staticmethod,
    and property defined by the adapter package (or the given modules) and
    raises :class:`ReadOnlySurfaceViolation` if any name contains a mutating
    token. Runs at package import and again in the test suite.
    """
    if modules is None:
        modules = _adapter_modules()
    violations: list[str] = []
    for module in modules:
        for qualified, bare in _surface_names(module):
            hit = _name_tokens(bare) & MUTATING_NAME_TOKENS
            if hit:
                violations.append(f"{qualified} (tokens: {sorted(hit)})")
    if violations:
        raise ReadOnlySurfaceViolation(
            "mutating entry point(s) on the diagnosis surface: "
            + "; ".join(violations)
            + " — diagnosis is read-only at every level (non-negotiable "
            "boundary 1); no function that writes to a host system may exist "
            "in this package."
        )
