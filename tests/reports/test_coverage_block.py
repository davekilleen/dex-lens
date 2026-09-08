"""The headline coverage block: lead with what was covered; confess only holes.

The first real run assessed 21 of 115 catalogue entries and the 94 left
``not-assessed`` hid in the appendix; the person concluded the product had
missed a tonne of capability — correctly. The first fix made the block a loud
confession. The founder then rejected the failure-count voice for the two-pass
product (2026-09-07): when the ledger carries a real family map — every signed
area assessed by the deterministic matcher, and any focused selection's
members individually examined — the block leads with what WAS covered, and the
words "not examined" appear only in the fallback branch for a ledger lacking
that map coverage, where the original confession stands verbatim. These tests
hold both voices, the branch condition between them, and the check gate that
refuses a report shipped without its coverage story — whichever branch
applies.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import NOW as CATALOGUE_NOW
from tests.catalogue.test_v2_verifier import sign_envelope, unsigned_envelope
from tests.diagnosis.test_run import NOW, RUN_ID
from tests.reports.test_ledger import _full_ledger, _grounded_report

from capability_exchange.catalogue.v2 import (
    KeyRing,
    VerifiedCatalogueStore,
    verify_catalogue_envelope,
)
from capability_exchange.diagnosis.comparison import (
    CatalogueDisposition,
    ComparisonLedger,
    Disposition,
)
from capability_exchange.diagnosis.families import FamilyAvailability
from capability_exchange.diagnosis.report import (
    ReportModel,
    canonical_coverage_block,
    canonical_ledger_digest,
    canonical_ledger_payload,
    coverage_block_errors,
)
from capability_exchange.diagnosis.run import (
    ENGINE_VERSION,
    INPUT_SCHEMA_VERSION,
    RunIdentity,
)
from capability_exchange.diagnosis.significant_families import (
    FamilyAssessmentDisposition,
)
from capability_exchange.reports import cli

TOTAL = 115
ASSESSED = 21


def _entry_id(index: int) -> str:
    return f"invented-capability-{index:03d}"


def _entries(assessed: int, total: int) -> tuple[CatalogueDisposition, ...]:
    return tuple(
        CatalogueDisposition(
            catalogue_id=_entry_id(index),
            capability_id="unassigned",
            disposition=(
                Disposition.NOT_RELEVANT if index < assessed else Disposition.NOT_ASSESSED
            ),
            reason=(
                "Not relevant to the invented setup."
                if index < assessed
                else "Not assessed in this run."
            ),
        )
        for index in range(total)
    )


def _family(
    family_id: str,
    title: str,
    member_ids: tuple[str, ...],
    *,
    disposition: FamilyAssessmentDisposition = FamilyAssessmentDisposition.NOT_ASSESSED,
    reason: str = "Not assessed yet.",
) -> dict[str, object]:
    return {
        "family_id": family_id,
        "title": title,
        "outcome": f"{title} outcome, described by the signed catalogue.",
        "signed_availability": FamilyAvailability.AVAILABLE.value,
        "available_member_ids": list(member_ids),
        "unavailable_member_ids": [],
        "recommendable_member_ids": list(member_ids),
        "matched_components": [],
        "matched_observation_ids": [],
        "unresolved_components": [],
        "evidence_references": [],
        "disposition": disposition.value,
        "reason": reason,
    }


#: Three signed areas: one wholly unexamined, one partly, one fully assessed.
#: Every row is disposition ``not-assessed`` on purpose: a ledger whose family
#: rows were never assessed carries no map coverage, so these families pin the
#: fallback confession voice.
_FAMILIES = (
    _family(
        "meeting-follow-through",
        "Meeting follow-through",
        tuple(_entry_id(index) for index in range(21, 27)),
    ),
    _family(
        "memory",
        "Memory",
        (_entry_id(6), _entry_id(27), _entry_id(28)),
    ),
    _family(
        "backup-safety",
        "Backup safety",
        tuple(_entry_id(index) for index in range(6)),
    ),
)

#: The same three signed areas as a real family map: every row assessed by
#: the deterministic matcher, so the coverage-first voice applies.
_MAPPED_FAMILIES = (
    _family(
        "meeting-follow-through",
        "Meeting follow-through",
        tuple(_entry_id(index) for index in range(21, 27)),
        disposition=FamilyAssessmentDisposition.UNRESOLVED,
        reason="No exact local overlap was proven.",
    ),
    _family(
        "memory",
        "Memory",
        (_entry_id(6), _entry_id(27), _entry_id(28)),
        disposition=FamilyAssessmentDisposition.UNRESOLVED,
        reason="No exact local overlap was proven.",
    ),
    _family(
        "backup-safety",
        "Backup safety",
        tuple(_entry_id(index) for index in range(6)),
        disposition=FamilyAssessmentDisposition.OVERLAP_OBSERVED,
        reason="Every published component matched exactly.",
    ),
)


def _ledger(
    *,
    assessed: int = ASSESSED,
    total: int = TOTAL,
    families: tuple[dict[str, object], ...] = _FAMILIES,
    focus_selected: tuple[str, ...] = (),
    focus_unselected: tuple[str, ...] = (),
) -> ComparisonLedger:
    return ComparisonLedger.model_validate(
        {
            "catalogue_version": 1,
            "catalogue_sha256": "a" * 64,
            "capabilities": [],
            "entries": [entry.model_dump(mode="json") for entry in _entries(assessed, total)],
            "family_entries": list(families),
            "reciprocal_answer": "No transferable method cleared the evidence bar.",
            "focus_selected_family_ids": list(focus_selected),
            "focus_unselected_family_ids": list(focus_unselected),
        }
    )


def _report(ledger: ComparisonLedger) -> ReportModel:
    return ReportModel.from_result(
        run_identity=RunIdentity(
            run_id=RUN_ID,
            engine_version=ENGINE_VERSION,
            input_schema_version=INPUT_SCHEMA_VERSION,
            created_at=NOW,
        ),
        ledger=ledger,
        ledger_sha256=canonical_ledger_digest(ledger),
    )


class TestTheCoverageBlockIsLoudAndPlaced:
    """Intent shift, 2026-09-07: these tests now pin the FALLBACK voice.

    The fixture families all carry disposition ``not-assessed``, so the ledger
    lacks map coverage and the original confession — counts with their
    denominator, the areas the unexamined entries sit in — must stand
    verbatim. The coverage-first voice for map-covered ledgers is pinned by
    :class:`TestTheCoverageFirstVoice` below.
    """

    def test_the_block_names_the_counts_with_their_denominator(self) -> None:
        block = canonical_coverage_block(_ledger())

        assert block.startswith("## How much was examined\n")
        assert (
            "Of the 115 entries in the signed Dex catalogue, 21 were assessed "
            "against your system and 94 were not examined at all." in block
        )

    def test_the_unexamined_concentrate_in_named_signed_areas(self) -> None:
        block = canonical_coverage_block(_ledger())

        meeting = (
            "- Meeting follow-through (`meeting-follow-through`): "
            "6 of its 6 signed members were not examined."
        )
        memory = "- Memory (`memory`): 2 of its 3 signed members were not examined."
        assert meeting in block
        assert memory in block
        # The wholly assessed area is not blamed, and the fuller gap leads.
        assert "Backup safety" not in block
        assert block.index(meeting) < block.index(memory)

    def test_unexamined_entries_outside_every_area_are_still_counted(self) -> None:
        block = canonical_coverage_block(_ledger())

        assert "- Outside every signed capability area: " in block
        # 94 not examined; 6 + 2 sit in named areas, so 86 sit outside and
        # the first few are named with the remainder counted, never hidden.
        assert f"`{_entry_id(29)}`" in block
        assert "and 78 more in the full record appendix." in block

    def test_the_block_offers_the_follow_up_in_one_plain_sentence(self) -> None:
        block = canonical_coverage_block(_ledger())

        assert (
            "A deeper look at these areas is a second, shorter run — it "
            "examines only what you point at." in block
        )

    def test_without_signed_families_the_top_unassessed_ids_are_named(self) -> None:
        block = canonical_coverage_block(_ledger(families=()))

        assert "no signed capability-family contract" in block.lower()
        assert f"`{_entry_id(21)}`" in block
        assert f"`{_entry_id(28)}`" in block
        assert "and 86 more in the full record appendix." in block

    def test_the_rendered_report_carries_the_block_near_the_top(self) -> None:
        ledger = _ledger()
        markdown = _report(ledger).render_markdown(ledger)

        block = canonical_coverage_block(ledger)
        assert block in markdown
        assert markdown.index(block) < markdown.index("## What is working especially well")
        assert markdown.index(block) < markdown.index("## Coverage and limits")

    def test_a_fully_assessed_unmapped_ledger_says_so_plainly(self) -> None:
        """Intent shift: without map coverage the plain all-assessed line
        stands; a fully assessed ledger WITH map coverage now speaks the
        coverage-first voice (see TestTheCoverageFirstVoice)."""

        ledger = _ledger(assessed=TOTAL)
        block = canonical_coverage_block(ledger)

        assert "All 115 entries in the signed Dex catalogue were assessed" in block
        assert "not examined" not in block

    def test_the_block_is_deterministic_under_reordered_input(self) -> None:
        ledger = _ledger()
        reordered = ComparisonLedger.model_validate(
            {
                **canonical_ledger_payload(ledger),
                "entries": [
                    entry.model_dump(mode="json") for entry in reversed(ledger.entries)
                ],
                "family_entries": [
                    dict(family) for family in reversed(_FAMILIES)
                ],
            }
        )

        assert canonical_coverage_block(ledger) == canonical_coverage_block(reordered)


class TestTheCoverageFirstVoice:
    """The founder-directed rewording for the two-pass product (2026-09-07).

    When every family row was actually assessed by the deterministic matcher
    — and, on a focused run, every member of every selected family carries an
    individual verdict — the block leads with what WAS covered: all areas
    assessed, the deep dives named, everything else covered at the map level
    and one ask away. It never leads with a failure count, and the words
    "not examined" never appear in this voice.
    """

    @staticmethod
    def _mapped(
        *,
        assessed: int = ASSESSED,
        selected: tuple[str, ...] = (),
        unselected: tuple[str, ...] = (),
    ) -> ComparisonLedger:
        return _ledger(
            assessed=assessed,
            families=_MAPPED_FAMILIES,
            focus_selected=selected,
            focus_unselected=unselected,
        )

    def test_a_mapped_ledger_leads_with_what_was_covered(self) -> None:
        block = canonical_coverage_block(self._mapped())

        assert block.startswith(
            "## How much was examined\n"
            "All three signed capability areas of Dex were assessed against "
            "your system.\n"
        )
        assert "not examined" not in block

    def test_an_unfocused_mapped_ledger_offers_the_map_level_line(self) -> None:
        block = canonical_coverage_block(self._mapped())

        assert (
            "Every area is covered at the map level — a deeper look at any of "
            "them is one ask away." in block
        )

    def test_a_focused_selection_names_its_deep_dives(self) -> None:
        block = canonical_coverage_block(
            self._mapped(
                assessed=29,
                selected=("backup-safety", "memory"),
                unselected=("meeting-follow-through",),
            )
        )

        assert (
            "You took deep dives into Backup safety (`backup-safety`) and "
            "Memory (`memory`); every capability inside them was examined "
            "individually, one by one." in block
        )
        assert (
            "The other area is covered at the map level — a deeper look at it "
            "is one ask away." in block
        )
        assert "not examined" not in block

    def test_the_voice_never_leads_with_a_failure_count(self) -> None:
        block = canonical_coverage_block(self._mapped())
        first_sentence_line = block.splitlines()[1]

        assert not first_sentence_line.startswith("Of the ")
        assert "94" not in block

    def test_a_silent_hole_in_a_selected_family_falls_back_to_the_confession(
        self,
    ) -> None:
        """A focused ledger that violates its own coverage gate — a selected
        family member left not-assessed — does not get the triumphant voice."""

        block = canonical_coverage_block(
            self._mapped(
                assessed=3,
                selected=("backup-safety",),
                unselected=("meeting-follow-through", "memory"),
            )
        )

        assert "were not examined at all" in block

    def test_a_map_with_an_unassessed_row_keeps_the_confession(self) -> None:
        """Family rows the matcher never assessed are not map coverage."""

        block = canonical_coverage_block(_ledger())

        assert "were not examined at all" in block

    def test_a_fully_assessed_mapped_ledger_counts_every_entry(self) -> None:
        block = canonical_coverage_block(self._mapped(assessed=TOTAL))

        assert (
            "All three signed capability areas of Dex were assessed against "
            "your system." in block
        )
        assert (
            "Every one of the 115 entries in the signed Dex catalogue was "
            "examined individually." in block
        )
        assert "not examined" not in block

    def test_the_check_gate_demands_the_story_for_a_mapped_ledger(self) -> None:
        """A report must still refuse to ship without its coverage story,
        whichever branch applies — here, the coverage-first branch."""

        ledger = self._mapped()

        errors = coverage_block_errors("# Diagnosis\n", ledger)
        assert len(errors) == 1
        assert "How much was examined" in errors[0]
        assert "family-map coverage story" in errors[0]

        carrying = f"# Diagnosis\n\n{canonical_coverage_block(ledger)}"
        assert coverage_block_errors(carrying, ledger) == ()

    def test_the_check_gate_demands_the_story_even_fully_assessed(self) -> None:
        ledger = self._mapped(assessed=TOTAL)

        assert coverage_block_errors("# Diagnosis\n", ledger) != ()

    def test_the_rendered_report_carries_the_coverage_first_block(self) -> None:
        ledger = self._mapped(
            assessed=29,
            selected=("backup-safety", "memory"),
            unselected=("meeting-follow-through",),
        )
        markdown = _report(ledger).render_markdown(ledger)

        assert canonical_coverage_block(ledger) in markdown


class TestTheCheckRefusesAReportThatLostTheBlock:
    def test_errors_name_the_missing_block_when_not_assessed_is_nonzero(self) -> None:
        ledger = _ledger()
        markdown = _report(ledger).render_markdown(ledger)
        stripped = markdown.replace(canonical_coverage_block(ledger), "")

        assert coverage_block_errors(markdown, ledger) == ()
        errors = coverage_block_errors(stripped, ledger)
        assert len(errors) == 1
        assert "94" in errors[0] and "115" in errors[0]

    def test_a_fully_assessed_unmapped_ledger_demands_no_block(self) -> None:
        """Intent shift: only a ledger with neither unexamined entries nor map
        coverage owes nothing — a map-covered ledger always owes its story
        (see TestTheCoverageFirstVoice)."""

        ledger = _ledger(assessed=TOTAL, families=())

        assert coverage_block_errors("# Diagnosis\n", ledger) == ()

    @staticmethod
    def _verified_catalogue_with_unexamined_entries():
        """A signed three-entry catalogue: one entry assessed leaves two behind.

        The shared single-entry fixture catalogue cannot exercise this rule —
        its one entry is assessed, so nothing remains unexamined and the
        coverage block owes nothing.
        """
        signing_key = Ed25519PrivateKey.from_private_bytes(
            b"coverage-block-test-key".ljust(32, b"!")
        )
        public_key = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        keyring = KeyRing({"coverage-test": base64.b64encode(public_key).decode("ascii")})
        envelope = unsigned_envelope(version=6, key_id="coverage-test")
        base_capability = envelope["catalogue"]["capabilities"][0]
        for suffix in ("b", "c"):
            capability = copy.deepcopy(base_capability)
            capability["capability_id"] = f"invented-coverage-{suffix}"
            capability["title"] = f"Invented coverage {suffix.upper()}"
            envelope["catalogue"]["capabilities"].append(capability)
        raw = sign_envelope(envelope, signing_key)
        return verify_catalogue_envelope(raw, keyring=keyring, now=CATALOGUE_NOW), keyring

    @pytest.fixture
    def saved_pair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path, ComparisonLedger]:
        """A saved report and ledger, exactly as a finished diagnosis writes them."""
        verified, keyring = self._verified_catalogue_with_unexamined_entries()
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        from capability_exchange.catalogue.subscription import default_lens_app_storage

        VerifiedCatalogueStore(default_lens_app_storage()).save_verified(verified)
        monkeypatch.setattr(cli, "default_keyring", lambda: keyring)
        ledger = _full_ledger(verified)
        source = tmp_path / "report.md"
        source.write_text(_grounded_report(ledger), encoding="utf-8")
        ledger_path = tmp_path / "ledger.json"
        ledger_path.write_text(
            json.dumps(canonical_ledger_payload(ledger)), encoding="utf-8"
        )
        return source, ledger_path, ledger

    def test_the_untouched_pair_passes(
        self, saved_pair: tuple[Path, Path, ComparisonLedger]
    ) -> None:
        source, ledger_path, _ledger_model = saved_pair

        assert cli.reports_main(["check", str(source), "--ledger", str(ledger_path)]) == 0

    def test_check_refuses_the_report_stripped_of_the_coverage_block(
        self,
        saved_pair: tuple[Path, Path, ComparisonLedger],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source, ledger_path, ledger = saved_pair
        block = canonical_coverage_block(ledger)
        markdown = source.read_text(encoding="utf-8")
        assert block in markdown, "the grounded fixture must carry the block it strips"
        source.write_text(markdown.replace(block, ""), encoding="utf-8")

        assert cli.reports_main(["check", str(source), "--ledger", str(ledger_path)]) == 2
        assert "how much was examined" in capsys.readouterr().err.lower()

    def test_save_refuses_the_stripped_report_too(
        self, saved_pair: tuple[Path, Path, ComparisonLedger], tmp_path: Path
    ) -> None:
        source, ledger_path, ledger = saved_pair
        markdown = source.read_text(encoding="utf-8")
        source.write_text(
            markdown.replace(canonical_coverage_block(ledger), ""), encoding="utf-8"
        )

        assert (
            cli.reports_main(
                ["save", str(source), "--ledger", str(ledger_path), "--for", str(tmp_path)]
            )
            == 2
        )
