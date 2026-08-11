from __future__ import annotations

from tests.diagnosis.conftest import contract, presence_only_envelope

from capability_exchange.catalogue.bridge import (
    rank_capability_shelf,
    render_portable_brief_markdown,
)
from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.diagnosis import assess


def _entry(
    capability_id: str,
    title: str,
    *,
    jobs: tuple[str, ...],
    foundations: tuple[str, ...],
    evidence_level: str,
    host_adapters: tuple[str, ...] = ("claude-code",),
) -> dict:
    return {
        "capability_id": capability_id,
        "title": title,
        "summary": f"{title} strengthens the person's own AI system.",
        "value": f"{title} helps with the selected local job without replacing the system.",
        "jobs": jobs,
        "prerequisites": ("The person has confirmed the matching job.",),
        "trade_offs": ("The brief is guidance only; the person's own AI must adapt it.",),
        "evidence": (
            {
                "level": evidence_level,
                "source": f"{title} release evidence",
                "summary": f"{title} has {evidence_level} catalogue evidence.",
                "limitations": "Lens has not applied this to the person's system.",
            },
        ),
        "compatibility": {
            "host_adapters": host_adapters,
            "foundation_capabilities": foundations,
            "minimum_lens_contract": "0.1.0",
            "platforms": ("macos", "linux", "windows"),
            "needs_hooks": False,
            "needs_mcp": True,
            "host_requirements": ("skills-directory",),
            "limitations": ("Brief only; Lens does not apply changes.",),
        },
        "docs_url": f"https://heydex.ai/catalogue/{capability_id}",
        "since_release": "1.80.0",
        "changed_in": ("1.80.0",),
        "release_provenance": "core-release",
        "portable_brief": {
            "goal": f"Adapt from {title} without copying private data.",
            "method_outline": (
                f"Identify the reusable operating pattern in {title}.",
                "Adapt it inside the person's own confirmed boundaries.",
            ),
            "verification_checklist": (
                "The person can preview the change before using it.",
                "The host AI can prove the outcome without sending data to Dex.",
            ),
            "rollback_advice": "Park this pattern by removing the local command or note.",
            "safety_notes": ("Keep this as advice for the user's own AI, not an action.",),
        },
    }


def _catalogue() -> CatalogueV2:
    return CatalogueV2.model_validate(
        {
            "jobs_taxonomy": (
                {
                    "job_id": "plan-my-work",
                    "label": "Plan my work",
                    "description": "Choose a realistic plan from current commitments.",
                    "confirmed_gap_signals": (
                        "no recent real example demonstrates this outcome",
                    ),
                },
                {
                    "job_id": "maintain-context",
                    "label": "Maintain context",
                    "description": "Keep useful context durable.",
                    "confirmed_gap_signals": ("the system forgets decisions",),
                },
                {
                    "job_id": "keep-human-control",
                    "label": "Keep human control",
                    "description": "Keep approval boundaries visible.",
                    "confirmed_gap_signals": ("approval is unclear",),
                },
                {
                    "job_id": "check-system-health",
                    "label": "Check system health",
                    "description": "Know whether the system is working.",
                    "confirmed_gap_signals": ("health is unknown",),
                },
            ),
            "capabilities": (
                _entry(
                    "durable-memory-boost",
                    "Durable Memory Boost",
                    jobs=("plan-my-work", "maintain-context"),
                    foundations=("durable-memory-provenance",),
                    evidence_level="verified",
                ),
                _entry(
                    "approval-boundary-helper",
                    "Approval Boundary Helper",
                    jobs=("plan-my-work", "keep-human-control"),
                    foundations=("scoped-agency-human-control",),
                    evidence_level="supported",
                ),
                _entry(
                    "health-observer",
                    "Health Observer",
                    jobs=("check-system-health",),
                    foundations=("honest-health-observability",),
                    evidence_level="reported",
                ),
                _entry(
                    "portable-export-helper",
                    "Portable Export Helper",
                    jobs=("maintain-context",),
                    foundations=("ownership-portability",),
                    evidence_level="unknown",
                    host_adapters=("other-host",),
                ),
            ),
            "portable_brief": {
                "format": "markdown",
                "audience": "the person's own AI system",
                "safety_boundary": "Brief only; no automatic adaptation.",
            },
        }
    )


