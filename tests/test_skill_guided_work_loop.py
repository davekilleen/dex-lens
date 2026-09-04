"""Skill drives the engine-owned guided work loop."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from capability_exchange.diagnosis.specialists import (
    ProposalContext,
    SpecialistProposal,
    validate_proposal,
)

SKILL = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "capability_exchange"
    / "skill"
    / "dex-lens"
    / "SKILL.md"
)


def _worked_example_payloads() -> list[dict[str, object]]:
    """Every ```json block in the skill is a worked proposal example."""

    text = SKILL.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", text, flags=re.DOTALL)
    return [json.loads(block) for block in blocks]


def test_skill_drives_guided_work_without_stage_prompts() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "get_diagnosis_work" in text
    assert "process every engine-issued packet" in text.lower() or "fetch the next packet" in text
    assert "never ask the person to prompt the next diagnosis stage" in text.lower()
    assert "submit the specialist response unchanged" in text.lower()
    assert "up to ten" in text.lower()


def test_skill_has_parallel_and_sequential_host_routes() -> None:
    # Markdown wraps lines, so compare against whitespace-normalised text.
    text = " ".join(SKILL.read_text(encoding="utf-8").lower().split())
    assert "fan the independent packets out in parallel" in text
    assert "parallel is the default whenever the host allows it" in text
    assert "sequential processing in this conversation is the fallback" in text


def test_skill_fans_out_the_whole_round_from_one_work_fetch() -> None:
    """The host fetches once per round, fans out every listed packet at once,
    gives each worker only its own packet plus the shared legend, and submits
    responses as they return."""

    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "one `work --json` fetch per round" in text
    assert "every packet you may answer right now" in text
    assert "in the same breath" in text
    assert "only its own packet" in text
    assert "plus the shared legend" in text
    assert "not the other packets" in text.lower()
    assert "as each worker returns" in text.lower()
    assert "order does not matter" in text


def test_skill_polls_status_at_stage_transitions_only() -> None:
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "at stage transitions" in text.lower()
    assert "never between packet submissions" in text.lower()
    assert "after every engine step" not in text.lower()


def test_skill_states_the_economics_of_the_packet_round() -> None:
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "costs real model time" in text
    assert "the packet round is the expensive stretch" in text
    assert "parallel is how it stays short" in text


def test_skill_worked_examples_are_valid_specialist_proposals() -> None:
    """The three worked examples must clear the real proposal model.

    This is the docs test for the proposal schema: if the model gains,
    drops or retypes a field, the skill's examples stop validating and
    this test goes red before a real host hits the drift.
    """

    payloads = _worked_example_payloads()
    assert len(payloads) == 3, "the skill must show exactly three worked proposal examples"
    proposals = [SpecialistProposal.model_validate(payload) for payload in payloads]
    kinds = {proposal.kind.value for proposal in proposals}
    assert kinds == {"strength", "recommendation", "fragility"}
    for proposal in proposals:
        # Each example is packet-bound, exactly as a guided run requires.
        assert proposal.packet_id is not None
        assert proposal.packet_digest is not None
        assert proposal.candidate_id is not None
        recommendation = proposal.kind.value == "recommendation"
        assert (proposal.recommendation_factors is not None) == recommendation
        # The example must clear full guided validation against a context
        # built from its own packet identities, exactly as the engine does.
        context = ProposalContext(
            analysis_mode="guided-analysis",
            run_id=proposal.run_id,
            fingerprint_digest=proposal.fingerprint_digest,
            catalogue_digest=proposal.catalogue_digest,
            packet_id=proposal.packet_id,
            packet_digest=proposal.packet_digest,
            packet_role=proposal.role,
            evidence_ids=proposal.evidence_ids,
            catalogue_ids=(proposal.catalogue_id,),
            capability_ids=(proposal.capability_id,),
            observation_ids=proposal.observation_ids,
        )
        validate_proposal(proposal, context)


def test_skill_recommendation_example_names_all_five_factors() -> None:
    payloads = _worked_example_payloads()
    recommendations = [item for item in payloads if item.get("kind") == "recommendation"]
    assert len(recommendations) == 1
    factors = recommendations[0]["recommendation_factors"]
    assert set(factors) == {
        "reliability_risk",
        "job_relevance",
        "workflow_leverage",
        "evidence_strength",
        "adoption_effort",
    }


def test_skill_candidate_id_recipe_actually_computes() -> None:
    """The shown one-liner must print the candidate_id the example carries."""

    text = SKILL.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip().startswith("python3 -c")]
    assert len(lines) == 1, "the skill must show the candidate_id one-liner exactly once"
    parts = shlex.split(lines[0].strip())
    assert parts[:2] == ["python3", "-c"]
    completed = subprocess.run(
        [sys.executable, "-c", parts[2]],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    recommendations = [
        item for item in _worked_example_payloads() if item.get("kind") == "recommendation"
    ]
    assert completed.stdout.strip() == recommendations[0]["candidate_id"]


def test_skill_documents_the_evidence_legend_columns() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "evidence_legend" in text
    for column in (
        "evidence_id",
        "observation_id",
        "kind",
        "identity",
        "label",
        "relative_reference",
        "source_class",
    ):
        assert f"`{column}`" in text


def test_skill_states_the_two_attempt_protocol_and_honest_empty() -> None:
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "one retry" in text.lower()
    assert "two attempts" in text.lower()
    assert "final for that packet" in text
    assert "Never loop empty submissions through the packets" in text


def test_skill_states_the_sceptical_packet_rules() -> None:
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "preserve or downgrade" in text
    assert "exact evidence and observation identities" in text


def test_skill_command_table_covers_work_and_packet_submit() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "| `dex-lens diagnosis work --run <id>` |" in text
    assert "| `dex-lens diagnosis submit --run <id> --packet <id> --proposal <file>` |" in text
