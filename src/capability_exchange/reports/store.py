"""Where a diagnosis lives after the conversation that produced it ends.

A second opinion that exists only in a chat window is gone by Friday. The
person cannot show it to anyone, cannot check next month whether they acted on
it, and the next run has nothing to compare against — so it repeats the same
findings as if they were new, which is how a recurring check becomes noise.

So every diagnosis ends as a dated Markdown file, and this module is where it
goes. Two properties matter more than anything else here:

- **It is never written inside the folder being inspected.** The read-only
  guarantee is the product's whole basis for being trusted with someone's
  system; a report dropped into their vault would break it in the most banal
  way possible. The directory is app storage, and
  :func:`require_app_storage_outside_roots` proves the separation rather than
  assuming it.
- **The file names itself by date**, so run N can find run N-1 without anyone
  remembering what it was called.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.catalogue.subscription import (
    default_lens_app_storage,
    require_app_storage_outside_roots,
)

__all__ = [
    "DEFAULT_LABEL",
    "LensReportStore",
    "missing_comparison_with",
    "SavedReport",
    "default_report_directory",
    "missing_report_requirements",
]

#: Sorts chronologically as text, carries no path separators, and survives a
#: case-insensitive filesystem. The trailing ``Z`` says the stamp is UTC, which
#: matters when someone compares two reports written either side of a flight.
_STAMP_FORMAT = "%Y-%m-%dT%H%M%SZ"

_SEPARATOR = "--"
#: Separates a same-second collision counter from the label. Deliberately a
#: character `_slug` can never produce, so a label of its own — "run-2" — is
#: never mistaken for the second report of "run".
_COLLISION = "~"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
#: The label a report is filed under when nobody chose one. Public because
#: the command has to resolve "no label given" to the same word the store
#: would have used, or a saved report and the search for it disagree.
DEFAULT_LABEL = "diagnosis"


def default_report_directory(
    approved_roots: Iterable[Path] = (),
    *,
    environ: dict[str, str] | None = None,
) -> Path:
    """The reports directory, proven to sit outside every approved root.

    Derived from the same app-storage root the catalogue cache uses, so there
    is one place to look for everything Lens keeps and one guard protecting it.
    """
    roots = tuple(approved_roots)
    reports = default_lens_app_storage(roots, environ=environ).parent / "reports"
    require_app_storage_outside_roots(reports, roots)
    return reports


def _slug(value: str) -> str:
    """A filename-safe label, or the default when nothing survives."""
    slug = _SLUG_STRIP.sub("-", value.strip().lower()).strip("-")
    return slug[:60] or DEFAULT_LABEL


def _decoded(path: Path) -> str:
    """The file's text, with bytes that are not UTF-8 shown rather than raised.

    The reports directory is the person's own folder — they are told to keep
    things there and share what is in it — so it will contain files Lens did
    not write, in encodings Lens did not choose. One `latin-1` note used to
    end the whole command in a `UnicodeDecodeError` traceback, taking the
    unsaved diagnosis with it. A file that will not decode is still a file in
    the folder; it is listed with what could be read of it.
    """
    return path.read_text(encoding="utf-8", errors="replace")


def _title_of(markdown: str) -> str:
    """The report's own first heading, so a listing reads like the reports."""
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading:
                return heading
    return ""


@dataclass(frozen=True)
class SavedReport:
    """One report on disk, with the facts a listing needs about it."""

    path: Path
    saved_at: datetime
    label: str
    title: str

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size

    @property
    def is_valid_utf8(self) -> bool:
        """Whether the file decodes cleanly, so a reader can be told when not."""
        try:
            self.path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return False
        except OSError:
            return False
        return True

    def read(self) -> str:
        """The report's text. Undecodable bytes come back as U+FFFD.

        Printing a damaged file with the damage visible beats refusing to
        print it: the person can still see what is there, and nothing on disk
        is touched either way.
        """
        return _decoded(self.path)

    def listing_line(self) -> str:
        """One line a person can read without being told how to read it."""
        when = self.saved_at.strftime("%Y-%m-%d %H:%M UTC")
        title = self.title or "(no title)"
        return f"{when}  {self.label}  {title}"


