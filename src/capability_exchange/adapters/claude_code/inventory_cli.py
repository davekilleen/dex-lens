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
from dataclasses import dataclass, field
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


#: A path segment that marks a full working copy of the folder left behind by
#: an agent run. One real vault held 22 of these — 6.2 GB, and 97% of every
#: file count — and the first inventory of it folded them into a "×32"
#: multiplier instead of naming them. The multiplier was accurate and useless:
#: the person's actual question was "how can I have 6,417 skills?", and the
#: answer was a finding this section now states outright.
_WORKING_COPY_SEGMENTS = frozenset({"worktrees", ".worktrees"})

_DISABLED_NAME = re.compile(r"^_*disabled[-_]", re.IGNORECASE)


def _working_copy_home(relative_path: str) -> str | None:
    """The worktree container a path lives under, or ``None`` for real files."""
    parts = Path(relative_path).parts
    for index, part in enumerate(parts[:-1]):
        if part in _WORKING_COPY_SEGMENTS:
            return "/".join(parts[: index + 1])
    return None


@dataclass
class _Group:
    """One named item and every place a copy of it was captured."""

    #: ``relative path -> canonical path`` for every captured copy.
    copies: dict[str, str] = field(default_factory=dict)
    digests: set[str] = field(default_factory=set)

    @property
    def relative_paths(self) -> list[str]:
        return list(self.copies)

    @property
    def versions(self) -> int:
        return len(self.digests)


