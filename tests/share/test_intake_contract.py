"""The intake payload contract, pinned against the Convex receiving end.

`convex/intake.ts` and `convex/schema.ts` are deployed with Convex's own
tooling, so nothing in this repo's CI executes them. What CI *can* do is
refuse to let the two sides of the wire drift apart: these tests parse the
TypeScript source as text and compare the closed question ids, option
values, link rules, and table fields against the constants below.

The constants are stated here rather than imported because the Python
payload model does not exist yet (intake goal G9). When it does, it must
import these same constants from one shared place so the model, this test,
and the TypeScript stay pinned to each other; until then, this file is the
single Python-side statement of the contract.

No network, no Convex tooling, no key, no URL: text in, assertions out
(goal G11).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INTAKE_TS = REPO_ROOT / "convex" / "intake.ts"
SCHEMA_TS = REPO_ROOT / "convex" / "schema.ts"

#: Every question whose answer is a choice from a fixed list, with the full
#: list for each. "not-sure" is always an acceptable answer (goal G2).
OPTION_QUESTIONS: dict[str, tuple[str, ...]] = {
    "dex-installed": ("yes", "no", "not-sure"),
    "customisation": ("barely-touched", "quite-a-bit", "unrecognisable", "not-sure"),
    "first-installed": ("last-week", "last-month", "last-3-months", "at-launch", "not-sure"),
    "last-update": ("last-week", "last-month", "longer-ago", "never", "not-sure"),
    "from-open-source": ("yes", "no-built-it-myself", "not-sure"),
}

#: The one free-text question: the open-source project link. Only allowed
#: when "from-open-source" is answered "yes".
LINK_QUESTION_ID = "project-link"
PROJECT_LINK_MAX_LENGTH = 300
PROJECT_LINK_PREFIX = "https://"

#: The payload fields, and therefore the table's fields. No email — the
#: newsletter signup travels elsewhere by design (goals G9/G10).
PAYLOAD_FIELDS = ("answers", "project_link", "submitted_at", "lens_version")


def _option_questions_in(intake_source: str) -> dict[str, tuple[str, ...]]:
    """The closed lists as `intake.ts` actually states them.

    Parsed from the `OPTION_QUESTIONS` object literal, so an edited,
    added, or removed option value over there changes what this returns
    and fails the comparison — the test cannot pass by matching its own
    expectations against themselves.
    """
    block = re.search(
        r"export const OPTION_QUESTIONS = \{(?P<body>.*?)\} as const;",
        intake_source,
        re.DOTALL,
    )
    assert block is not None, "intake.ts no longer declares OPTION_QUESTIONS"
    entries = re.findall(r'"([^"]+)":\s*\[([^\]]*)\]', block.group("body"))
    assert entries, "the OPTION_QUESTIONS block holds no question entries"
    return {
        question_id: tuple(re.findall(r'"([^"]+)"', raw_options))
        for question_id, raw_options in entries
    }


def test_intake_ts_states_exactly_the_pinned_questions_and_options() -> None:
    parsed = _option_questions_in(INTAKE_TS.read_text(encoding="utf-8"))
    assert parsed == OPTION_QUESTIONS


def test_intake_ts_states_exactly_the_pinned_project_link_rules() -> None:
    source = INTAKE_TS.read_text(encoding="utf-8")
    assert f'export const LINK_QUESTION_ID = "{LINK_QUESTION_ID}";' in source
    assert f"export const PROJECT_LINK_MAX_LENGTH = {PROJECT_LINK_MAX_LENGTH};" in source
    assert f'export const PROJECT_LINK_PREFIX = "{PROJECT_LINK_PREFIX}";' in source
    # The link is conditional on one specific answer, checked in the handler.
    assert 'args.answers["from-open-source"] !== "yes"' in source


def test_schema_ts_carries_exactly_the_payload_fields() -> None:
    source = SCHEMA_TS.read_text(encoding="utf-8")
    table = re.search(
        r"intake_submissions: defineTable\(\{(?P<body>.*?)\}\)",
        source,
        re.DOTALL,
    )
    assert table is not None, "schema.ts no longer defines intake_submissions"
    declared = re.findall(r"^\s*(\w+):\s*v\.", table.group("body"), re.MULTILINE)
    assert tuple(declared) == PAYLOAD_FIELDS


def test_the_receiving_end_gives_an_email_address_no_place_to_land() -> None:
    """Goals G9/G10: email never enters the intake table.

    "email" appears in both files only inside comments saying it is
    excluded; no field, no variable, no code path carries one. A crude
    check on purpose: any new code-level mention must come explain itself
    here.
    """
    for path in (INTAKE_TS, SCHEMA_TS):
        code_lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("//")
        ]
        assert not re.search(r"email", "\n".join(code_lines), re.IGNORECASE), (
            f"{path.name} mentions email outside a comment"
        )


def test_the_mutation_inserts_into_the_declared_table() -> None:
    source = INTAKE_TS.read_text(encoding="utf-8")
    assert 'ctx.db.insert("intake_submissions"' in source


def test_the_engine_and_the_receiving_table_agree_on_every_option() -> None:
    """The Python question table and the Convex validator carry the same lists.

    This is the cross-pin the earlier tests promised: a drift on either side
    fails here, so the payload a run offers always validates on Dave's table.
    """

    from capability_exchange.diagnosis.run import (
        INTAKE_PROJECT_LINK,
        INTAKE_PROJECT_LINK_MAX_LENGTH,
        INTAKE_PROJECT_LINK_PREFIX,
        INTAKE_QUESTION_OPTIONS,
    )

    convex_options = _option_questions_in(INTAKE_TS.read_text(encoding="utf-8"))
    python_options = {
        question: tuple(options)
        for question, options in INTAKE_QUESTION_OPTIONS.items()
    }
    assert convex_options == python_options
    source = INTAKE_TS.read_text(encoding="utf-8")
    assert f'LINK_QUESTION_ID = "{INTAKE_PROJECT_LINK}"' in source
    assert f"PROJECT_LINK_MAX_LENGTH = {INTAKE_PROJECT_LINK_MAX_LENGTH}" in source
    assert f'PROJECT_LINK_PREFIX = "{INTAKE_PROJECT_LINK_PREFIX}"' in source
