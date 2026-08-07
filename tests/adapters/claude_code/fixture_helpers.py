"""Shared fixture helpers for the Claude Code deep adapter tests.

The hostile fixture *catalog* (tests/fixtures/hostile/) is a separate M1
deliverable and is not built here; these are the unit-level fixtures the
adapter's own property tests run against.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

#: A realistic planted credential set (synthetic; G1 hostile fixture 4 shape).
PLANTED_AWS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
PLANTED_SECRET_VALUE = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
PLANTED_API_TOKEN = "sk-c4n4ryc4n4ryc4n4ryc4n4ry"
PLANTED_PRIVATE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "c2VjcmV0LWtleS1ib2R5LWNhbmFyeQ==\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


def build_claude_root(base: Path) -> Path:
    """A benign local folder-based Claude Code system."""
    root = base / "claude-root"
    (root / ".claude" / "skills" / "demo").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("Project instructions for a real repeated job.\n")
    (root / ".claude" / "settings.json").write_text('{"model": "opus"}\n')
    (root / ".claude" / "skills" / "demo" / "SKILL.md").write_text("# demo skill\n")
    (root / "notes.md").write_text("Weekly review notes.\n")
    return root


def plant_secrets(root: Path) -> Path:
    """Plant realistic credentials inside the scope (must never leave raw)."""
    target = root / ".claude" / "secrets.env"
    target.write_text(
        f"AWS_ACCESS_KEY_ID={PLANTED_AWS_KEY_ID}\n"
        f"AWS_SECRET_ACCESS_KEY={PLANTED_SECRET_VALUE}\n"
        f"OPENAI_API_KEY={PLANTED_API_TOKEN}\n"
        f"{PLANTED_PRIVATE_KEY}"
    )
    return target


def tree_digests(root: Path) -> dict[str, tuple[int, str]]:
    """(mtime_ns, sha256) for every file under root — byte-identity witness."""
    digests: dict[str, tuple[int, str]] = {}
    for current_dir, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = Path(current_dir) / name
            stat_result = full.lstat()
            content = full.read_bytes() if not full.is_symlink() else b""
            digests[str(full)] = (stat_result.st_mtime_ns, hashlib.sha256(content).hexdigest())
    return digests


