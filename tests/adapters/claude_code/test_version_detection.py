"""Version detection: read-only file markers, honest Unknown when unprovable."""

from __future__ import annotations

from pathlib import Path

from capability_exchange.adapter import VersionDetectionMethod
from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.snapshot import take_snapshot
from capability_exchange.adapters.claude_code.version_detection import (
    InstallationMarker,
    detect_installation,
)


def shape_of(root: Path):  # type: ignore[no-untyped-def]
    return detect_installation(take_snapshot(CanonicalAllowlist([root])))


def test_configured_installation_detected_from_file_markers(claude_root: Path) -> None:
    shape = shape_of(claude_root)
    assert shape.marker is InstallationMarker.CONFIGURED
    assert shape.method is VersionDetectionMethod.FILE_MARKER


def test_instructions_only_shape(tmp_path: Path) -> None:
    root = tmp_path / "sparse"
    root.mkdir()
    (root / "CLAUDE.md").write_text("instructions\n")
    shape = shape_of(root)
    assert shape.marker is InstallationMarker.INSTRUCTIONS_ONLY
    assert shape.method is VersionDetectionMethod.FILE_MARKER


def test_empty_scope_is_honest_unknown(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    (root / "unrelated.txt").write_text("nothing claude-shaped\n")
    shape = shape_of(root)
    assert shape.marker is InstallationMarker.UNKNOWN
    assert shape.method is VersionDetectionMethod.UNKNOWN
    assert "Unknown" in shape.detail


def test_version_is_never_guessed(claude_root: Path, tmp_path: Path) -> None:
    # A version marker is unprovable without executing the host binary,
    # which G1 forbids — so the version is Unknown even when a plausible
    # version string sits in an inspected file.
    (claude_root / ".claude" / "version.txt").write_text("1.2.3\n")
    shape = shape_of(claude_root)
    assert shape.version is None
    assert not shape.version_known


def test_detection_reads_snapshot_not_live_disk(claude_root: Path) -> None:
    snapshot = take_snapshot(CanonicalAllowlist([claude_root]))
    (claude_root / "CLAUDE.md").unlink()
    (claude_root / ".claude" / "settings.json").unlink()
    shape = detect_installation(snapshot)
    assert shape.marker is InstallationMarker.CONFIGURED
