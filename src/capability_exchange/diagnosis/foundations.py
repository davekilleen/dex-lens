"""The eight Foundation Capabilities encoded as data (#351; HANDOFF 2.3 M-D).

Each Foundation Capability carries, verbatim-faithful to the #351 resolution:
a defined user job, observable evidence, a safety boundary, and its negative
rules — including the four cross-cutting ones the resolution names (read
access never implies write permission; file presence never means healthy;
chat history alone is not memory proof; no autonomous permanent
self-modification).

Everything here is data, not behavior: plain frozen structures the engine
(:mod:`capability_exchange.diagnosis.engine`) interprets deterministically.
Nothing in this module reads, writes, or transmits anything.

**Probe-pattern vocabulary.** Observable evidence is made machine-checkable
through kebab-case probe-id patterns (a pattern matches when it is a
substring of a probe id, mirroring the deterministic probe-id keying of the
M-C proposal rules). Four pattern classes exist per capability:

- ``outcome_probe_patterns`` — probes whose evidence is a recent real
  example of the job outcome itself. Only these can ground ``Working``.
- ``configuration_probe_patterns`` — probes whose evidence is configuration
  or file presence. "File exists" is evidence of configuration, not proof of
  a job outcome (HANDOFF 2.3 M-B): presence alone never yields ``Working``
  or ``Verified``.
- ``boundary_probe_patterns`` — probes whose evidence speaks to the
  capability staying inside the assessed job's limits.
- ``overbroad_probe_patterns`` — probes whose evidence shows the capability
  operating beyond what the assessed job requires.

Some patterns name probes no shipped adapter emits yet; as with the M-C
proposal rules, the vocabulary is declared now so later adapters feed the
same deterministic path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

__all__ = [
    "FOUNDATION_DEFINITIONS",
    "FoundationCapability",
    "FoundationDefinition",
    "NegativeRule",
    "definition_for",
    "negative_rule_ids",
]


class FoundationCapability(StrEnum):
    """Closed vocabulary: exactly these eight Foundation Capabilities exist.

    Do not add, remove, or rename members without re-opening #351: the
    definitions, the engine, and the conformance tests all key on this enum.
    Evidence quality is an evaluation dimension, not a ninth capability.
    """

    OWNERSHIP_PORTABILITY = "ownership-portability"
    PRIVACY_MINIMAL_DISCLOSURE = "privacy-minimal-disclosure"
    CONTEXT_ORIENTATION = "context-orientation"
    DURABLE_MEMORY_PROVENANCE = "durable-memory-provenance"
    SCOPED_AGENCY_HUMAN_CONTROL = "scoped-agency-human-control"
    SAFE_CHANGE_RECOVERY = "safe-change-recovery"
    HONEST_HEALTH_OBSERVABILITY = "honest-health-observability"
    COMPOUNDING_CORRECTABILITY = "compounding-correctability"


@dataclass(frozen=True, slots=True)
class NegativeRule:
    """One negative rule from the #351 resolution: what never follows.

    ``rule_id`` is the stable kebab-case handle the fixture suite keys on —
    every encoded negative rule has a fixture test proving the engine
    honors it.
    """

    rule_id: str
    statement: str


#: The four state values ``next_moves`` must cover (kept as literals here so
#: this data module does not import the finding schema; the engine looks the
#: move up by ``CapabilityState.value`` and a test asserts the two sets agree).
_STATE_VALUES: tuple[str, ...] = ("working", "partial", "not-demonstrated", "unknown")


@dataclass(frozen=True, slots=True)
class FoundationDefinition:
    """One Foundation Capability as data: definition, evidence, boundary, rules."""

    capability: FoundationCapability
    #: The defined user job (#351): what the person gets from this capability.
    user_job: str
    #: Observable evidence, as prose from the #351 resolution.
    observable_evidence: tuple[str, ...]
    #: The safety boundary, as prose from the #351 resolution.
    safety_boundary: str
    #: The negative rules: what never counts, and what never follows.
    negative_rules: tuple[NegativeRule, ...]
    #: Probe-id patterns for recent-real-example (outcome) evidence.
    outcome_probe_patterns: tuple[str, ...]
    #: Probe-id patterns for configuration/presence evidence.
    configuration_probe_patterns: tuple[str, ...]
    #: Probe-id patterns for boundary-respected evidence.
    boundary_probe_patterns: tuple[str, ...]
    #: Probe-id patterns for beyond-the-job (overbroad) evidence.
    overbroad_probe_patterns: tuple[str, ...]
    #: Why this capability matters, in useful non-judgmental language.
    practical_implication: str
    #: Exactly one recommended next move per capability state value.
    next_moves: Mapping[str, str]

    def __post_init__(self) -> None:
        if set(self.next_moves) != set(_STATE_VALUES):
            raise ValueError(
                f"{self.capability.value}: next_moves must cover exactly the "
                f"capability-state values {_STATE_VALUES}"
            )


_DEFINITIONS: tuple[FoundationDefinition, ...] = (
    FoundationDefinition(
        capability=FoundationCapability.OWNERSHIP_PORTABILITY,
        user_job=(
            "The person retains custody and can inspect, export, move, or "
            "replace the system."
        ),
        observable_evidence=(
            "usable inventories",
            "readable exports",
            "open formats",
            "a demonstrated exit path",
        ),
        safety_boundary=(
            "Never move, delete, or export without approval; export and exit "
            "stay within what the person approved for the assessed job."
        ),
        negative_rules=(
            NegativeRule(
                rule_id="never-move-delete-export-without-approval",
                statement="Never move, delete, or export without approval.",
            ),
            NegativeRule(
                rule_id="file-presence-is-not-portability-proof",
                statement="Do not treat local file presence as proof of portability.",
            ),
        ),
        outcome_probe_patterns=("export-readable", "exit-path-demonstrated"),
        configuration_probe_patterns=("installation-shape", "open-format"),
        boundary_probe_patterns=("export-approval",),
        overbroad_probe_patterns=("unapproved-export", "unapproved-move", "unapproved-delete"),
        practical_implication=(
            "Custody of your own system decides whether you can leave, back "
            "up, or rebuild without losing your work."
        ),
        next_moves={
            "working": (
                "Keep a recent readable export where you control it, and "
                "note the exit path you demonstrated."
            ),
            "partial": (
                "Exercise the export or exit path end to end once and keep "
                "the readable result."
            ),
            "not-demonstrated": (
                "Try one real export of your material and check you can "
                "read it without the system."
            ),
            "unknown": (
                "Identify where your material lives and whether any export "
                "path exists to inspect."
            ),
        },
    ),
    FoundationDefinition(
        capability=FoundationCapability.PRIVACY_MINIMAL_DISCLOSURE,
        user_job=(
            "The system accesses and reveals only what the job requires."
        ),
        observable_evidence=(
            "declared scopes",
            "access paths",
            "redaction",
            "local processing",
            "actual outbound-data behavior",
        ),
        safety_boundary=(
            "Unknown paths remain Unknown; diagnosis does not scan secrets "
            "or unrelated private content."
        ),
        negative_rules=(
            NegativeRule(
                rule_id="unknown-access-paths-remain-unknown",
                statement="Unknown paths remain Unknown; nothing unassessed counts as safe.",
            ),
            NegativeRule(
                rule_id="diagnosis-never-scans-secrets-or-unrelated-content",
                statement=(
                    "Diagnosis does not scan secrets or unrelated private "
                    "content; evidence outside the declared patterns grounds "
                    "no finding."
                ),
            ),
        ),
        outcome_probe_patterns=("minimal-disclosure-demonstrated", "local-processing-demonstrated"),
        configuration_probe_patterns=("collection-exclusions", "declared-scope-config"),
        boundary_probe_patterns=("outbound-data-observed", "redaction-observed"),
        overbroad_probe_patterns=("reads-beyond-scope", "disclosure-beyond-job"),
        practical_implication=(
            "What the system can read and reveal sets the real cost of every "
            "job you give it."
        ),
        next_moves={
            "working": (
                "Re-check the declared scopes the next time the job's "
                "material changes."
            ),
            "partial": (
                "Narrow one access path to what this job actually requires "
                "and re-run the job."
            ),
            "not-demonstrated": (
                "Run the job once and watch what the system actually reads "
                "and reveals for it."
            ),
            "unknown": (
                "List which paths this job can reach; anything you cannot "
                "list stays Unknown."
            ),
        },
    ),
    FoundationDefinition(
        capability=FoundationCapability.CONTEXT_ORIENTATION,
        user_job=(
            "The system can start or resume work with relevant, current context."
        ),
        observable_evidence=(
            "repeatable job examples with freshness visibility",
            "repeatable job examples with source visibility",
        ),
        safety_boundary=(
            "More context is not automatically better; stale and inferred "
            "context must be labeled."
        ),
        negative_rules=(
            NegativeRule(
                rule_id="stale-and-inferred-context-must-be-labeled",
                statement="Stale and inferred context must be labeled, never silently trusted.",
            ),
            NegativeRule(
                rule_id="more-context-is-not-automatically-better",
                statement=(
                    "More context is not automatically better; volume of "
                    "material never upgrades an assessment."
                ),
            ),
        ),
        outcome_probe_patterns=("recent-activity", "resume-demonstrated"),
        configuration_probe_patterns=("instructions-present", "settings-present"),
        boundary_probe_patterns=("context-freshness-observed",),
        overbroad_probe_patterns=("context-beyond-job",),
        practical_implication=(
            "Whether work resumes with current context decides how much you "
            "re-explain every session."
        ),
        next_moves={
            "working": (
                "Note which context sources made the resume work, so you can "
                "keep them current."
            ),
            "partial": (
                "Refresh the stalest context source this job depends on, "
                "then resume the job once."
            ),
            "not-demonstrated": (
                "Resume this job cold once and see what context the system "
                "actually brings."
            ),
            "unknown": (
                "Pick one recent example of this job to walk through with "
                "the system."
            ),
        },
    ),
    FoundationDefinition(
        capability=FoundationCapability.DURABLE_MEMORY_PROVENANCE,
        user_job=(
            "Important knowledge survives sessions, can be sourced, "
            "corrected, and removed."
        ),
        observable_evidence=(
            "write-retrieve-correct behavior across sessions",
        ),
        safety_boundary=(
            "Chat history or configuration alone is not proof, and the "
            "system must not invent memory."
        ),
        negative_rules=(
            NegativeRule(
                rule_id="chat-history-alone-is-not-memory-proof",
                statement="Chat history or configuration alone is not proof of durable memory.",
            ),
            NegativeRule(
                rule_id="the-system-must-not-invent-memory",
                statement=(
                    "The system must not invent memory; no claim-supporting "
                    "memory evidence exists unless the collection observed it."
                ),
            ),
        ),
        outcome_probe_patterns=("write-retrieve-correct", "memory-recall-demonstrated"),
        configuration_probe_patterns=("chat-history", "memory-config"),
        boundary_probe_patterns=("memory-correction-observed", "memory-removal-observed"),
        overbroad_probe_patterns=("memory-beyond-consent",),
        practical_implication=(
            "Durable, correctable memory decides whether the system's "
            "knowledge of your work can be trusted and repaired."
        ),
        next_moves={
            "working": (
                "Correct one remembered fact and confirm the correction "
                "survives the next session."
            ),
            "partial": (
                "Test removal: delete one remembered item and confirm it "
                "stays gone across sessions."
            ),
            "not-demonstrated": (
                "Write one fact, end the session, and check the system can "
                "retrieve and source it."
            ),
            "unknown": (
                "Find out where this system claims to keep durable knowledge "
                "before relying on it."
            ),
        },
    ),
    FoundationDefinition(
        capability=FoundationCapability.SCOPED_AGENCY_HUMAN_CONTROL,
        user_job=(
            "The person can delegate within understood authority."
        ),
        observable_evidence=(
            "permission boundaries",
            "approvals",
            "action receipts",
            "refusal of out-of-scope actions",
        ),
        safety_boundary=(
            "Read access never implies permission to write, send, or expand "
            "privileges."
        ),
        negative_rules=(
            NegativeRule(
                rule_id="read-access-never-implies-write-permission",
                statement=(
                    "Read access never implies permission to write, send, or "
                    "expand privileges."
                ),
            ),
        ),
        outcome_probe_patterns=("approval-receipt", "refusal-demonstrated", "action-receipt"),
        configuration_probe_patterns=("read-access", "permission-config"),
        boundary_probe_patterns=("permission-boundary-observed",),
        overbroad_probe_patterns=("write-access-observed", "privilege-expansion", "send-access"),
        practical_implication=(
            "Understood authority is what makes delegation safe: you know "
            "what the system may do before it acts."
        ),
        next_moves={
            "working": (
                "Review the standing approvals once and retire any this job "
                "no longer needs."
            ),
            "partial": (
                "Ask the system to do one out-of-scope action and confirm it "
                "refuses with a receipt."
            ),
            "not-demonstrated": (
                "Delegate one small bounded action and keep the approval and "
                "receipt it produces."
            ),
            "unknown": (
                "Write down what you believe this system is allowed to do, "
                "then check it against its permissions."
            ),
        },
    ),
    FoundationDefinition(
        capability=FoundationCapability.SAFE_CHANGE_RECOVERY,
        user_job=(
            "Improvements do not silently destroy what works."
        ),
        observable_evidence=(
            "preview",
            "snapshot or backup",
            "apply receipt",
            "verification",
            "demonstrated rollback",
        ),
        safety_boundary=(
            "Diagnosis never mutates; if recovery cannot be guaranteed, "
            "adaptation is not automated."
        ),
        negative_rules=(
            NegativeRule(
                rule_id="diagnosis-never-mutates",
                statement="Diagnosis never mutates anything in the person's system.",
            ),
            NegativeRule(
                rule_id="no-guaranteed-recovery-no-automated-adaptation",
                statement=(
                    "If recovery cannot be guaranteed, adaptation is not "
                    "automated; diagnosis offers no adaptation entry point."
                ),
            ),
        ),
        outcome_probe_patterns=("rollback-demonstrated", "recovery-demonstrated"),
        configuration_probe_patterns=("backup-config", "snapshot-present"),
        boundary_probe_patterns=("change-preview-observed", "apply-receipt-observed"),
        overbroad_probe_patterns=("unapproved-change", "change-without-recovery"),
        practical_implication=(
            "Proven recovery is what lets you improve the system without "
            "gambling the parts that already work."
        ),
        next_moves={
            "working": (
                "Keep the demonstrated rollback path documented next to the "
                "thing it protects."
            ),
            "partial": (
                "Take one existing backup and actually restore from it to "
                "prove the path works."
            ),
            "not-demonstrated": (
                "Before the next change, make a snapshot and rehearse "
                "rolling one file back."
            ),
            "unknown": (
                "Find out what, if anything, would restore this system after "
                "a bad change."
            ),
        },
    ),
    FoundationDefinition(
        capability=FoundationCapability.HONEST_HEALTH_OBSERVABILITY,
        user_job=(
            "The person can tell what is working, partial, disabled, broken, "
            "or unknown and why."
        ),
        observable_evidence=(
            "live checks",
            "last-run information",
            "failure evidence",
        ),
        safety_boundary=(
            "File presence alone never means healthy, and uncertainty "
            "remains visible."
        ),
        negative_rules=(
            NegativeRule(
                rule_id="file-presence-never-means-healthy",
                statement="File presence alone never means healthy.",
            ),
            NegativeRule(
                rule_id="uncertainty-remains-visible",
                statement=(
                    "Uncertainty remains visible; an instrument that could "
                    "not check is reported, never hidden or counted as fine."
                ),
            ),
        ),
        outcome_probe_patterns=("live-check", "last-run-observed", "failure-reported"),
        configuration_probe_patterns=(
            "skills-present",
            "instructions-present",
            "settings-present",
            "installation-shape",
        ),
        boundary_probe_patterns=("health-visibility-observed",),
        overbroad_probe_patterns=("unchecked-health-claim",),
        practical_implication=(
            "Knowing what is actually working, and why, is what separates a "
            "system you trust from one you hope about."
        ),
        next_moves={
            "working": (
                "Keep the live checks in the loop you already use, so "
                "failures keep surfacing."
            ),
            "partial": (
                "Add a last-run marker to the piece you can least tell is "
                "working."
            ),
            "not-demonstrated": (
                "Run one live check against the piece you rely on most and "
                "keep its result."
            ),
            "unknown": (
                "Pick the piece you rely on most and find any signal of when "
                "it last actually ran."
            ),
        },
    ),
    FoundationDefinition(
        capability=FoundationCapability.COMPOUNDING_CORRECTABILITY,
        user_job=(
            "Outcomes and corrections can improve future work while the "
            "person controls what becomes permanent."
        ),
        observable_evidence=(
            "an improvement linked to an outcome",
            "explicit promotion",
            "version history",
            "reversibility",
        ),
        safety_boundary=(
            "No autonomous permanent self-modification, and one system's "
            "pattern is not treated as universal truth."
        ),
        negative_rules=(
            NegativeRule(
                rule_id="no-autonomous-permanent-self-modification",
                statement="No autonomous permanent self-modification.",
            ),
            NegativeRule(
                rule_id="one-systems-pattern-is-not-universal-truth",
                statement=(
                    "One system's pattern is not treated as universal truth; "
                    "every finding stays scoped to this system and job."
                ),
            ),
        ),
        outcome_probe_patterns=(
            "explicit-promotion-observed",
            "correction-applied",
            "improvement-linked-outcome",
        ),
        configuration_probe_patterns=("version-history-present",),
        boundary_probe_patterns=("promotion-approval-observed", "reversibility-observed"),
        overbroad_probe_patterns=("autonomous-self-modification", "auto-promotion"),
        practical_implication=(
            "Controlled compounding is how the system gets better for you "
            "without changing itself behind your back."
        ),
        next_moves={
            "working": (
                "Review the version history after the next promotion to "
                "confirm it stays reversible."
            ),
            "partial": (
                "Promote one proven improvement explicitly and record the "
                "outcome it is linked to."
            ),
            "not-demonstrated": (
                "Take one correction you made recently and promote it "
                "explicitly, with a way back."
            ),
            "unknown": (
                "Find out whether anything in this system changes itself, "
                "and who approves it."
            ),
        },
    ),
)

#: Capability → definition, exactly one per member (checked below and tested).
FOUNDATION_DEFINITIONS: Mapping[FoundationCapability, FoundationDefinition] = MappingProxyType(
    {definition.capability: definition for definition in _DEFINITIONS}
)

if set(FOUNDATION_DEFINITIONS) != set(FoundationCapability):  # pragma: no cover
    raise AssertionError("FOUNDATION_DEFINITIONS must cover exactly the eight capabilities")


def definition_for(capability: FoundationCapability) -> FoundationDefinition:
    """The definition for one Foundation Capability. Total over the enum."""
    return FOUNDATION_DEFINITIONS[capability]


def negative_rule_ids() -> frozenset[str]:
    """Every encoded negative-rule id (each one has a fixture test)."""
    return frozenset(
        rule.rule_id
        for definition in FOUNDATION_DEFINITIONS.values()
        for rule in definition.negative_rules
    )