def test_ranked_shelf_scores_the_full_catalogue_without_a_three_item_cap() -> None:
    capability_map = assess([contract("weekly-report")], presence_only_envelope())

    shelf = rank_capability_shelf(
        _catalogue(),
        capability_map,
        host_adapter="claude-code",
        lens_contract_version="0.1.0",
    )

    assert [match.capability_id for match in shelf] == [
        "durable-memory-boost",
        "health-observer",
        "approval-boundary-helper",
        "portable-export-helper",
    ]
    assert len(shelf) == 4
    assert shelf[0].score >= shelf[1].score > shelf[2].score > shelf[3].score
    assert [match.shelf_section for match in shelf] == [
        "picked",
        "picked",
        "picked",
        "picked",
    ]
    assert "weak or gappy for weekly-report" in shelf[0].match_explanation
    assert "matched foundation durable-memory-provenance" in shelf[0].match_explanation
    assert "verified - direct Dex evidence" in shelf[0].evidence_explanation
    assert "unknown" in shelf[0].gap_explanation


def test_picked_shelf_uses_foundation_gaps_when_job_ids_do_not_overlap() -> None:
    capability_map = assess([contract("weekly-report")], presence_only_envelope())

    shelf = rank_capability_shelf(
        _catalogue(),
        capability_map,
        host_adapter="claude-code",
        lens_contract_version="0.1.0",
    )

    picked = [match for match in shelf if match.shelf_section == "picked"]

    assert picked
    assert all("weekly-report" in match.matched_job_ids for match in picked)
    assert all("weekly-report" not in _capability.jobs for _capability in _catalogue().capabilities)
    assert "weekly-report" in picked[0].gap_explanation


def test_match_explanations_use_all_evidence_language_levels() -> None:
    capability_map = assess([contract("weekly-report")], presence_only_envelope())

    shelf = rank_capability_shelf(
        _catalogue(),
        capability_map,
        host_adapter="claude-code",
        lens_contract_version="0.1.0",
    )

    explanations = {match.capability_id: match.evidence_explanation for match in shelf}
    assert "verified - direct Dex evidence" in explanations["durable-memory-boost"]
    assert "supported - Dex-supplied material" in explanations["approval-boundary-helper"]
    assert "reported - Dex team's account" in explanations["health-observer"]
    assert "unknown - not established either way" in explanations["portable-export-helper"]


def test_portable_brief_markdown_is_safe_advice_for_the_selected_capability() -> None:
    catalogue = _catalogue()
    capability = catalogue.capabilities[0].model_copy(
        update={
            "summary": '<script>alert("adapt now")</script>',
        }
    )
    catalogue = catalogue.model_copy(
        update={
            "capabilities": (capability, *catalogue.capabilities[1:]),
        }
    )
    capability_map = assess([contract("weekly-report")], presence_only_envelope())
    shelf = rank_capability_shelf(
        catalogue,
        capability_map,
        host_adapter="claude-code",
        lens_contract_version="0.1.0",
    )

    markdown = render_portable_brief_markdown(
        catalogue,
        capability_map,
        shelf,
        selected_capability_id="durable-memory-boost",
        selected_job_id="weekly-report",
    )

    assert markdown.startswith("# Portable Brief: Durable Memory Boost")
    assert "Audience: the person's own AI system" in markdown
    assert "Brief only; no automatic adaptation." in markdown
    assert (
        "This is guidance only. It does not grant permission to read, write, "
        "send, or install anything."
    ) in markdown
    assert "&lt;script&gt;" in markdown
    assert "<script>" not in markdown
    assert "weak or gappy for weekly-report" in markdown
    assert "verified - direct Dex evidence" in markdown
    assert "### Method Outline" in markdown
    assert "Identify the reusable operating pattern in Durable Memory Boost." in markdown
    assert "### Verification Checklist" in markdown
    assert "The person can preview the change before using it." in markdown
    assert "### Rollback Advice" in markdown
    assert "Park this pattern by removing the local command or note." in markdown
