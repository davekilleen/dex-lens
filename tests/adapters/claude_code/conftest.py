"""Pytest fixtures for the Claude Code deep adapter tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.adapters.claude_code.fixture_helpers import build_claude_root, plant_secrets


@pytest.fixture
def claude_root(tmp_path: Path) -> Path:
    return build_claude_root(tmp_path)


@pytest.fixture
def secret_bearing_root(tmp_path: Path) -> Path:
    root = build_claude_root(tmp_path)
    plant_secrets(root)
    return root
