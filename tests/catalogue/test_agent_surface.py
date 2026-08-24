"""The catalogue as an agent reads it.

These renderings are consumed by an assistant that can write to the person's
system. That makes two properties load-bearing rather than cosmetic: the text
must never read as permission to act, and it must never quietly drop a
capability, because an entry the reader cannot see is a choice made on the
person's behalf without them.
"""

from __future__ import annotations

import pytest
from tests.catalogue.test_bridge import _catalogue

from capability_exchange.catalogue.agent import (
    capability_by_id,
    render_capability_brief_markdown,
    render_catalogue_digest,
)


class TestDigest:
    def test_every_capability_appears(self) -> None:
        catalogue = _catalogue()

        digest = render_catalogue_digest(catalogue)

        for entry in catalogue.capabilities:
            assert entry.capability_id in digest, f"{entry.capability_id} is invisible"

    def test_a_capability_whose_job_is_missing_still_appears(self) -> None:
        """An unlisted job must not silently remove the capability.

        The taxonomy and the capability list are published together but they
        are separate fields, so they can disagree. Grouping strictly by job
        would drop the disagreement, and with it the entry.
        """
        catalogue = _catalogue()
        orphan = catalogue.capabilities[0].model_copy(update={"jobs": ("job-nobody-declared",)})
        catalogue = catalogue.model_copy(
            update={"capabilities": (orphan, *catalogue.capabilities[1:])}
        )

        digest = render_catalogue_digest(catalogue)

        assert orphan.capability_id in digest
        assert "Not listed under any known job" in digest

    def test_it_never_reads_as_permission(self) -> None:
        digest = render_catalogue_digest(_catalogue())

        assert "grants no permission" in digest

    def test_only_narrows_without_hiding_the_count(self) -> None:
        catalogue = _catalogue()
        wanted = catalogue.capabilities[0].capability_id

        digest = render_catalogue_digest(catalogue, only=[wanted])

        assert wanted in digest
        assert catalogue.capabilities[1].capability_id not in digest

    def test_a_narrowed_digest_counts_the_jobs_it_actually_shows(self) -> None:
        """"14 capabilities across 11 jobs" describes a document the reader,
        having narrowed to one job, is not holding."""
        catalogue = _catalogue()
        wanted = catalogue.capabilities[0]

        digest = render_catalogue_digest(catalogue, only=[wanted.capability_id])

        shown_jobs = sum(
            1 for job in catalogue.jobs_taxonomy if job.job_id in wanted.jobs
        )
        assert f"1 capabilities across {shown_jobs} jobs" in digest


class TestBrief:
    def test_it_says_it_is_not_permission_at_both_ends(self) -> None:
        """A long document gets skimmed from either end."""
        brief = render_capability_brief_markdown(_catalogue(), "durable-memory-boost")

        assert brief.count("grants no permission") >= 2

    def test_the_reason_is_attributed_not_absorbed(self) -> None:
        """Dex must never appear to have made a claim about this person."""
        why = "They already keep decisions in dated notes but never read them back."

        brief = render_capability_brief_markdown(
            _catalogue(), "durable-memory-boost", why=why
        )

        assert why in brief
        assert "not by Dex" in brief

    def test_no_reason_means_no_invented_reason(self) -> None:
        brief = render_capability_brief_markdown(_catalogue(), "durable-memory-boost")

        assert "Why this was suggested for this person" not in brief

    def test_dex_evidence_is_bounded_to_dex(self) -> None:
        """Evidence that Dex works is not evidence that it will help here."""
        brief = render_capability_brief_markdown(_catalogue(), "durable-memory-boost")

        assert "not evidence that it will work, or help, in this person's system" in brief

    def test_it_asks_for_a_rebuild_not_a_copy(self) -> None:
        brief = render_capability_brief_markdown(_catalogue(), "durable-memory-boost")

        assert "Rebuild it, do not copy it" in brief

    def test_an_unknown_id_names_what_is_available(self) -> None:
        with pytest.raises(KeyError) as caught:
            render_capability_brief_markdown(_catalogue(), "no-such-capability")

        message = caught.value.args[0]
        assert "no-such-capability" in message
        assert "durable-memory-boost" in message, "the error must be actionable"


class TestLookup:
    def test_it_finds_by_exact_id(self) -> None:
        entry = capability_by_id(_catalogue(), "health-observer")

        assert entry.title == "Health Observer"