def _render(
    snapshot: InspectionSnapshot, root: Path, names: Sequence[str] = ()
) -> str:
    lines = [
        f"# System inventory: {root}",
        "",
    ]
    if names:
        lines.extend(
            [
                f"> **Narrowed.** Listing only items whose name contains "
                f"{', '.join(repr(name) for name in names)}. The counts and the "
                "housekeeping findings below still describe the whole folder, "
                "because that is what they are about.",
                "",
            ]
        )
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
    all_groups: dict[tuple[str, str], _Group] = {}
    working_copies: Counter[str] = Counter()
    working_copy_files = 0
    matched = 0

    for basename, paths in by_name.items():
        if not paths:
            lines.extend([f"## {basename} (none captured)", "", "None captured.", ""])
            continue

        # Collapse copies by name. Worktrees, vendored bundles and plugin
        # caches mean one authored skill can appear dozens of times; listing
        # every copy buries the system's actual shape under its own
        # duplication. Copies are counted and their differing versions are
        # counted separately below — nothing is hidden, only folded.
        grouped: dict[str, _Group] = {}
        for canonical_path in paths:
            entry = snapshot.entry_for(canonical_path)
            label = Path(entry.relative_path).parent.name or entry.relative_path
            group = grouped.setdefault(label, _Group())
            group.copies[entry.relative_path] = canonical_path
            group.digests.add(entry.keyed_digest)
            home = _working_copy_home(entry.relative_path)
            if home is not None:
                working_copies[home] += 1
                working_copy_files += 1

        total_copies += len(paths)
        total_distinct += len(grouped)
        for label, group in grouped.items():
            all_groups[(basename, label)] = group

        # Narrowing hides rows, never facts: the counts in the heading and
        # everything under Housekeeping are still about the whole folder.
        shown = {
            label: group
            for label, group in grouped.items()
            if not names or any(name in label.lower() for name in names)
        }
        matched += len(shown)
        heading = f"## {basename} ({len(grouped)} distinct, {len(paths)} files"
        heading += f", showing {len(shown)} that match)" if names else ")"
        lines.extend([heading, ""])
        for label, group in sorted(shown.items()):
            group = grouped[label]
            copies = f" ×{len(group.copies)}" if len(group.copies) > 1 else ""
            drift = f" ({group.versions} versions)" if group.versions > 1 else ""
            best = _shortest(group.relative_paths)
            description = _describe(snapshot, group.copies[best])
            lines.append(f"- **{label}**{copies}{drift} — {description}")
            lines.append(f"  - `{best}`")
        lines.append("")

    lines.extend(
        _render_housekeeping(
            all_groups,
            working_copies,
            working_copy_files,
            total_copies,
            total_distinct,
        )
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

    lines.extend(_render_how_this_ends())

    if names and not matched:
        # An empty listing is the one output that would be read as a finding:
        # "you have nothing called that". A typo must not be able to say it.
        raise _NothingMatched(names)

    return "\n".join(lines).rstrip() + "\n"


class _NothingMatched(Exception):
    """No declared item's name contained any of the requested fragments."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = tuple(names)
        super().__init__(", ".join(self.names))


def _render_how_this_ends() -> list[str]:
    """The two rules that decide whether this inventory becomes a diagnosis.

    The reader of this file is an assistant partway through a long run, and
    both rules are easiest to drop exactly then: quote what you judge, and
    leave the person something dated they can find again. Saying it here, at
    the point the material arrives, costs four lines and is the last cheap
    place to say it.
    """
    return [
        "## How this ends",
        "",
        "This is material, not a diagnosis. Two things turn it into one:",
        "",
        "- Every judgement carries a line quoted from a file you actually read, "
        "with its path. No quote means the finding is Unknown, and you say so.",
        "- The diagnosis ends as a dated report: write it, then run "
        "`dex-lens reports save <file> --label <name> --for <folder>`. It is "
        "kept outside this folder, and the next run reads it to say what "
        "changed. `dex-lens reports check <file>` says whether it is ready.",
        "",
    ]


def _render_housekeeping(
    all_groups: dict[tuple[str, str], _Group],
    working_copies: Counter[str],
    working_copy_files: int,
    total_copies: int,
    total_distinct: int,
) -> list[str]:
    """The findings about the system itself, stated as findings.

    These are facts the reader cannot see from the folded listing alone, and
    each one is the kind of thing a person mistakes for the size or health of
    their own system. The tool states what it measured; whether anything
    should change about it is the person's call.
    """
    if not total_copies:
        return []

    lines = [
        "## Housekeeping",
        "",
        f"{total_distinct} distinct items across {total_copies} scanned "
        "instruction, skill and settings files. That is the population every "
        "count below describes — not the whole folder. Treat the distinct "
        "count as the size of the system; the rest is copies.",
        "",
    ]

    if working_copies:
        share = round(100 * working_copy_files / total_copies)
        lines.extend(
            [
                "### Leftover working copies",
                "",
                f"{working_copy_files} of the {total_copies} scanned files "
                f"({share}% of the files this inventory covers, not of the "
                "whole folder) sit "
                "inside `worktrees` folders: full working copies of this whole "
                "folder, usually left behind by past agent runs. They inflate "
                "every count and can hide drift. They may hold unmerged work, "
                "so check before removing anything.",
                "",
            ]
        )
        for home, count in working_copies.most_common(10):
            lines.append(f"- `{home}` — {count} files")
        lines.append("")

    # Same name, different bytes. Sometimes deliberate (a per-assistant
    # variant); the finding is that nothing checks which, and the copies
    # will keep drifting until something does.
    drifted = sorted(
        (
            (basename, label, group)
            for (basename, label), group in all_groups.items()
            if group.versions > 1
        ),
        key=lambda item: (-item[2].versions, -len(item[2].copies), item[1]),
    )
    if drifted:
        lines.extend(
            [
                "### Copies that no longer match",
                "",
                f"{len(drifted)} items exist in more than one version under the "
                "same name. Some divergence may be deliberate; the finding is "
                "that nothing here records which, so the copies drift silently.",
                "",
            ]
        )
        for basename, label, group in drifted[:15]:
            lines.append(
                f"- **{label}** ({basename}) — {len(group.copies)} copies "
                f"in {group.versions} versions"
            )
        if len(drifted) > 15:
            lines.append(f"- …and {len(drifted) - 15} more")
        lines.append("")

    disabled = sorted(
        label for (_basename, label) in all_groups if _DISABLED_NAME.match(label)
    )
    if disabled:
        lines.extend(
            [
                "### Switched off by name",
                "",
                "Named as disabled rather than removed. Usually a capability "
                "someone wanted but the implementation fell short, which makes "
                "each one a statement of unmet intent.",
                "",
            ]
        )
        lines.extend(f"- **{label}**" for label in disabled)
        lines.append("")

    return lines


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
        "--names",
        metavar="TEXT[,TEXT...]",
        help=(
            "List only items whose name contains one of these, for a second "
            "look at what a previous report flagged. The counts and the "
            "housekeeping findings still describe the whole folder."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write the inventory to this file as well as printing it.",
    )
    args = parser.parse_args(argv)
    names = tuple(
        fragment.strip().lower() for fragment in (args.names or "").split(",") if fragment.strip()
    )

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

    try:
        rendered = _render(snapshot, root, names)
    except _NothingMatched as nothing:
        print(
            f"dex-lens: nothing in this folder is named like {', '.join(nothing.names)}. "
            "Run without --names rather than reading an empty list as an absence.",
            file=sys.stderr,
        )
        return 1
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"dex-lens: written to {args.out}", file=sys.stderr)
    print(rendered, end="")
    return 0
