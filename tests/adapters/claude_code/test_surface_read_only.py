"""Non-negotiable boundary 1: the adapter package exposes no mutating entry
point, structurally — the import-time scan covers every module here."""

from __future__ import annotations

import types

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


def test_scan_rejects_a_write_method_on_a_class() -> None:
    hostile = types.ModuleType("capability_exchange.adapters.claude_code.hostile_cls")

    class SnapshotSideDoor:
        def write_to_target(self) -> None:  # pragma: no cover - never called
            raise NotImplementedError

    SnapshotSideDoor.__module__ = hostile.__name__
    hostile.SnapshotSideDoor = SnapshotSideDoor  # type: ignore[attr-defined]
    with pytest.raises(ReadOnlySurfaceViolation, match="write"):
        assert_read_only_surface(modules=(hostile,))
