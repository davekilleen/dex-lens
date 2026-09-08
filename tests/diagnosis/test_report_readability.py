"""What the first person to read a real report actually sees.

The first person-mimicking run against a realistic stale vault (2026-09-08,
RISK-FIRST-READ-REPORT-VOICE-2026-09-08) closed correctly and produced a
report that was true and hard to read: the reverse-direction section claimed
personal authorship over a list that includes Dex's own retired stock and
rendered a boilerplate row per item; the one grounded recommendation appeared
three times verbatim; one manual-only family flipped the whole coverage story
into the confession voice; the installed welcome listed two commands twice;
and the diagnosis help never named the mandatory intake step.

Every fixture is invented. Each test was observed to fail on the tree
without the change it pins.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.diagnosis.test_intake import DEX_ANSWERS, NO_DEX_ANSWERS, _at_scope_approved
from tests.diagnosis.test_real_comparer_guided_run import RealComparerHarness
from tests.diagnosis.test_report_model import run_identity
from tests.diagnosis.test_significant_family_assessment import (
    _automation,
    _family,
    _job,
    _mcp,
    _parked_engine,
    _skill,
)
from tests.evals.stale_install_fixture import write_stale_install

from capability_exchange.catalogue.v2 import CatalogueV2
from capability_exchange.concierge import cli as concierge_cli
from capability_exchange.diagnosis import cli as diagnosis_cli
from capability_exchange.diagnosis.comparison import (
    Disposition,
    insights_from_proposals,
)
from capability_exchange.diagnosis.defaults import (
    CachedCatalogueLoader,
    UnknownUntilProposedComparer,
)
from capability_exchange.diagnosis.expectations import WOW_EXPECTATIONS
from capability_exchange.diagnosis.observations import (
    ConfigurationState,
    EvidenceFingerprint,
    HealthState,
    Observation,
    ObservationKind,
    RuntimeState,
    SafeAttribute,
)
from capability_exchange.diagnosis.report import (
    ReportModel,
    canonical_ledger_digest,
)
from capability_exchange.diagnosis.run import DiagnosisStage
from capability_exchange.diagnosis.specialists import ProposalKind, ValidatedProposal
from capability_exchange.diagnosis.work import AnalysisMode
from capability_exchange.evidence import EvidenceItem

_NOW = datetime(2026, 9, 8, 11, 0, tzinfo=UTC)

#: One signed member per area. The health member's name is one the
#: stale-install fixture ships, so its lineage decides whether the name
#: counts; every other member matches nothing local.
HEALTH_FAMILY = "proactive-health-and-recovery"
HEALTH_MEMBER = "vault-doctor"
MANUAL_FAMILY = "privacy-safe-feedback-loop"


def _all_areas_catalogue(
    *, manual_family: bool = False, member_since: str = "1.80.0"
) -> CatalogueV2:
    capabilities = [_skill(HEALTH_MEMBER), _mcp(), _automation(), _parked_engine()]
    capabilities[0]["since_release"] = member_since
    families = [
        _family(
            HEALTH_FAMILY,
            profile="catalogue",
            members=[HEALTH_MEMBER],
            components=[
                {"component_type": "capability", "capability_id": HEALTH_MEMBER}
            ],
        )
    ]
    for family_id in WOW_EXPECTATIONS:
        if family_id == HEALTH_FAMILY:
            continue
        member = f"{family_id}-member"
        entry = _skill(member)
        entry["since_release"] = "1.1.0"
        capabilities.append(entry)
        families.append(
            _family(
                family_id,
                profile=None if manual_family and family_id == MANUAL_FAMILY else "catalogue",
                members=[member],
                components=[
                    {"component_type": "capability", "capability_id": member}
                ],
            )
        )
    return CatalogueV2.model_validate(
        {
            "jobs_taxonomy": [_job()],
            "capabilities": capabilities,
            "capability_aliases": [],
            "capability_families": families,
            "portable_brief": {
                "format": "markdown",
                "audience": "the person's own AI system",
                "safety_boundary": "guidance only; it changes nothing",
            },
        }
    )


def _closed_report(
    tmp_path: Path,
    answers: dict[str, str],
    *,
    dex_present: bool = True,
    manual_family: bool = False,
    core_release: str | None = "v1.97.0",
) -> str:
    fingerprint = write_stale_install(tmp_path / "vault", dex_present=dex_present)
    harness = RealComparerHarness(
        tmp_path,
        catalogue=_all_areas_catalogue(manual_family=manual_family),
        fingerprint=fingerprint,
        core_release=core_release,
    )
    run_id = _at_scope_approved(harness, AnalysisMode.INVENTORY_ONLY)
    harness.engine.intake(run_id, answers)
    view = harness.engine.status(run_id)
    while view.stage is not DiagnosisStage.CLOSED:
        view = harness.engine.advance(run_id)
    return harness.engine.result(run_id).render_markdown()


def _section(markdown: str, heading: str) -> str:
    if heading not in markdown:
        return ""
    return markdown.split(heading, 1)[1].split("\n## ", 1)[0]


# --- the reverse direction claims possession, never personal authorship ---------


def test_unique_to_you_claims_possession_not_personal_authorship(
    tmp_path: Path,
) -> None:
    """Founder decision, 2026-09-08 (AGENTS.md F7 annotation): items the
    current catalogue does not name stay in the reverse direction, but the
    report may only claim they are part of the person's setup — never that
    the person wrote them, which on a stale install praises retired stock."""

    rendered = _closed_report(tmp_path, DEX_ANSWERS)
    section = _section(rendered, "## Unique to you")

    assert section, rendered
    assert "yours alone" not in section
    assert "match nothing in today's signed Dex catalogue" in section


def test_a_behind_install_carries_the_older_dex_caveat(tmp_path: Path) -> None:
    rendered = _closed_report(tmp_path, DEX_ANSWERS)
    section = _section(rendered, "## Unique to you")

    assert "may have shipped with the older Dex" in section


def test_a_no_dex_run_carries_no_older_dex_caveat(tmp_path: Path) -> None:
    rendered = _closed_report(
        tmp_path, NO_DEX_ANSWERS, dex_present=False, core_release=None
    )
    section = _section(rendered, "## Unique to you")

    assert "older Dex" not in section


def test_unique_to_you_renders_one_line_per_capability_type(tmp_path: Path) -> None:
    """A hundred identical boilerplate rows is a wall, not a map. Items are
    grouped by what they are, with every identity still named."""

    rendered = _closed_report(tmp_path, DEX_ANSWERS)
    section = _section(rendered, "## Unique to you")
    bullet_lines = [line for line in section.splitlines() if line.startswith("- ")]

    assert bullet_lines
    for line in bullet_lines:
        assert re.match(r"- [a-z][a-z-]*s? \(\d+\): `", line), line
    assert "Evidence: 1 approved observation" not in section
    # Grouping loses no identity: a known authored skill is still named.
    assert "`deal-brief-mine`" in section


# --- one finding renders once ---------------------------------------------------


def test_a_recommendation_is_not_double_counted_as_a_workflow_connection() -> None:
    proposal = ValidatedProposal(
        kind=ProposalKind.RECOMMENDATION,
        catalogue_id="skill-score",
        capability_id="skill-score",
        disposition=Disposition.WORTH_BORROWING,
        evidence_ids=("file-token:one", "file-token:two"),
        reason="Two copies of one skill differ; grade them before consolidating.",
    )

    strengths, lessons, connections = insights_from_proposals((proposal,))

    assert strengths == ()
    assert lessons == ()
    assert connections == ()


def _skill_copy_ledger():
    payload = _all_areas_catalogue().model_dump(mode="json")
    payload["capabilities"][0]["capability_id"] = "skill-score"
    payload["capabilities"][0]["title"] = "Skill grading"
    payload["capability_families"][0]["member_capability_ids"] = ["skill-score"]
    payload["capability_families"][0]["components"] = [
        {"component_type": "capability", "capability_id": "skill-score"}
    ]
    catalogue = CatalogueV2.model_validate(payload)
    store = SimpleNamespace(
        load_last_verified=lambda **_kwargs: SimpleNamespace(
            catalogue=catalogue,
            metadata=SimpleNamespace(catalog_version=7, core_release=None),
            _signed_json="invented-signed-catalogue",
        )
    )
    fingerprint = EvidenceFingerprint(
        adapter_id="synthetic",
        collected_at=_NOW,
        observations=(
            Observation(
                kind=ObservationKind.SKILL,
                identity="morning-plan",
                label="Morning plan",
                configuration_state=ConfigurationState.ENABLED,
                runtime_state=RuntimeState.NOT_ASSESSED,
                health_state=HealthState.NOT_ASSESSED,
                attributes=(
                    SafeAttribute(key="copy-count", value="5"),
                    SafeAttribute(key="variant-count", value="3"),
                ),
                evidence=EvidenceItem(
                    state="observed",
                    captured_at=_NOW,
                    reference="file-token:morning-plan",
                ),
                provenance={
                    "source_id": "scope:primary",
                    "source_class": "vault-authored",
                    "scope_reference": "scope:sha256:" + "a" * 64,
                    "relative_reference": "skills/morning-plan",
                },
            ),
        ),
    )
    slice_ = CachedCatalogueLoader(store).load(
        run_id="run:" + "c" * 32,
        fingerprint_digest="sha256:" + "b" * 64,
    )
    return UnknownUntilProposedComparer(store).compare(
        fingerprint=fingerprint,
        catalogue=slice_,
        jobs=(),
        proposals=(),
    )


def test_the_ranked_move_is_not_repeated_under_worth_borrowing() -> None:
    """The mimic run rendered the same paragraph under three headings."""

    ledger = _skill_copy_ledger()
    report = ReportModel.from_result(
        run_identity=run_identity(),
        ledger=ledger,
        ledger_sha256=canonical_ledger_digest(ledger),
        findings=(),
    )
    rendered = report.render_markdown(ledger)
    reason = next(
        item.reason for item in ledger.entries if item.catalogue_id == "skill-score"
    )

    visible = rendered.split("## Complete record appendix", 1)[0]
    assert visible.count(reason) == 1
    borrowing = _section(rendered, "## Worth borrowing from Dex")
    assert "ranked moves above" in borrowing
    assert "`skill-score`" in borrowing


# --- coverage speaks in the voice the run earned --------------------------------


def test_a_manual_only_family_does_not_flip_coverage_into_the_confession(
    tmp_path: Path,
) -> None:
    """The signed catalogue reserves one family for a person's review. That is
    a priced, named fact — not a reason to tell someone whose every area was
    assessed that 116 things were "not examined at all"."""

    rendered = _closed_report(tmp_path, DEX_ANSWERS, manual_family=True)
    block = _section(rendered, "## How much was examined")

    assert "not examined at all" not in block
    assert "reserves for a person's own review" in block
    assert "Privacy Safe Feedback Loop" in block


def test_a_postdated_family_row_does_not_call_its_components_unknown(
    tmp_path: Path,
) -> None:
    """Evidence of absence is not an absence of evidence: a family proven
    un-carryable by release history must not be summarised as Unknown."""

    rendered = _closed_report(tmp_path, DEX_ANSWERS)
    coverage = _section(rendered, "## Significant capability coverage")
    row = next(
        line for line in coverage.splitlines() if f"`{HEALTH_FAMILY}`" in line
    )

    assert "remain Unknown" not in row
    assert "cannot be on this install" in row


# --- the two doorways say what exists -------------------------------------------


def test_the_welcome_names_each_command_exactly_once(
    capsys: pytest.CaptureFixture,
) -> None:
    assert concierge_cli.main([]) == 0
    welcome = capsys.readouterr().out

    assert welcome.count("share-answers") == 1
    assert welcome.count("newsletter") == 1


def test_the_diagnosis_help_names_the_intake_step(
    capsys: pytest.CaptureFixture,
) -> None:
    assert diagnosis_cli.diagnosis_main(["--help"]) == 0
    help_text = capsys.readouterr().out

    assert "intake" in help_text
