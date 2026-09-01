"""The catalogue as an agent reads it.

These renderings are consumed by an assistant that can write to the person's
system. That makes two properties load-bearing rather than cosmetic: the text
must never read as permission to act, and it must never quietly drop a
capability, because an entry the reader cannot see is a choice made on the
person's behalf without them.
"""

from __future__ import annotations

import base64
import hashlib
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_bridge import _catalogue
from tests.catalogue.test_significant_contract import _catalogue as _significant_catalogue
from tests.catalogue.test_significant_contract import _family as _significant_family
from tests.catalogue.test_v2_verifier import NOW, sign_envelope, unsigned_envelope
from tests.diagnosis.test_significant_family_assessment import (
    _catalogue as assessment_catalogue,
)
from tests.diagnosis.test_significant_family_assessment import (
    _family as assessment_family,
)

from capability_exchange.catalogue.agent import (
    capability_by_id,
    render_capability_brief_markdown,
    render_catalogue_digest,
    render_catalogue_ledger_template,
)
from capability_exchange.catalogue.v2 import CatalogueV2, KeyRing, verify_catalogue_envelope
from capability_exchange.diagnosis.comparison import ComparisonLedger


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

    def test_digest_includes_family_state_derived_from_leaf_entries(self) -> None:
        catalogue = CatalogueV2.model_validate(
            _significant_catalogue(families=[_significant_family()])
        )

        digest = render_catalogue_digest(catalogue)

        assert "## Capability families" in digest
        assert "Durable task continuity" in digest
        assert "available" in digest

    def test_family_digest_ignores_unrelated_catalogue_entries(self) -> None:
        catalogue = assessment_catalogue(
            assessment_family(
                "work-family",
                profile="mcp",
                members=["dex-work-mcp"],
                components=[
                    {"component_type": "capability", "capability_id": "dex-work-mcp"}
                ],
            )
        )

        digest = render_catalogue_digest(catalogue)

        assert "Work Family" in digest


def test_ledger_template_contains_every_entry_and_release_identity() -> None:
    signing_key = Ed25519PrivateKey.from_private_bytes(b"ledger-template-test-key".ljust(32, b"!"))
    public_key = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    keyring = KeyRing(
        {"ledger-template-test": base64.b64encode(public_key).decode("ascii")}
    )
    raw = sign_envelope(
        unsigned_envelope(version=5, key_id="ledger-template-test"), signing_key
    )
    verified = verify_catalogue_envelope(raw, keyring=keyring, now=NOW)

    rendered = json.loads(render_catalogue_ledger_template(verified))
    parsed = ComparisonLedger.model_validate(rendered)
    rebound = ComparisonLedger.for_catalogue(
        verified.catalogue,
        catalogue_version=parsed.catalogue_version,
        catalogue_sha256=parsed.catalogue_sha256,
        capabilities=parsed.capabilities,
        entries=parsed.entries,
        reciprocal_answer=parsed.reciprocal_answer,
    )

    assert rendered["catalogue_version"] == 5
    assert rendered["catalogue_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert {item["catalogue_id"] for item in rendered["entries"]} == {
        item.capability_id for item in verified.catalogue.capabilities
    }
    assert all(item["disposition"] == "not-assessed" for item in rendered["entries"])
    assert rebound == parsed


def test_ledger_template_is_complete_for_enriched_family_catalogue() -> None:
    catalogue = assessment_catalogue(
        assessment_family(
            "work-family",
            profile="mcp",
            members=["dex-work-mcp"],
            components=[
                {"component_type": "capability", "capability_id": "dex-work-mcp"},
                {
                    "component_type": "mcp-tool",
                    "server_id": "dex-work-mcp",
                    "tool_name": "create_task",
                },
            ],
        )
    )
    envelope = SimpleNamespace(
        catalogue=catalogue,
        metadata=SimpleNamespace(catalog_version=7),
        _signed_json="synthetic-verified-enriched-catalogue",
    )

    rendered = json.loads(render_catalogue_ledger_template(envelope))
    parsed = ComparisonLedger.model_validate(rendered)
    rebound = ComparisonLedger.for_catalogue(
        catalogue,
        catalogue_version=parsed.catalogue_version,
        catalogue_sha256=parsed.catalogue_sha256,
        capabilities=parsed.capabilities,
        entries=parsed.entries,
        mcp_tools_by_server=parsed.mcp_tools_by_server,
        family_entries=parsed.family_entries,
        reciprocal_answer=parsed.reciprocal_answer,
    )

    assert parsed.family_entries[0].unresolved_components == (
        "capability:dex-work-mcp",
        "mcp-tool:dex-work-mcp:create_task",
    )
    assert parsed.mcp_tools_by_server
    assert rebound == parsed


class TestBrief:
    def test_it_says_outright_that_printing_it_changed_nothing(self) -> None:
        """The person is holding a document describing a change to their
        system. Whether one has already happened must not be inferable."""
        brief = render_capability_brief_markdown(_catalogue(), "durable-memory-boost")

        assert "Nothing on this machine has changed by printing this" in brief

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


class TestReversibility:
    def test_every_brief_opens_the_build_with_making_it_reversible(self) -> None:
        """The reassurance the page promises has to live in the brief itself.

        Lens never changes anything, so the only place a "you can always go
        back" promise can be kept is in the instructions handed to whichever
        AI eventually builds the thing: copy first, prove the way back, build
        removable. A brief without that section outsources the promise to
        hope.
        """
        brief = render_capability_brief_markdown(_catalogue(), "durable-memory-boost")

        assert "First, make it reversible" in brief
        assert brief.index("make it reversible") < brief.index("Prerequisites")
        assert "checked" in brief and "before the first edit" in brief
