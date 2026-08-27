"""Local-only S1/S2/S4 privacy gate for contribution abstractions.

Candidate identity comes from the existing proposal/evidence vocabulary, never
from inspected bytes.  Sensitive source text is classified in memory and then
discarded: previews contain category labels and a closed Capability Card only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, final

from pydantic import ConfigDict, Field, StrictBool, ValidationError, model_validator

from capability_exchange.boundary.serialization import InventoriedModel
from capability_exchange.cards.model import (
    CapabilityCard,
    CardDependencies,
    CardProvenance,
    CardRights,
    CardTestStatus,
)
from capability_exchange.cards.validation import require_valid_card, scan_text
from capability_exchange.jobs import CandidateJobProposal

LOOKS_PERSONAL_CONFIRMATION = (
    "This looks personal. Build only the abstraction shown."
)
NON_PERSONAL_CONFIRMATION = "Build only the structured abstraction shown."
DECLINE_FILE = "contribution-candidate-declines.json"
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class SensitiveCategory(StrEnum):
    """Closed labels safe to display without repeating matched private text."""

    HEALTH = "health"
    FAMILY_CARE = "family-or-care"
    FINANCES = "finances"
    PERSONNEL = "personnel"
    NAMED_COMPANY = "named-company"


_CATEGORY_PATTERNS: dict[SensitiveCategory, tuple[re.Pattern[str], ...]] = {
    SensitiveCategory.HEALTH: (
        re.compile(
            r"\b(?:cancer|oncolog\w*|chemotherap\w*|medicat\w*|prescription|"
            r"diagnos\w*|doctor|patient|hospital|therapy|therapist|medical|"
            r"health|dose|dosage|symptom|treatment)\b",
            re.I,
        ),
    ),
    SensitiveCategory.FAMILY_CARE: (
        re.compile(
            r"\b(?:family|caregiv\w*|care\s+(?:plan|reminder|routine)|daughter|son|"
            r"child|children|mother|father|parent|spouse|husband|wife|partner|"
            r"relative|school\s+(?:run|pickup))\b",
            re.I,
        ),
    ),
    SensitiveCategory.FINANCES: (
        re.compile(
            r"\b(?:financ\w*|bank|account\s+balance|mortgage|debt|salary|payroll|"
            r"credit\s+card|tax(?:es)?|invoice|investment|portfolio|budget|rent)\b",
            re.I,
        ),
    ),
    SensitiveCategory.PERSONNEL: (
        re.compile(
            r"\b(?:personnel|employee|colleague|manager|performance\s+review|"
            r"hiring|hire|firing|fire|human\s+resources|hr\s|staff|candidate|"
            r"promotion|disciplin\w*)\b",
            re.I,
        ),
    ),
    SensitiveCategory.NAMED_COMPANY: (
        re.compile(
            r"\b(?:[A-Z][A-Za-z0-9&'.-]*\s+){0,4}"
            r"(?:Ltd|Limited|Inc|LLC|Corp|Corporation|PLC|GmbH|Company|Co\.)\b"
        ),
        re.compile(r"\b[A-Z][a-z]+(?:AI|HQ|Cloud|Labs|Works|Soft)\b"),
        re.compile(
            r"\b(?:at|for|from|with|client|customer|employer|company)\s+"
            r"[A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,3}\b"
        ),
    ),
}

_RAW_SOURCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\braw\s+(?:vault\s+)?(?:prose|text|notes?|prompt|history|source)\b", re.I),
    re.compile(r"\bsource\s+file\s+(?:contents?|body|text)\b", re.I),
    re.compile(r"\b(?:literal|verbatim)\s+(?:skill|workflow|file|prompt)\s+(?:code|text)\b", re.I),
    re.compile(r"(?:^|\s)(?:def|class|function)\s+[A-Za-z_][A-Za-z0-9_]*\s*[(:]"),
)

_PATTERN_LABELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "recurring-skill-workflows": (
        "recurring-workflow-pattern",
        ("repeatable workflow shape", "inferred non-raw evidence state"),
    ),
    "instruction-guided-work": (
        "standing-instruction-pattern",
        ("standing instruction shape", "inferred non-raw evidence state"),
    ),
    "tool-configuration-upkeep": (
        "configuration-upkeep-pattern",
        ("configuration upkeep shape", "inferred non-raw evidence state"),
    ),
    "recent-activity-follow-through": (
        "recurring-follow-through-pattern",
        ("recurring follow-through shape", "inferred non-raw evidence state"),
    ),
}


@final
class ContributionCandidate(InventoriedModel):
    """Safe local candidate projection; it contains no proposal prose/reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_digest: str = Field(pattern=_DIGEST_PATTERN)
    pattern_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
    source_kind: Literal["inferred-proposal", "user-initiated"]
    retained_primitives: tuple[str, ...]


