"""Non-negotiable boundary 1: the adapter package exposes no mutating entry
point, structurally — the import-time scan covers every module here."""

from __future__ import annotations

import ast
import importlib
import pkgutil
import types
from pathlib import Path

import pytest

from capability_exchange.adapter.surface import (
    ReadOnlySurfaceViolation,
    assert_read_only_surface,
)
from capability_exchange.adapters.claude_code import (
    allowlist,
    collector,
    contained,
    containment,
    contract,
    secrets,
    snapshot,
    version_detection,
)

ALL_ADAPTER_MODULES = (
    allowlist,
    collector,
    contained,
    containment,
    contract,
    secrets,
    snapshot,
    version_detection,
)


def test_every_module_passes_the_read_only_scan() -> None:
    assert_read_only_surface(modules=ALL_ADAPTER_MODULES)


def test_package_import_runs_the_scan() -> None:
    # The call sits at the bottom of the package __init__; the import above
    # succeeding is the assertion. Verify the guard is present, not vestigial.
    import capability_exchange.adapters.claude_code as package

    source = (package.__file__ or "")
    assert source.endswith("__init__.py")
    with open(source, encoding="utf-8") as handle:
        assert "assert_read_only_surface(" in handle.read()


def test_scan_rejects_a_mutating_entry_point() -> None:
    hostile = types.ModuleType("capability_exchange.adapters.claude_code.hostile_fixture")

    def upload_collected_evidence() -> None:  # pragma: no cover - never called
        raise NotImplementedError

    upload_collected_evidence.__module__ = hostile.__name__
    hostile.upload_collected_evidence = upload_collected_evidence  # type: ignore[attr-defined]
    with pytest.raises(ReadOnlySurfaceViolation, match="upload"):
        assert_read_only_surface(modules=(hostile,))


_FORBIDDEN_PACKAGES = (
    "capability_exchange.adaptation",
    "capability_exchange.contribution",
    "capability_exchange.share",
)
_FORBIDDEN_MODULES = frozenset(
    {
        "subprocess",
        "httpx",
        "requests",
        "urllib.request",
        "urllib3",
    }
)


def _import_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _diagnosis_and_replay_modules() -> tuple[types.ModuleType, ...]:
    package = importlib.import_module("capability_exchange.diagnosis")
    modules = [package]
    for info in pkgutil.walk_packages(package.__path__, prefix=f"{package.__name__}."):
        modules.append(importlib.import_module(info.name))
    replay = importlib.import_module("capability_exchange.evaluation.replay")
    modules.append(replay)
    return tuple(modules)


def test_diagnosis_imports_never_reach_mutation_or_send_paths() -> None:
    for module in _diagnosis_and_replay_modules():
        path = Path(module.__file__ or "")
        assert path.is_file(), module.__name__
        imported = _import_names(path)
        for name in imported:
            for banned in _FORBIDDEN_PACKAGES:
                assert name != banned and not name.startswith(f"{banned}."), (
                    f"{module.__name__} imports {name}"
                )
            root = name.split(".")[0] if "." in name else name
            if name in _FORBIDDEN_MODULES or (
                name.startswith("urllib.") and name != "urllib.parse"
            ):
                raise AssertionError(f"{module.__name__} imports {name}")
            if root in {"subprocess", "httpx", "requests"}:
                raise AssertionError(f"{module.__name__} imports {name}")


def test_scan_rejects_a_write_method_on_a_class() -> None:
    hostile = types.ModuleType("capability_exchange.adapters.claude_code.hostile_cls")

    class SnapshotSideDoor:
        def write_to_target(self) -> None:  # pragma: no cover - never called
            raise NotImplementedError

    SnapshotSideDoor.__module__ = hostile.__name__
    hostile.SnapshotSideDoor = SnapshotSideDoor  # type: ignore[attr-defined]
    with pytest.raises(ReadOnlySurfaceViolation, match="write"):
        assert_read_only_surface(modules=(hostile,))
