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
    "unsigned-draft; founder-approved as drafted on 2026-09-07 — becomes "
    "release truth only when Dex Core signs a catalogue carrying this "
    "capability_families collection"
)

# The founder reviewed the drafted families on 2026-09-07 and approved them
# in full, in his own words ("consider the capability contract all signed by
# me"; "take it from me that I'm happy with everything"). That approval is a
# fact of the review, so it lives here in source: the generator emits it as
# each family's recorded resolution, and a regenerated draft reproduces it
# byte for byte. Signing authority is unchanged — only Dex Core's release
# environment can turn this into release truth.
_FOUNDER_RESOLUTION: dict[str, str] = {
    "resolved_by": "founder",
    "resolved_on": "2026-09-07",
    "decision": (
        "Approved as drafted: member lists and assessments confirmed as "
        "generated, shipping without mcp-tool components until Core publishes "
        "complete tool inventories."
    ),
}

# The approval above is bound to the exact content the founder reviewed: the
# canonical-JSON sha256 of each family payload as it stood in the draft he
# approved on 2026-09-07. A family whose regenerated payload still hashes to
# its pinned digest carries the recorded resolution; a family whose payload
# differs was never seen by the founder, so it gets open TODO(founder) items
# again and no resolution until he re-reviews it (then the new digest is
# pinned here alongside the new resolution).
_FOUNDER_APPROVED_FAMILY_DIGESTS: dict[str, str] = {
    "meeting-follow-through": (
        "sha256:f4bed1f6cbff9f9e86648f2e093569824456a29c76a812b9d7275c4a2fa8979b"
    ),
    "living-people-company-context": (
        "sha256:57d0d639a29bc7bb81778965e32fbb8f5155b4e0b46ade0359b2bf0ea29030f5"
    ),
    "durable-task-continuity": (
        "sha256:cc78a94c2da1331847aae16502ee55531ab6606b72ac53c2e7c83faa1c11ca99"
    ),
    "external-task-interoperability": (
        "sha256:aa3693a47260de8f099a87b394bd207694af3f3ad2fcce88f742d41e696d21de"
    ),
    "connected-work-context": (
        "sha256:3a853f195afa7169cc293209a4b872af6e1b2ae311ed2b357264271667bd7555"
    ),
    "pipedrive-pipeline-continuity": (
        "sha256:e8032ad534e16ae2b48d46caf0df60f63c36e3b2fbc69f554a4ef0180c87243d"
    ),
    "daily-weekly-operating-rhythm": (
        "sha256:87c930c0ed2c417b601d851b28ac4fe6f72ddbb5efc98096906d9788791c0cec"
    ),
    "durable-work-memory": (
        "sha256:579582317dc33ee415777e1ab1bb90491816d361f4901205785ae92089803f31"
    ),
    "proactive-health-and-recovery": (
        "sha256:91a43a6b482c40cb6e2bde0f3c3392893627f27d41a6b0e85b0fb27dc333a7f4"
    ),
    "backup-and-restore-confidence": (
        "sha256:7eed27f40dc574d5dc65dbfc8791a42d13023cc44a152175e6e3cef252ce8805"
    ),
    "safe-change-and-rewind": (
        "sha256:dae78a70e438d20cd284ab600a2e31dd8165b106c90347fe73df563979914416"
    ),
    "capability-discovery-and-adoption": (
        "sha256:e6c88ffefef5a6aab889c9f41193dc06c8baf3d002194faa01d479ef71794893"
    ),
    "privacy-safe-feedback-loop": (
        "sha256:6100954efcb42782d2ea093bc43c7494bd39ea23fa57899dc7894ee4e03a9bcc"
    ),
    "career-growth-evidence": (
        "sha256:e451a2ddaab53e3be0ab7ea7ff4a9ce756c1c19a3a017e7c7cbe5b4041befd84"
    ),
}
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


def _family_content_digest(family_payload: dict[str, object]) -> str:
    """sha256: plus 64 hex characters over the family's canonical JSON."""

    return "sha256:" + hashlib.sha256(_canonical_json_bytes(family_payload)).hexdigest()


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
    family_payload: dict[str, object],
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
    member_basis = _member_basis(tuple(definition["members"]), entries_by_id)
    # The founder's recorded resolution applies only to the content he actually
    # approved: a family whose current payload no longer hashes to its pinned
    # approved digest was never reviewed in this form, so its TODOs reopen and
    # no resolution is attached.
    if _family_content_digest(family_payload) != _FOUNDER_APPROVED_FAMILY_DIGESTS.get(
        family_id
    ):
        return {
            "family_id": family_id,
            "todos": todos,
            "member_basis": member_basis,
        }
    confirmed = [
        "Confirmed(founder): " + todo.removeprefix("TODO(founder): ") for todo in todos
    ]
    return {
        "family_id": family_id,
        "todos": [],
        "resolution": {**_FOUNDER_RESOLUTION, "confirmed": confirmed},
        "member_basis": member_basis,
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
        _founder_review(
            family_id, _FAMILY_DEFINITIONS[family_id], entries_by_id, family
        )
        for family_id, family in zip(WOW_EXPECTATIONS, families, strict=True)
    ]
    reopened = [item["family_id"] for item in review if item["todos"]]

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
    if reopened:
        status = (
            "unsigned-draft; founder review REOPENED for: "
            + ", ".join(reopened)
            + " — these families' content differs from the content the founder "
            "approved on 2026-09-07, so they carry open TODO(founder) items "
            "and no resolution; this draft must not be signed until the "
            "founder re-reviews them"
        )
        membership_note = (
            "The founder's 2026-09-07 approval is digest-bound to the exact "
            "family content he reviewed. The families named in status no "
            "longer match their approved digest, so their review is reopened "
            "with open TODO(founder) items; the remaining families still "
            "carry his recorded resolution."
        )
    else:
        status = _STATUS
        membership_note = (
            "Membership was drafted for founder review and approved as drafted "
            "by the founder on 2026-09-07; each family's founder_review entry "
            "records that resolution. The resolved capability_families "
            "collection may now enter Dex Core's catalogue generator and be "
            "signed."
        )
    return {
        "capability_families": families,
        "derivation_notes": [
            "Derived from the signature-verified Dex catalogue named in "
            "derived_from and the founder-approved family definitions in "
            + _PLAN_PATH + ".",
            membership_note,
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
        "status": status,
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