class LensReportStore:
    """Read and write the dated diagnosis reports for this machine."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def save(
        self,
        markdown: str,
        *,
        label: str = DEFAULT_LABEL,
        now: datetime | None = None,
    ) -> SavedReport:
        """Write one dated report and return where it landed.

        An empty report is refused rather than written. A zero-byte file dated
        today is worse than no file at all: the next run reads it as a baseline
        and concludes that nothing was found last time.
        """
        if not markdown.strip():
            raise ValueError("a report with no content is not a report")

        stamp = (now or datetime.now(UTC)).astimezone(UTC)
        slug = _slug(label)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._free_path(stamp, slug)
        path.write_text(markdown, encoding="utf-8")
        return SavedReport(
            path=path,
            saved_at=stamp.replace(microsecond=0),
            label=slug,
            title=_title_of(markdown),
        )

    def _free_path(self, stamp: datetime, slug: str) -> Path:
        """A path this second's report can have without overwriting another.

        Two runs in the same second are rare and entirely possible, and the
        one thing that must not happen is the second silently replacing the
        first: these files are the only record that the first run happened.
        """
        base = f"{stamp.strftime(_STAMP_FORMAT)}{_SEPARATOR}{slug}"
        candidate = self.directory / f"{base}.md"
        suffix = 2
        while candidate.exists():
            # The counter goes after `~`, never after a hyphen: a hyphen would
            # read back as part of the label, so the second report of the day
            # would be filed under "vault-2" and every lookup by label — the
            # listing, the baseline the next run compares against — would miss
            # it.
            candidate = self.directory / f"{base}{_COLLISION}{suffix}.md"
            suffix += 1
        return candidate

    def list(self, *, label: str | None = None) -> list[SavedReport]:
        """Every report, newest first, optionally narrowed to one label."""
        if not self.directory.is_dir():
            return []
        wanted = _slug(label) if label else None
        reports = [
            report
            for path in sorted(self.directory.glob("*.md"))
            if (report := self._describe(path)) is not None
            and (wanted is None or report.label == wanted)
        ]
        # Two reports can share a second, so the name breaks the tie: the
        # collision counter sorts after the plain name, which makes the newer
        # of the two genuinely the newest.
        return sorted(reports, key=lambda report: (report.saved_at, report.path.name), reverse=True)

    def last(self, *, label: str | None = None) -> SavedReport | None:
        """The most recent report, or ``None`` when this is the first run."""
        reports = self.list(label=label)
        return reports[0] if reports else None

    def _describe(self, path: Path) -> SavedReport | None:
        """One file as a report, dating it from its name where possible.

        A file whose name Lens did not write still gets listed, dated by its
        modification time. Hiding a report because its name is unfamiliar
        would quietly answer "what did the last run say?" with the wrong file,
        and that includes a file whose *contents* are unfamiliar: text in
        another encoding is listed with whatever could be read of its title.

        Nothing in here may raise. This runs on every listing, and on the way
        into `save` — one unreadable file in the folder used to end the
        command in a traceback, with the diagnosis still unwritten. What is
        skipped is only what holds no report at all: a directory or a broken
        link that happens to be named `*.md`.
        """
        stem = path.stem
        stamp_text, _, label = stem.partition(_SEPARATOR)
        label = label.partition(_COLLISION)[0]
        try:
            saved_at = datetime.strptime(stamp_text, _STAMP_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            try:
                modified = path.stat().st_mtime
            except OSError:
                return None
            saved_at = datetime.fromtimestamp(modified, UTC).replace(microsecond=0)
            label = stem
        try:
            title = _title_of(_decoded(path))
        except OSError:
            return None
        return SavedReport(
            path=path,
            saved_at=saved_at,
            label=label or DEFAULT_LABEL,
            title=title,
        )


#: Section headings every report must carry, matched on the phrase rather than
#: the exact line so a report may title its own sections a little differently.
#: "What I read" is the boundary of the diagnosis and "What happens next"
#: is where the person is told nothing changed; a report missing either is
#: not a second opinion, it is an assertion.
_REQUIRED_SECTIONS = (
    ("what i read", "## What I read — what the diagnosis is actually based on"),
    (
        "contradiction",
        "## Contradictions and fragility — what you found when you checked the "
        "rules in the instruction files against the skills",
    ),
    ("what happens next", "## What happens next — including that nothing changed"),
)

#: A search that came back clean. The hunt is the most valuable thing in the
#: diagnosis and the easiest to quietly not do, so "I looked and found nothing"
#: has to be written down: it is a real answer, and silence is not.
#:
#: The statement has to show the check itself, in one sentence: something was
#: checked, the rules were what was checked, the skills were what they were
#: checked against, and nothing conflicted. A bare "found none" used to
#: satisfy this, which let incidental prose ("I found none of the skills that
#: close the loop") stand in for a hunt that never ran — the same disease the
#: Unknown label had before it was pinned to label position.
#: One statement, not one sentence: the gaps stop at a blank line rather than
#: at a full stop, because file names like `CLAUDE.md` put full stops in the
#: middle of the honest wording.
_CLEAN_GAP = r"(?:(?!\n\n)[\s\S]){0,160}?"
_CLEAN_SWEEP = re.compile(
    rf"(?:checked|compared){_CLEAN_GAP}(?:rules?|instructions?){_CLEAN_GAP}skills?"
    rf"{_CLEAN_GAP}(?:no\s+(?:conflicts?|contradictions?)|found\s+none)",
    re.IGNORECASE,
)

#: Headings whose findings are judgements, and therefore need evidence under
#: them. A finding under any of these that quotes nothing has been asserted.
_JUDGEMENT_SECTIONS = (
    "what is strong",
    "the mirror",
    "contradictions",
    "worth borrowing",
)

#: One line of a quotation. Matched line by line rather than over the whole
#: report, because what has to be told apart is a *block* with something in it
#: from a lone ">" character: the second used to satisfy the evidence rule for
#: an entire report.
_QUOTE_LINE = re.compile(r"^\s*>")

#: How far under a quotation its source may sit. The template puts the path on
#: the last line of the block ("> — `<path>`"); people just as often put it on
#: its own line under the block. Both are the same act, so both count.
_CITATION_LINES = 3

#: A file the report says it read. Backticks are how the template writes a
#: path and how people write one anyway, but a bare path counts too — what is
#: being looked for is a name the reader could open for themselves, not a
#: formatting habit.
_PATH_MENTION = re.compile(
    r"""
    <paths?>                                        # the template's placeholder
    | (?:^|[\s`("'\[])[~.]?[/\\][\w~@+.\-]+         # /vault, ~/.claude, ./notes
    | [\w~@+\-][\w~@+.\-/\\]*\.(?:md|markdown|txt|json|jsonl|ya?ml|toml|ini|cfg
        |conf|env|py|js|ts|sh|zsh|bash|rb|go|rs|lock|xml|csv|html?)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: The opening or closing line of a fenced code block.
_FENCE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,})")

#: An Unknown *label*, not the word in passing. It has to sit where the report
#: template puts a label — at the end of the finding's heading, or on a line of
#: its own — because waiving the evidence requirement on any sentence
#: containing "unknown" let "it calls an unknown tool" pass an unquoted claim.
_UNKNOWN_LABEL = re.compile(
    r"(?:[-—–:|]\s*|^)Unknown\b\.?\s*$", re.IGNORECASE | re.MULTILINE
)
#: Every heading a report can carry under its title. Levels below "###" are
#: not decoration: "#### Your router skill is flawless" is the same judgement
#: as the "###" version of it, and matching only two levels meant the deeper
#: one was checked by nothing at all.
_HEADING = re.compile(r"^(#{2,6})\s+(.*?)\s*$", re.MULTILINE)


def _without_code_fences(markdown: str) -> str:
    """The report's own words: everything outside a fenced code block.

    A fence is quoted material, not a claim. A report that pasted the template
    it was supposed to fill in — "here is what I was going to write" — used to
    satisfy every heading and every quotation from inside the fence while its
    own prose said it had done nothing, which is the laziest possible
    diagnosis passing the check that exists to catch it.

    An unterminated fence swallows the rest of the file. That is the
    fail-closed reading: text the writer marked as a sample is not the
    writer's own claim, whether or not they closed the fence.
    """
    kept: list[str] = []
    closing: str | None = None
    for line in markdown.splitlines():
        fence = _FENCE.match(line)
        if closing is None:
            if fence is not None:
                closing = fence.group("fence")[0] * 3
                continue
            kept.append(line)
        elif fence is not None and fence.group("fence").startswith(closing):
            closing = None
    return "\n".join(kept)


def _quotations(markdown: str) -> list[tuple[str, str]]:
    """Every "> " block in this passage, paired with the lines that cite it.

    The pair is (what was quoted, the block plus the few lines under it), so
    the two halves of the rule — that something was quoted, and that its path
    is given — can be asked separately.
    """
    lines = markdown.splitlines()
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        if _QUOTE_LINE.match(lines[index]) is None:
            index += 1
            continue
        start = index
        while index < len(lines) and _QUOTE_LINE.match(lines[index]) is not None:
            index += 1
        block = lines[start:index]
        quoted = "\n".join(line.lstrip().removeprefix(">") for line in block)
        citation = "\n".join(block + lines[index : index + _CITATION_LINES])
        blocks.append((quoted, citation))
    return blocks


def _shows_evidence(markdown: str) -> bool:
    """Whether this passage carries a quotation with a source beside it.

    Both halves are required, because either alone is satisfied by a report
    that read nothing: a lone ">" is not a quotation, and a line with no path
    under it is not something the person can go and check.
    """
    return any(
        quoted.strip() and _PATH_MENTION.search(citation) is not None
        for quoted, citation in _quotations(markdown)
    )


def missing_comparison_with(previous: SavedReport | None, markdown: str) -> str | None:
    """Why this report cannot stand as a second look, if it cannot.

    A recurring diagnosis that restates the same findings every time is how a
    person learns to stop reading it. Once there is a previous report, the new
    one has to account for it — even if the account is "nothing has changed" —
    so this is checked rather than hoped for.
    """
    if previous is None:
        return None
    titles = _section_titles(_without_code_fences(markdown))
    if any("since" in title.lower() for title in titles):
        return None
    when = previous.saved_at.strftime("%Y-%m-%d")
    return (
        f"say what has changed: the last look at this system was on {when} "
        f"({previous.path}). Add a section whose heading says 'since' - what is "
        "fixed, what still stands, what is new. 'Nothing has changed since "
        "then' is a complete answer; leaving it out is not."
    )


def _section_titles(markdown: str) -> list[str]:
    return [match.group(2) for match in _HEADING.finditer(markdown)]


def missing_report_requirements(markdown: str) -> list[str]:
    """What this report would have to add before it could be saved.

    The rule the whole report format exists to enforce is *no quote, no
    claim*, and a rule enforced only by prose in a skill file is a rule that
    holds until the run is long and the assistant is tired. So it is checked
    here, at the moment the report is written, where skipping it is not an
    option that exists.

    What is checked is structural, never the wording: that the report says
    what it read and what happens next, that at least one claim is backed by
    a quotation with the path it came from, that no scored finding stands
    with neither a quotation nor an honest "Unknown" under it, and that a
    shortlist is accompanied by the rejections that prove a comparison
    happened. Each returned line names the fix, because an error that only
    says "invalid" gets worked around rather than fixed.

    Everything is read from the report's own prose — fenced code blocks are
    removed first, so a pasted template cannot answer for a diagnosis that
    was never done.
    """
    prose = _without_code_fences(markdown)
    lowered = prose.lower()
    # A required section is a "##" heading, not a phrase somewhere in prose.
    # "No contradictions found" mentioned under The Mirror used to satisfy the
    # contradictions requirement while the dedicated section — and with it the
    # content check that the hunt actually ran — was skipped entirely.
    problems = [
        f"add a section: {advice}"
        for phrase, advice in _REQUIRED_SECTIONS
        if not _has_section_heading(prose, phrase)
    ]

    if not _shows_evidence(prose):
        problems.append(
            "quote something: every judgement carries a line copied from a file "
            'you read, as a "> " block with the path under it. A report with no '
            "quotations has not shown its work."
        )

    problems.extend(_findings_without_evidence(prose))
    problems.extend(_contradiction_hunt_not_shown(prose))

    if "worth borrowing" in lowered and not _has_section_heading(
        prose, "considered and rejected"
    ):
        problems.append(
            "add a section: ## Considered and rejected — one line each for what "
            "you looked at and ruled out. A shortlist with no visible rejections "
            "cannot be told apart from one that never compared."
        )
    return problems


def _has_section_heading(markdown: str, phrase: str) -> bool:
    """Whether a "##" heading carries this phrase.

    The looser check — the phrase anywhere in the report — let a passing
    mention satisfy a structural requirement, and the section's own content
    check never ran because there was no heading for it to find.
    """
    return any(
        heading.group(1) == "##" and phrase in heading.group(2).lower()
        for heading in _HEADING.finditer(markdown)
    )


def _clean_sweep_shown(body: str) -> bool:
    """Whether a clean result names what was actually checked.

    The words alone cannot carry this. They are a bag of words over a short
    window, and prose saying the exact opposite — "I have not checked
    anything. I would have compared the rules to your skills, but found none
    of the time needed" — matches them all. No widening fixes that: a
    sentence about a hunt reads like a hunt.

    What a hunt that ran can do, and a sentence about one cannot, is name a
    file it read. So that is what is required.
    """
    match = _CLEAN_SWEEP.search(body)
    return match is not None and _PATH_MENTION.search(match.group(0)) is not None


def _contradiction_hunt_not_shown(markdown: str) -> list[str]:
    """Whether the contradictions section shows a hunt or only a heading.

    An empty heading is the failure mode this guards: the section survives,
    the search never happened, and the reader cannot tell the difference. Two
    things count as having done it — a finding with the rule and the thing
    breaking it both quoted, or the plain statement that the rules in a named
    file were checked and nothing conflicted.
    """
    headings = list(_HEADING.finditer(markdown))
    for index, heading in enumerate(headings):
        if heading.group(1) != "##" or "contradiction" not in heading.group(2).lower():
            continue
        # The section runs to the next "##"; the findings inside it are part
        # of it, which is where the quotations live.
        following = [later for later in headings[index + 1 :] if later.group(1) == "##"]
        end = following[0].start() if following else len(markdown)
        body = markdown[heading.end() : end]
        if _shows_evidence(body) or _clean_sweep_shown(body):
            return []
        return [
            "show the contradiction hunt: under the contradictions heading, "
            "either quote a rule from an instruction file and the skill that "
            "breaks it, each with its path, or say plainly that you checked "
            "the rules — naming the instruction file you read — against the "
            "skills and found no conflicts. Finding none is a real answer; an "
            "empty heading is not."
        ]
    return []


def _span_end(markdown: str, headings: list[re.Match[str]], index: int) -> int:
    """Where a heading's own passage ends: at the next heading as shallow.

    A finding owns whatever is nested under it, so a "###" finding whose
    evidence sits under a "####" of its own still counts as evidenced.
    """
    level = len(headings[index].group(1))
    for later in headings[index + 1 :]:
        if len(later.group(1)) <= level:
            return later.start()
    return len(markdown)


def _is_finding(level: str, section: str, headings: list[re.Match[str]], index: int) -> bool:
    """Whether this heading makes a judgement that needs evidence under it.

    Anything under a section heading is a finding, at any depth. A section
    heading is one too when it has no findings beneath it: "## What is strong:
    your router skill is flawless" is the same claim as the "###" version, and
    treating every "##" as a container let the judgement be made in the
    heading with nothing but praise underneath.

    The contradictions section is left to :func:`_contradiction_hunt_not_shown`,
    which accepts a clean sweep where there is nothing to quote.
    """
    if not any(phrase in section for phrase in _JUDGEMENT_SECTIONS):
        return False
    if level != "##":
        return True
    if "contradiction" in section:
        return False
    following = headings[index + 1 :]
    return not following or following[0].group(1) == "##"


def _findings_without_evidence(markdown: str) -> list[str]:
    """Every scored finding that carries neither a quotation nor an Unknown.

    Sections are walked by heading rather than parsed, because a report is
    prose and the check must survive someone writing it slightly differently.
    A finding that honestly says Unknown is fine — that is the rubric working,
    not failing.
    """
    headings = list(_HEADING.finditer(markdown))
    problems: list[str] = []
    section = ""
    for index, heading in enumerate(headings):
        level, title = heading.group(1), heading.group(2)
        if level == "##":
            section = title.lower()
        if not _is_finding(level, section, headings, index):
            continue
        body = markdown[heading.end() : _span_end(markdown, headings, index)]
        # The label often sits in the heading ("### X - Unknown"), so the
        # heading counts as part of the finding for this check.
        if _shows_evidence(body) or _UNKNOWN_LABEL.search(f"{title}\n{body}"):
            continue
        problems.append(
            f"back up '{title}' with a quoted line and its path, or "
            "label it Unknown. It is scored under a heading that requires evidence."
        )
    return problems
