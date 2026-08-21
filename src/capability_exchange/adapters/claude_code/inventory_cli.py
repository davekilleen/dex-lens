"""``dex-lens inventory``: what a personal AI system is made of, in one page.

The Dex Lens skill has to reason about a whole personal system, and a real one
is large. The reference vault carries 6,263 skill files. No assistant is going
to read those, and it should not try: nearly all of what distinguishes one
skill from another is in its name and its one-line description, and the few
that need reading in full can be read individually once the comparison has
narrowed things down.

So this prints the shape of the system rather than its contents: every
declared artifact, with the name and description it declares for itself. On
the reference vault that is a few hundred kilobytes instead of tens of
megabytes, which is the difference between a skill that works on a real system
and one that only works on a demo.

**On containment.** The browser journey ran its read inside a sandbox that
proved it could not write, execute, or reach the network, because a person had
no reason to trust a program they had just handed their files to. Here the
reader is the person's own assistant, which already has that access; a sandbox
around this one command would prove nothing about the process asking for the
output. What still applies, and is applied, is the rest of the boundary: the
same allowlist, the same credential deny list, secrets redacted before content
is held, and the same honest bounds. This command never writes.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from capability_exchange.adapters.claude_code.allowlist import CanonicalAllowlist
from capability_exchange.adapters.claude_code.contract import (
    CLAUDE_CODE_DIAGNOSTIC_BASENAMES,
    claude_code_contract,
)
from capability_exchange.adapters.claude_code.snapshot import (
    CollectionBounds,
    InspectionSnapshot,
    take_snapshot,
)

__all__ = ["inventory_main"]

#: Frontmatter keys worth surfacing. `description` is the one that carries
#: what a skill is actually for; the rest place it.
_INTERESTING_KEYS = ("name", "description", "when_to_use", "whenToUse")

_FRONTMATTER = re.compile(rb"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_KEY_VALUE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")


def _frontmatter(content: bytes) -> dict[str, str]:
    """Best-effort frontmatter read.

    Deliberately not a YAML parser. This runs over thousands of files written
    by many hands across several years; a strict parser would fail on the
    ragged ones, and a file whose header cannot be read should still appear in
    the inventory as itself rather than vanish from it.
    """
    match = _FRONTMATTER.match(content)
    if match is None:
        return {}
    block = match.group(1).decode("utf-8", "replace")
    found: dict[str, str] = {}
    for line in block.splitlines():
        key_value = _KEY_VALUE.match(line)
        if key_value is None:
            continue
        key, value = key_value.group(1), key_value.group(2).strip()
        if key in _INTERESTING_KEYS and value:
            found[key] = value.strip("\"'")
    return found


def _first_heading(content: bytes) -> str:
    for raw in content.decode("utf-8", "replace").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def _one_line(value: str, limit: int = 240) -> str:
    # Some captured files are not text at all — the reference vault holds a
    # binary snapshot named CLAUDE.md — and a line of mojibake is worse than
    # no line, because the assistant reading it will try to make sense of it.
    # A replacement character means the decode already failed, so the honest
    # answer is that this file declares nothing readable.
    if "�" in value:
        return ""
    printable = "".join(char for char in value if char.isprintable() or char.isspace())
    collapsed = " ".join(printable.split())
    if not collapsed:
        return ""
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _describe(snapshot: InspectionSnapshot, canonical_path: str) -> str:
    content = snapshot.content_of(canonical_path)
    header = _frontmatter(content)
    description = header.get("description") or header.get("when_to_use") or header.get("whenToUse")
    if not description:
        description = _first_heading(content)
    return _one_line(description) if description else "(no description declared)"


def _shortest(paths: Sequence[str]) -> str:
    """The least buried copy, which is nearly always the one being maintained."""
    return min(paths, key=lambda value: (value.count("/"), len(value), value))


def _render(snapshot: InspectionSnapshot, root: Path) -> str:
    lines = [
        f"# System inventory: {root}",
        "",
    ]
    if not snapshot.complete:
        lines.extend(
            [
                "> **Incomplete.** Collection bounds stopped the capture before the "
                "whole approved scope was read. What follows is what was captured, "
                "not necessarily everything there is. Do not describe anything as "
                "absent on the strength of this list.",
                "",
            ]
        )

    by_name: dict[str, list[str]] = {name: [] for name in sorted(CLAUDE_CODE_DIAGNOSTIC_BASENAMES)}
    for canonical_path in snapshot.canonical_paths():
        basename = Path(canonical_path).name
        if basename in by_name:
            by_name[basename].append(canonical_path)

    total_copies = 0
    total_distinct = 0

    for basename, paths in by_name.items():
        if not paths:
            lines.extend([f"## {basename} (none captured)", "", "None captured.", ""])
            continue

        # Collapse copies. Worktrees, vendored bundles and plugin caches mean
        # one authored skill can appear dozens of times; listing each copy
        # buries the system's actual shape under its own duplication. The
        # count is kept because "this exists 41 times" is itself worth
        # knowing, and nothing is hidden — only folded.
        grouped: dict[tuple[str, str], list[str]] = {}
        for canonical_path in paths:
            entry = snapshot.entry_for(canonical_path)
            description = _describe(snapshot, canonical_path)
            identity = (Path(entry.relative_path).parent.name or entry.relative_path, description)
            grouped.setdefault(identity, []).append(entry.relative_path)

        total_copies += len(paths)
        total_distinct += len(grouped)
        lines.extend([f"## {basename} ({len(grouped)} distinct, {len(paths)} files)", ""])
        for (label, description), relatives in sorted(grouped.items()):
            copies = f" ×{len(relatives)}" if len(relatives) > 1 else ""
            shown = description or "(no description declared)"
            lines.append(f"- **{label}**{copies} — {shown}")
            lines.append(f"  - `{_shortest(relatives)}`")
        lines.append("")

    if total_copies:
        lines.extend(
            [
                "## Duplication",
                "",
                f"{total_distinct} distinct items across {total_copies} files. "
                "Copies usually mean worktrees, vendored bundles or plugin caches "
                "rather than genuinely separate capabilities; treat the distinct "
                "count as the size of the system.",
                "",
            ]
        )

    folders = Counter(
        str(Path(snapshot.entry_for(path).relative_path).parent.parent)
        for paths in by_name.values()
        for path in paths
    )
    if folders:
        lines.extend(["## Where they live", ""])
        for folder, count in folders.most_common(25):
            lines.append(f"- `{folder}` — {count}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def inventory_main(argv: list[str] | None = None) -> int:
    """Print the declared shape of one personal AI system."""

    parser = argparse.ArgumentParser(
        prog="dex-lens inventory",
        description=(
            "List the instruction, settings and skill files in a folder with the "
            "description each declares for itself. Reads only; writes nothing."
        ),
    )
    parser.add_argument("root", type=Path, help="The folder to inspect.")
    parser.add_argument(
        "--max-files",
        type=int,
        default=CollectionBounds().max_file_count,
        help="Bound on files captured. Reaching it is reported, never hidden.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write the inventory to this file as well as printing it.",
    )
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"dex-lens: not a folder: {root}", file=sys.stderr)
        return 2

    contract = claude_code_contract((str(root),))
    allowlist = CanonicalAllowlist(contract.read_scope, denied_paths=contract.denied_paths)
    snapshot = take_snapshot(
        allowlist,
        bounds=CollectionBounds(max_file_count=args.max_files),
    )

    rendered = _render(snapshot, root)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"dex-lens: written to {args.out}", file=sys.stderr)
    print(rendered, end="")
    return 0