@final
class ContributionPrivacyPreview(InventoriedModel):
    """Display-safe abstraction accounting; no matched value is representable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_digest: str = Field(pattern=_DIGEST_PATTERN)
    looks_personal: StrictBool
    sensitive_categories: tuple[SensitiveCategory, ...]
    retained: tuple[str, ...]
    removed: tuple[str, ...]
    confirmation_statement: str
    abstract_card: CapabilityCard


@final
class ContributionDeclineLedger(InventoriedModel):
    """Only durable S2 state: opaque candidate digests and a schema version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_digests: tuple[str, ...]
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def _bounded_unique_digests(self) -> ContributionDeclineLedger:
        if (
            len(self.candidate_digests) > 512
            or len(set(self.candidate_digests)) != len(self.candidate_digests)
            or any(re.fullmatch(_DIGEST_PATTERN, item) is None for item in self.candidate_digests)
        ):
            raise ValueError("contribution decline digests are invalid")
        return self

    @classmethod
    def empty(cls) -> ContributionDeclineLedger:
        return cls(candidate_digests=())


def _candidate_digest(candidate_id: str) -> str:
    material = b"dex-contribution-candidate-v1\0" + candidate_id.encode("utf-8")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def candidate_from_proposal(proposal: CandidateJobProposal) -> ContributionCandidate:
    """Project a proposal through identifiers/states only, never prose/references."""

    pattern_id, retained = _PATTERN_LABELS.get(
        proposal.candidate_id,
        (
            "other-reusable-pattern",
            ("user-selected workflow shape", "inferred non-raw evidence state"),
        ),
    )
    return ContributionCandidate(
        candidate_digest=_candidate_digest(proposal.candidate_id),
        pattern_id=pattern_id,
        source_kind="inferred-proposal",
        retained_primitives=retained,
    )


def user_initiated_candidate() -> ContributionCandidate:
    """Fallback for an explicit share request with no adapter proposal."""

    return ContributionCandidate(
        candidate_digest=_candidate_digest("user-initiated-reusable-pattern"),
        pattern_id="user-initiated-pattern",
        source_kind="user-initiated",
        retained_primitives=(
            "user-selected workflow shape",
            "structured Card declarations",
        ),
    )


def _strings(value: object) -> tuple[str, ...]:
    strings: list[str] = []

    def collect(item: object) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, Mapping):
            for nested in item.values():
                collect(nested)
        elif isinstance(item, (tuple, list)):
            for nested in item:
                collect(nested)

    collect(value)
    return tuple(strings)


def detect_sensitive_categories(value: object) -> tuple[SensitiveCategory, ...]:
    """Classify locally and return labels only; matched strings never escape."""

    strings = _strings(value)
    result = tuple(
        category
        for category in SensitiveCategory
        if any(pattern.search(text) for text in strings for pattern in _CATEGORY_PATTERNS[category])
    )
    return result


def _safe_abstract_card(
    candidate: ContributionCandidate,
    card: CapabilityCard,
    *,
    stable_card_id: str | None = None,
) -> CapabilityCard:
    """Replace all prose as fields, not substrings; no source fragment survives."""

    return CapabilityCard(
        # Keep this below the Card scanner's generic high-entropy-token bound.
        # Candidate identity remains in the separate opaque preview digest.
        card_id=stable_card_id or "reusable-pattern-card",
        version=card.version,
        selected_job=candidate.pattern_id,
        method=(
            "Run a recurring, consent-led check-in and escalate only through "
            "the participant's chosen route."
        ),
        conditions=("When a recurring check-in has been explicitly requested",),
        desired_outcome=(
            "A repeatable check-in completes with clear, user-chosen follow-up."
        ),
        boundaries=(
            "Do not include names, conditions, schedules, organisations, or source material.",
        ),
        evidence_claim=(
            "Reported reusable pattern only; effectiveness requires local verification."
        ),
        permissions=card.permissions,
        dependencies=CardDependencies(items=()),
        provenance=CardProvenance(
            method_basis="Abstracted from a locally selected reusable workflow shape",
            evidence_basis="Inferred from non-raw evidence state only",
            adapter_id="local-non-raw-evidence",
            evidence_mode="inferred",
        ),
        rights=CardRights(
            license_status="Rights require fresh contributor review",
            rights_attested=card.rights.rights_attested,
        ),
        test_status=CardTestStatus(
            status=card.test_status.status,
            summary="Original context removed; verify this abstraction independently",
        ),
        limitations=(
            "The abstraction deliberately omits all person- and organisation-specific context.",
        ),
    )


