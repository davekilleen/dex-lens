#!/usr/bin/env python3
"""Derive the unsigned significant-family contract draft from signed truth.

The release-distance dimension of a Lens diagnosis stays disabled until the
verified catalogue carries a signed ``capability_families`` collection.  This
script derives that payload — the contract the founder reviews and signs — from
two sources only:

1. the signature-verified Dex catalogue (default: the packaged reference), for
   every capability identity, class, availability and job it cites; and
2. the founder-approved family definitions in
   ``docs/superpowers/plans/2026-09-01-dex-lens-significant-capability-coverage-gate.md``,
   for the fourteen family identities, titles and outcomes.

Family membership needs judgment the data cannot fully supply, so the draft
encodes that judgment transparently (the ``_FAMILY_DEFINITIONS`` table below),
grounds every member in its signed facts (``member_basis``), and attaches
explicit ``TODO(founder)`` items instead of presenting the draft as settled.

The output is deterministic, unsigned, and validated against the exact source
catalogue with the same ``CatalogueV2`` model the Lens verifier applies to
signed bytes.  Nothing here signs, publishes, or touches key material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from capability_exchange.catalogue.v2 import (  # noqa: E402
    CatalogueV2,
    CatalogueVerificationError,
    KeyRing,
    SignedCatalogueEnvelopeV2,
    default_keyring,
    verify_catalogue_envelope_for_stale_display,
)
from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS  # noqa: E402

REFERENCE_PATH = (
    SRC_ROOT / "capability_exchange" / "skill" / "dex-lens" / "dex-capabilities.json"
)
DRAFT_PATH = REPO_ROOT / "release" / "significant-family-contract.draft.json"
_PLAN_PATH = (
    "docs/superpowers/plans/"
    "2026-09-01-dex-lens-significant-capability-coverage-gate.md"
)
_STATUS = (
    "unsigned-draft; not release truth until the founder resolves every "
    "TODO(founder) item and Dex Core signs a catalogue carrying the resolved "
    "capability_families collection"
)
_MANUAL_ONLY_FAMILY = "privacy-safe-feedback-loop"
_MANUAL_ONLY_REASON = (
    "A person must confirm that no private work leaves the machine before "
    "feedback is shared."
)


class FamilyContractDraftError(ValueError):
    """The draft cannot be derived honestly from the given source."""


# One entry per Wow Gate expectation family. ``title`` and ``outcome`` restate
# the founder-approved definitions in the coverage-gate plan; ``members`` is
# the draft judgment this script surfaces for founder review — every id must
# exist in the signed source catalogue or generation fails.
_FAMILY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "meeting-follow-through": {
        "title": "Meeting follow-through",
        "outcome": "Meetings become notes, people context and tracked follow-up.",
        "members": (
            "dex-granola-mcp",
            "dex-meeting-intel",
            "granola-setup",
            "meeting-closeout",
            "meeting-prep",
            "process-meetings",
        ),
    },
    "living-people-company-context": {
        "title": "Living people and company context",
        "outcome": (
            "People and company pages are created, refreshed and connected over time."
        ),
        "members": (
            "entity-temperature-engine",
            "relationship-radar",
        ),
    },
    "durable-task-continuity": {
        "title": "Durable task continuity",
        "outcome": (
            "Tasks can be captured from several places and completion returns to "
            "linked surfaces."
        ),
        "members": (
            "commitments",
            "delegate-check",
            "dex-work-mcp",
            "proactive-promise-engine",
            "triage",
        ),
    },
    "external-task-interoperability": {
        "title": "External task interoperability",
        "outcome": (
            "Todoist, Things and Trello can exchange tasks on request without "
            "pretending background polling exists."
        ),
        "members": (
            "things-setup",
            "todoist-setup",
            "trello-setup",
        ),
    },
    "connected-work-context": {
        "title": "Connected work context",
        "outcome": (
            "Google, Teams, Zoom, Atlassian and Apple Mail can inform plans, "
            "preparation and reviews when explicitly connected."
        ),
        "members": (
            "apple-mail-setup",
            "atlassian-setup",
            "calendar-setup",
            "dex-calendar-mcp",
            "google-workspace-setup",
            "ms-teams-setup",
            "zoom-setup",
        ),
    },
    "pipedrive-pipeline-continuity": {
        "title": "Pipedrive pipeline continuity",
        "outcome": (
            "Live pipeline context informs local work; external writes stay "
            "previewed and confirmed."
        ),
        "members": (
            "dex-pipedrive-mcp",
            "pipedrive-setup",
            "pipeline-sync",
        ),
    },
    "daily-weekly-operating-rhythm": {
        "title": "Daily and weekly operating rhythm",
        "outcome": (
            "Planning, review and reflection form one repeatable operating cadence."
        ),
        "members": (
            "daily-plan",
            "daily-review",
            "week-plan",
            "week-review",
            "weekly-reflection",
        ),
    },
    "durable-work-memory": {
        "title": "Durable work memory",
        "outcome": (
            "Sourced decisions, commitments, context and patterns remain available "
            "across sessions."
        ),
        "members": (
            "decision-log",
            "dex-session-memory",
            "enable-semantic-search",
            "journal",
            "save-insight",
        ),
    },
    "proactive-health-and-recovery": {
        "title": "Proactive health and recovery",
        "outcome": (
            "Doctor and scheduled checks distinguish healthy, off, broken and "
            "unknown, then use bounded repair paths."
        ),
        "members": (
            "dex-doctor",
            "dex-smoke-nightly",
        ),
    },
    "backup-and-restore-confidence": {
        "title": "Backup and restore confidence",
        "outcome": (
            "Backups are created and recovery is proved by a safe restore rehearsal."
        ),
        "members": (
            "backup-now",
            "backup-restore",
            "backup-setup",
            "dex-vault-backup",
        ),
    },
    "safe-change-and-rewind": {
        "title": "Safe change and rewind",
        "outcome": "Changes are previewed, verified, receipted and reversible.",
        "members": (
            "dex-rollback",
            "dex-update",
            "diff-adopt",
            "diff-adopt-profile",
            "diff-generate",
            "diff-list",
            "diff-profile",
            "diff-remove",
        ),
    },
    "capability-discovery-and-adoption": {
        "title": "Capability discovery and adoption",
        "outcome": (
            "Useful methods can be discovered, reviewed, adopted and created "
            "through the safe lifecycle."
        ),
        "members": (
            "create-mcp",
            "create-skill",
            "dex-add-mcp",
            "dex-whats-new",
            "integrate-mcp",
            "manage-capabilities",
            "skill-score",
        ),
    },
    "privacy-safe-feedback-loop": {
        "title": "Privacy-safe feedback loop",
        "outcome": (
            "A problem can become a minimal report and a returned answer or fix "
            "without exporting private work."
        ),
        "members": ("feedback",),
    },
    "career-growth-evidence": {
        "title": "Career growth evidence",
        "outcome": (
            "Career and Resume tools turn consented evidence into development and "
            "application support without inventing claims."
        ),
        "members": (
            "career-coach",
            "career-setup",
            "dex-career-mcp",
            "dex-resume-mcp",
            "resume-builder",
        ),
    },
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _load_source_envelope_json(input_path: Path) -> str:
    """Accept either a raw signed envelope or the packaged reference wrapper."""

    try:
        parsed = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FamilyContractDraftError(f"cannot read source catalogue {input_path}: {exc}") from exc
    if isinstance(parsed, dict) and "signed_catalogue" in parsed:
        parsed = parsed["signed_catalogue"]
    return _canonical_json_bytes(parsed).decode("utf-8")


def _assessment_for(family_id: str) -> dict[str, object]:
    if family_id == _MANUAL_ONLY_FAMILY:
        return {"mode": "manual-only", "reason": _MANUAL_ONLY_REASON}
    return {"mode": "automatic", "profile": "catalogue"}


def _family_payload(
    family_id: str,
    definition: dict[str, Any],
    entries_by_id: dict[str, Any],
) -> dict[str, object]:
    members = tuple(definition["members"])
    missing = sorted(set(members) - set(entries_by_id))
    if missing:
        raise FamilyContractDraftError(
            f"family {family_id!r} cites capability id(s) absent from the signed "
            "source catalogue: " + ", ".join(missing)
        )
    jobs = sorted({job for member in members for job in entries_by_id[member].jobs})
    return {
        "family_id": family_id,
        "title": definition["title"],
        "outcome": definition["outcome"],
        "jobs": jobs,
        "aliases": [],
        "member_capability_ids": list(members),
        "components": [
            {"component_type": "capability", "capability_id": member}
            for member in members
        ],
        "assessment": _assessment_for(family_id),
    }


def _member_basis(members: tuple[str, ...], entries_by_id: dict[str, Any]) -> list[dict]:
    basis: list[dict[str, object]] = []
    for member in members:
        entry = entries_by_id[member]
        basis.append(
            {
                "capability_id": member,
                "capability_class": getattr(entry, "capability_class", "active-skill"),
                "availability": getattr(entry, "availability", "active"),
                "jobs": sorted(entry.jobs),
                "title": entry.title,
            }
        )
    return basis


def _founder_review(
    family_id: str,
    definition: dict[str, Any],
    entries_by_id: dict[str, Any],
) -> dict[str, object]:
    todos = [
        (
            f"TODO(founder): confirm the member list for '{family_id}'. It is a "
            f"draft derived from the family definition in {_PLAN_PATH} and each "
            "member's signed title/jobs, not from a Core-owned registry."
        ),
        (
            "TODO(founder): confirm the assessment for this family "
            "(draft: "
            + json.dumps(_assessment_for(family_id), sort_keys=True)
            + "); a stronger detector profile may fit better."
        ),
    ]
    if any(
        getattr(entries_by_id[member], "capability_class", "active-skill") == "mcp-server"
        for member in definition["members"]
    ):
        todos.append(
            "TODO(founder): add exact mcp-tool components for the MCP members once "
            "Core publishes complete tool inventories; the current signed "
            "catalogue's MCP inventories are sampled, so tool-level components "
            "would fail verification today."
        )
    return {
        "family_id": family_id,
        "todos": todos,
        "member_basis": _member_basis(tuple(definition["members"]), entries_by_id),
    }


def build_draft(raw_envelope_json: str, *, keyring: KeyRing) -> dict[str, object]:
    """Verify the source and derive the complete, validated, unsigned draft."""

    verified: SignedCatalogueEnvelopeV2 = verify_catalogue_envelope_for_stale_display(
        raw_envelope_json, keyring=keyring
    )
    if set(_FAMILY_DEFINITIONS) != set(WOW_EXPECTATIONS):
        raise FamilyContractDraftError(
            "family definitions have drifted from the Wow Gate expectation manifest"
        )
    entries_by_id = {
        entry.capability_id: entry for entry in verified.catalogue.capabilities
    }
    families = [
        _family_payload(family_id, _FAMILY_DEFINITIONS[family_id], entries_by_id)
        for family_id in WOW_EXPECTATIONS
    ]
    review = [
        _founder_review(family_id, _FAMILY_DEFINITIONS[family_id], entries_by_id)
        for family_id in WOW_EXPECTATIONS
    ]

    # Prove the drafted payload closes against the exact source catalogue with
    # the same model the Lens verifier applies to signed bytes. A draft that
    # fails here would also fail verification after signing, so it is refused
    # now rather than after the founder's review.
    catalogue_payload = verified.catalogue.model_dump(mode="json")
    catalogue_payload["capability_families"] = families
    try:
        combined = CatalogueV2.model_validate(catalogue_payload)
    except ValueError as exc:
        raise FamilyContractDraftError(
            f"drafted families do not close against the source catalogue: {exc}"
        ) from exc
    if not combined.capability_families:
        raise FamilyContractDraftError("drafted contract carries no families")

    canonical_source = _canonical_json_bytes(json.loads(raw_envelope_json))
    return {
        "capability_families": families,
        "derivation_notes": [
            "Derived from the signature-verified Dex catalogue named in "
            "derived_from and the founder-approved family definitions in "
            + _PLAN_PATH + ".",
            "Membership is drafted judgment for founder review; every "
            "TODO(founder) item in founder_review must be resolved before the "
            "resolved capability_families collection enters Dex Core's "
            "catalogue generator and is signed.",
            "This file is never signed and never published; only Dex Core "
            "signs catalogue bytes.",
        ],
        "derived_from": {
            "canonical_sha256": hashlib.sha256(canonical_source).hexdigest(),
            "catalog_version": verified.metadata.catalog_version,
            "core_release": verified.metadata.core_release,
            "key_id": verified.metadata.key_id,
            "produced_at": verified.metadata.produced_at.isoformat().replace(
                "+00:00", "Z"
            ),
        },
        "draft_contract": "dex-lens-significant-family-contract-draft",
        "draft_version": 1,
        "founder_review": review,
        "status": _STATUS,
    }


def render_draft(raw_envelope_json: str, *, keyring: KeyRing) -> bytes:
    draft = build_draft(raw_envelope_json, keyring=keyring)
    return (json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=REFERENCE_PATH,
        help=(
            "signed Dex catalogue envelope, or the packaged reference wrapper "
            f"(default: {REFERENCE_PATH})"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DRAFT_PATH,
        help=f"draft contract path (default: {DRAFT_PATH})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless output is the exact generated bytes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        raw = _load_source_envelope_json(args.input)
        generated = render_draft(raw, keyring=default_keyring())
        if args.check:
            current = args.output.read_bytes()
            if current != generated:
                raise FamilyContractDraftError(
                    f"{args.output} has drifted; regenerate it with this script"
                )
            print(f"significant-family contract draft is exact generated output: {args.output}")
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(generated)
        print(f"generated unsigned significant-family contract draft: {args.output}")
        return 0
    except (
        FamilyContractDraftError,
        CatalogueVerificationError,
        OSError,
        ValueError,
    ) as exc:
        print(f"significant-family contract draft refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
