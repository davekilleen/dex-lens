"""The promise the whole product rests on, checked across the whole flow.

Individual pieces are already proven read-only: the collector, the allowlist,
the mutation contract. What was not proven is the *sequence* a person actually
runs — inventory the folder, then save the report about it — and the sequence
is where a read-only product most plausibly stops being one, because the
report is a write and it has to go somewhere.

So this walks the flow over a small system, byte for byte, and fails if a
single file inside the inspected folder is added, removed, or altered.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from capability_exchange.adapters.claude_code.inventory_cli import inventory_main
from capability_exchange.reports import cli as reports_cli

REPORT = """# Dex Lens: a small system - 2026-08-24

## What I read
- Inventory: the whole folder, 2 distinct items

## The mirror
### One skill is switched off by name
> name: _disabled_weekly-note
> - `.claude/skills/_disabled_weekly-note/SKILL.md`
What it costs: someone wanted that and it never landed.

## What happens next
- Nothing has changed on your machine.
"""


def _system(root: Path) -> None:
    """A miniature personal AI system: instructions, settings, two skills."""
    (root / ".claude" / "skills" / "weekly-note").mkdir(parents=True)
    (root / ".claude" / "skills" / "_disabled_weekly-note").mkdir(parents=True)
    (root / "CLAUDE.md").write_text(
        "# House rules\n\nAlways use the shared calendar.\n", encoding="utf-8"
    )
    (root / ".claude" / "settings.json").write_text('{"permissions": {}}\n', encoding="utf-8")
    (root / ".claude" / "skills" / "weekly-note" / "SKILL.md").write_text(
        "---\nname: weekly-note\ndescription: Write the weekly note.\n---\n", encoding="utf-8"
    )
    (root / ".claude" / "skills" / "_disabled_weekly-note" / "SKILL.md").write_text(
        "---\nname: _disabled_weekly-note\ndescription: The one that did not work.\n---\n",
        encoding="utf-8",
    )


def _fingerprint(root: Path) -> dict[str, str]:
    """Every file under the root, by path and content."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def inspected(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    _system(root)
    return root


def test_the_whole_flow_leaves_the_inspected_folder_byte_for_byte_identical(
    inspected: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _fingerprint(inspected)
    reports = tmp_path / "state" / "reports"
    monkeypatch.setattr(reports_cli, "default_report_directory", lambda _roots: reports)
    written_report = tmp_path / "report.md"
    written_report.write_text(REPORT, encoding="utf-8")

    assert inventory_main([str(inspected), "--out", str(tmp_path / "inventory.md")]) == 0
    assert (
        reports_cli.reports_main(
            ["save", str(written_report), "--label", "small", "--for", str(inspected)]
        )
        == 0
    )

    assert _fingerprint(inspected) == before
    saved = Path(capsys.readouterr().out.strip().splitlines()[-1])
    assert saved.parent == reports
    assert not saved.is_relative_to(inspected)


def test_the_report_is_refused_rather_than_written_into_the_inspected_folder(
    inspected: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If app storage ever resolved inside the folder, saving must stop.

    This is the failure that would break the promise quietly: the command
    would succeed, and the only sign would be a file in someone's vault.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(inspected / "state"))
    written_report = tmp_path / "report.md"
    written_report.write_text(REPORT, encoding="utf-8")
    before = _fingerprint(inspected)

    assert (
        reports_cli.reports_main(["save", str(written_report), "--for", str(inspected)]) == 2
    )

    assert _fingerprint(inspected) == before