class ContributionPrivacyGate:
    """Build a safe abstraction preview and guard the later disclosure seam."""

    def preview(
        self,
        candidate: ContributionCandidate,
        payload: CapabilityCard | Mapping[str, Any],
        *,
        stable_card_id: str | None = None,
    ) -> ContributionPrivacyPreview:
        try:
            if isinstance(payload, Mapping):
                unknown = set(payload) - set(CapabilityCard.model_fields)
                if unknown:
                    raise ValueError("raw or extra fields are forbidden")
                card = CapabilityCard.model_validate(payload)
            elif isinstance(payload, CapabilityCard):
                card = CapabilityCard.model_validate(payload.model_dump(mode="python"))
            else:
                raise TypeError("payload is not a Capability Card")
        except (TypeError, ValueError, ValidationError) as exc:
            raise ValueError(
                "contribution privacy preview requires one closed structured Capability Card"
            ) from exc

        plain = card.model_dump(mode="python")
        categories = detect_sensitive_categories(plain)
        content_findings = scan_text(plain, path="candidate")
        raw_source = any(
            pattern.search(text)
            for text in _strings(plain)
            for pattern in _RAW_SOURCE_PATTERNS
        )
        looks_personal = bool(categories or content_findings or raw_source)
        if looks_personal:
            abstract_card = require_valid_card(
                _safe_abstract_card(
                    candidate,
                    card,
                    stable_card_id=stable_card_id,
                )
            )
            retained = (
                "closed Capability Card structure",
                "version number",
                "permission choices",
                "test-state label",
                "inferred non-raw evidence basis",
            )
            removed = (
                "all source prose, names, schedules, organisations, and file material",
                *(f"sensitive category: {category.value}" for category in categories),
            )
            confirmation = LOOKS_PERSONAL_CONFIRMATION
        else:
            abstract_card = require_valid_card(card)
            retained = ("all validated structured Capability Card fields",)
            removed = ("raw source files and uninventoried fields",)
            confirmation = NON_PERSONAL_CONFIRMATION
        return ContributionPrivacyPreview(
            candidate_digest=candidate.candidate_digest,
            looks_personal=looks_personal,
            sensitive_categories=categories,
            retained=retained,
            removed=removed,
            confirmation_statement=confirmation,
            abstract_card=abstract_card,
        )

    def require_minimized(self, card: CapabilityCard) -> CapabilityCard:
        """Refuse sensitive or raw-looking text at the disclosure boundary."""

        validated = require_valid_card(card)
        plain = validated.model_dump(mode="python")
        if (
            detect_sensitive_categories(plain)
            or scan_text(plain, path="disclosure")
            or any(
                pattern.search(text)
                for text in _strings(plain)
                for pattern in _RAW_SOURCE_PATTERNS
            )
        ):
            raise ValueError("contribution disclosure still looks personal or raw")
        return validated


def _has_symlinked_ancestor(path: Path) -> bool:
    candidate = path
    while candidate != candidate.parent:
        if candidate.is_symlink():
            return True
        candidate = candidate.parent
    return False


class ContributionDeclineStore:
    """Durable permanent suppression with no candidate prose or metadata."""

    def __init__(self, path: Path, *, inspected_roots: tuple[Path, ...] = ()) -> None:
        self.path = path.expanduser().resolve(strict=False)
        for raw_root in inspected_roots:
            root = raw_root.expanduser().resolve(strict=False)
            if self.path == root or self.path.is_relative_to(root):
                raise ValueError("contribution decline storage must stay outside inspected roots")

    def _load(self) -> ContributionDeclineLedger:
        if not self.path.exists():
            return ContributionDeclineLedger.empty()
        if self.path.is_symlink() or _has_symlinked_ancestor(self.path.parent):
            raise ValueError("contribution decline storage path is unsafe")
        try:
            raw = self.path.read_bytes()
            if len(raw) > 64 * 1024:
                raise ValueError("contribution decline storage is too large")
            return ContributionDeclineLedger.model_validate_json(raw)
        except (OSError, ValidationError, ValueError) as exc:
            raise ValueError("contribution decline storage is invalid") from exc

    def is_declined(self, candidate: ContributionCandidate) -> bool:
        return candidate.candidate_digest in self._load().candidate_digests

    def decline(self, candidate: ContributionCandidate) -> None:
        existing = self._load()
        if candidate.candidate_digest in existing.candidate_digests:
            return
        updated = ContributionDeclineLedger(
            candidate_digests=tuple(
                sorted((*existing.candidate_digests, candidate.candidate_digest))
            )
        )
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if _has_symlinked_ancestor(self.path.parent) or self.path.is_symlink():
            raise ValueError("contribution decline storage path is unsafe")
        payload = json.dumps(
            updated.dump_for_storage(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        descriptor, raw_temp = tempfile.mkstemp(
            prefix=".contribution-declines-",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(raw_temp)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        if self._load() != updated:
            raise ValueError("contribution decline storage read-back did not match")
