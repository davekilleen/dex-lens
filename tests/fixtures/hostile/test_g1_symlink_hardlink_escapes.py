"""G1 hostile fixtures 1–2 (gates.md): symlink and hard-link escapes.

Symlinks from an allowlisted directory to a fake ``~/.ssh`` and an
out-of-scope home, plus the hard-link variant, must be refused with honest
exclusion records — and not one byte behind them may reach the snapshot or
the envelope.

The third variant gates.md G1 fixture (2) requires — the bind mount — lives
in ``test_g1_bind_mount_escape.py``: it needs a user namespace and a child
process, because a bind mount is only constructible with ``CAP_SYS_ADMIN``
and only visible inside the mount namespace that made it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.adapters.claude_code.fixture_helpers import tree_digests
from tests.fixtures.hostile.catalog import (
    CANARY_HARDLINK_BYTES,
    CANARY_HOME_NOTE,
    CANARY_SSH_KEY_BYTES,
    SymlinkEscapeSystem,
    assert_no_canary_leak,
    build_symlink_escape_system,
)
from tests.fixtures.hostile.pipeline import collect_from, serialized, snapshot_of

from capability_exchange.evidence import EvidenceState


@pytest.fixture
def escape_system(tmp_path: Path) -> SymlinkEscapeSystem:
    return build_symlink_escape_system(tmp_path)


def _exclusion_references(root: Path) -> list[str]:
    envelope = collect_from(root)
    probe = {p.probe_id: p for p in envelope.probes}["collection-exclusions"]
    return [item.reference for item in probe.evidence]


def test_g1_symlinked_ssh_directory_never_entered(
    escape_system: SymlinkEscapeSystem,
) -> None:
    _contract, snapshot = snapshot_of(escape_system.root)
    captured = snapshot.canonical_paths()
    assert not any(".ssh" in path for path in captured)
    for path in captured:
        assert_no_canary_leak(
            snapshot.content_of(path),
            [CANARY_SSH_KEY_BYTES, CANARY_HOME_NOTE],
            context="snapshot content",
        )


def test_g1_symlinked_key_file_refused_with_honest_record(
    escape_system: SymlinkEscapeSystem,
) -> None:
    references = _exclusion_references(escape_system.root)
    assert any("symlink-escape" in ref for ref in references)
    assert_no_canary_leak(
        "\n".join(references), [CANARY_SSH_KEY_BYTES], context="exclusion references"
    )


def test_g1_symlink_to_out_of_scope_home_refused(
    escape_system: SymlinkEscapeSystem,
) -> None:
    envelope = collect_from(escape_system.root)
    assert_no_canary_leak(
        serialized(envelope),
        [CANARY_HOME_NOTE, CANARY_SSH_KEY_BYTES],
        context="serialized envelope",
    )
    probe = {p.probe_id: p for p in envelope.probes}["collection-exclusions"]
    blocked = [i for i in probe.evidence if i.state is EvidenceState.BLOCKED]
    assert blocked, "escape attempts must yield honest blocked exclusion records"


def test_g1_hardlink_to_out_of_scope_bytes_refused(
    escape_system: SymlinkEscapeSystem,
) -> None:
    _contract, snapshot = snapshot_of(escape_system.root)
    assert str(escape_system.hardlink_path) not in snapshot.canonical_paths()
    envelope = collect_from(escape_system.root)
    assert_no_canary_leak(
        serialized(envelope), [CANARY_HARDLINK_BYTES], context="serialized envelope"
    )
    references = _exclusion_references(escape_system.root)
    assert any("hardlink-ambiguous" in ref for ref in references)


def test_g1_whole_escape_fixture_leak_free_and_unwritten(
    escape_system: SymlinkEscapeSystem, tmp_path: Path
) -> None:
    before = tree_digests(tmp_path)
    envelope = collect_from(escape_system.root)
    assert tree_digests(tmp_path) == before, "inspection must write nothing"
    assert_no_canary_leak(serialized(envelope), context="serialized envelope")


def test_g1_broken_links_do_not_disable_the_adapter(
    escape_system: SymlinkEscapeSystem,
) -> None:
    """Adversarial M1 fixture: unresolvable links degrade the finding, not
    the inspection.

    A dangling symlink and a symlink loop are trivial to plant and ordinary
    in real systems. If either aborted the whole inspection, any inspected
    system could deny itself the deep adapter with one `ln -s`. They must
    become honest per-path exclusions while the rest of the scope is still
    collected.
    """
    (escape_system.root / "broken-link.md").symlink_to(
        escape_system.root / "never-existed.md"
    )
    loop = escape_system.root / "loop.md"
    loop.symlink_to(loop)

    envelope = collect_from(escape_system.root)
    references = _exclusion_references(escape_system.root)
    assert any("dangling-symlink" in ref for ref in references)
    assert any("symlink-loop" in ref for ref in references)

    _contract, snapshot = snapshot_of(escape_system.root)
    assert snapshot.canonical_paths(), "the rest of the approved scope is still collected"
    assert_no_canary_leak(serialized(envelope), context="serialized envelope")
