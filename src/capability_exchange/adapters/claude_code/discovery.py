"""Deterministic whole-system discovery over an immutable local snapshot.

Only bounded structural facts enter the fingerprint. Commands, arguments,
environment blocks, URLs, note bodies, and credential-shaped keys are never
represented, so there is no later filtering step that could forget them.
"""

from __future__ import annotations

import json
import plistlib
import re
import tomllib
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

from capability_exchange.adapters.claude_code.contract import (
    AUTOMATION_SUFFIXES,
    INTEGRATION_BASENAMES,
    MCP_CONFIG_BASENAMES,
    RELEASE_BASENAMES,
)
from capability_exchange.adapters.claude_code.snapshot import (
    InspectionSnapshot,
    SnapshotEntry,
    reference_token,
)
from capability_exchange.diagnosis.observations import (
    EvidenceFingerprint,
    Observation,
    ObservationKind,
    OperationalState,
    SafeAttribute,
)
from capability_exchange.diagnosis.provenance import SourceClass
from capability_exchange.evidence import EvidenceItem, EvidenceState

__all__ = [
    "AUTOMATION_SUFFIXES",
    "INTEGRATION_BASENAMES",
    "MCP_CONFIG_BASENAMES",
    "RELEASE_BASENAMES",
    "discover_fingerprint",
]

_IDENTITY_CHAR = re.compile(r"[^a-z0-9._-]+")
_VERSION = re.compile(r"(?<![A-Za-z0-9])v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
_FRONTMATTER_DISABLED = re.compile(
    rb"(?im)^\s*(?:enabled\s*:\s*false|disabled\s*:\s*true|active\s*:\s*false)\s*$"
)
_PLIST_CALENDAR = re.compile(rb"<key>\s*StartCalendarInterval\s*</key>", re.IGNORECASE)
_PLIST_INTERVAL = re.compile(rb"<key>\s*StartInterval\s*</key>\s*<integer>\s*(\d+)", re.IGNORECASE)
_CRON_LINE = re.compile(r"^\s*([-\d*/,]+(?:\s+[-\d*/,]+){4})\s+(\S.*)$")
_INTEGRATION_PATH_PARTS = frozenset(
    {"integration", "integrations", "connection", "connections", "provider", "providers"}
)
_HEALTH_WORDS = frozenset({"doctor", "health", "smoke"})
_SAFE_PROBE_FOLDERS = frozenset({".scripts", "scripts", "checks", "health", "system"})


class _LiveStateLike(Protocol):
    kind: str
    identity: str
    operational_state: OperationalState


def _identity(value: str, *, fallback: str = "unnamed") -> str:
    collapsed = _IDENTITY_CHAR.sub("-", value.strip().lower()).strip("-._")
    return (collapsed or fallback)[:120]


def _label(value: str, *, fallback: str = "Unnamed") -> str:
    clean = " ".join(char for char in value.split() if char.isprintable())
    return (clean or fallback)[:160]


def _evidence(entry: SnapshotEntry, collected_at: datetime) -> EvidenceItem:
    return EvidenceItem(
        state=EvidenceState.OBSERVED,
        captured_at=collected_at,
        reference=(f"file:{reference_token(entry.relative_path)}#snap:{entry.keyed_digest}"),
    )


def _attribute(key: str, value: object) -> SafeAttribute | None:
    """Build a safe attribute, dropping untrusted text that cannot fit it."""
    try:
        return SafeAttribute(key=key, value=_label(str(value), fallback="unknown"))
    except ValueError:
        return None


def _attributes(*items: SafeAttribute | None) -> tuple[SafeAttribute, ...]:
    return tuple(item for item in items if item is not None)


def _entry_observation(
    entry: SnapshotEntry,
    collected_at: datetime,
    *,
    kind: ObservationKind,
    identity: str,
    label: str,
    operational_state: OperationalState,
    attributes: tuple[SafeAttribute, ...] = (),
) -> Observation:
    effective_state = (
        OperationalState.NOT_ASSESSED
        if entry.source.source_class is SourceClass.WORKING_COPY
        else operational_state
    )
    return Observation(
        kind=kind,
        identity=_identity(identity),
        label=_label(label),
        operational_state=effective_state,
        evidence=_evidence(entry, collected_at),
        provenance=entry.source,
        attributes=attributes,
    )


def _all_entries(snapshot: InspectionSnapshot) -> tuple[SnapshotEntry, ...]:
    return tuple(snapshot.entry_for(path) for path in snapshot.canonical_paths())


def _release_version(entry: SnapshotEntry) -> str | None:
    text = entry.content.decode("utf-8", "replace")
    if Path(entry.relative_path).name == "CHANGELOG.md":
        for line in text.splitlines()[:80]:
            if line.startswith("##"):
                match = _VERSION.search(line)
                if match is not None:
                    return match.group(0)
        return None
    match = _VERSION.search(text[:200])
    return match.group(0) if match is not None else None


def _release_observations(
    snapshot: InspectionSnapshot, collected_at: datetime
) -> tuple[Observation, ...]:
    entries = sorted(
        (
            entry
            for entry in _all_entries(snapshot)
            if Path(entry.relative_path).name in RELEASE_BASENAMES
        ),
        key=lambda entry: (
            {".dex-version": 0, "VERSION": 1, "CHANGELOG.md": 2}[Path(entry.relative_path).name],
            entry.relative_path.count("/"),
            entry.relative_path,
        ),
    )
    observations: list[Observation] = []
    for source_id in sorted({entry.source.source_id for entry in entries}):
        for entry in (item for item in entries if item.source.source_id == source_id):
            version = _release_version(entry)
            if version is None:
                continue
            observations.append(
                _entry_observation(
                    entry,
                    collected_at,
                    kind=ObservationKind.RELEASE,
                    identity="dex-core",
                    label="Dex Core release",
                    operational_state=OperationalState.INSTALLED,
                    attributes=_attributes(_attribute("release-id", version)),
                )
            )
            break
    return tuple(observations)


def _skill_observations(
    snapshot: InspectionSnapshot, collected_at: datetime
) -> tuple[Observation, ...]:
    observations: list[Observation] = []
    for entry in snapshot.entries_named("SKILL.md"):
        name = Path(entry.relative_path).parent.name
        state = (
            OperationalState.DISABLED
            if _FRONTMATTER_DISABLED.search(entry.content)
            else OperationalState.IMPLEMENTED
        )
        observations.append(
            _entry_observation(
                entry,
                collected_at,
                kind=ObservationKind.SKILL,
                identity=name,
                label=name,
                operational_state=state,
            )
        )
    return tuple(observations)


def _documents(entry: SnapshotEntry) -> tuple[object, ...]:
    basename = Path(entry.relative_path).name
    try:
        if basename == "config.toml":
            return (tomllib.loads(entry.content.decode("utf-8", "replace")),)
        return (json.loads(entry.content.decode("utf-8", "replace")),)
    except (UnicodeError, ValueError, tomllib.TOMLDecodeError):
        return ()


def _mapping_values_for_key(
    value: object, names: frozenset[str]
) -> Iterable[Mapping[object, object]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).replace("_", "").lower()
            if normalized in names and isinstance(item, Mapping):
                yield item
            yield from _mapping_values_for_key(item, names)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _mapping_values_for_key(item, names)


def _mcp_transport(config: object) -> str:
    if not isinstance(config, Mapping):
        return "unknown"
    if isinstance(config.get("command"), str):
        return "local-command"
    if any(isinstance(config.get(key), str) for key in ("url", "httpUrl", "serverUrl")):
        return "remote-http"
    transport = config.get("transport")
    if isinstance(transport, str) and transport.lower() in {"stdio", "http", "sse"}:
        return transport.lower()
    return "unknown"


def _mcp_observations(
    snapshot: InspectionSnapshot, collected_at: datetime
) -> tuple[Observation, ...]:
    observations: list[Observation] = []
    for entry in _all_entries(snapshot):
        if Path(entry.relative_path).name not in MCP_CONFIG_BASENAMES:
            continue
        for document in _documents(entry):
            for servers in _mapping_values_for_key(document, frozenset({"mcpservers"})):
                for raw_name, config in servers.items():
                    name = _label(str(raw_name))
                    observations.append(
                        _entry_observation(
                            entry,
                            collected_at,
                            kind=ObservationKind.MCP_SERVER,
                            identity=name,
                            label=name,
                            operational_state=OperationalState.DECLARED,
                            attributes=_attributes(_attribute("transport", _mcp_transport(config))),
                        )
                    )
    return tuple(observations)


def _action_count(value: object) -> int:
    if isinstance(value, list | tuple):
        return sum(_action_count(item) for item in value)
    if not isinstance(value, Mapping):
        return 0
    if any(key in value for key in ("command", "prompt", "url")):
        return 1
    return sum(_action_count(item) for item in value.values())


def _hook_observations(
    snapshot: InspectionSnapshot, collected_at: datetime
) -> tuple[Observation, ...]:
    observations: list[Observation] = []
    for entry in _all_entries(snapshot):
        if Path(entry.relative_path).name not in {"settings.json", ".claude.json"}:
            continue
        for document in _documents(entry):
            for hooks in _mapping_values_for_key(document, frozenset({"hooks"})):
                for raw_event, actions in hooks.items():
                    event = _label(str(raw_event))
                    count = _action_count(actions)
                    observations.append(
                        _entry_observation(
                            entry,
                            collected_at,
                            kind=ObservationKind.HOOK,
                            identity=event,
                            label=event,
                            operational_state=OperationalState.DECLARED,
                            attributes=_attributes(
                                _attribute("hook-event", event),
                                _attribute("tool-count", count),
                            ),
                        )
                    )
    return tuple(observations)


def _integration_provider_count(entry: SnapshotEntry) -> int:
    documents = _documents(entry)
    if documents:
        names: set[str] = set()
        for document in documents:
            for block in _mapping_values_for_key(
                document, frozenset({"providers", "integrations", "connections"})
            ):
                names.update(str(key) for key in block)
        return len(names)
    text = entry.content.decode("utf-8", "replace")
    in_block = False
    names = set()
    for line in text.splitlines():
        if re.match(r"^(providers|integrations|connections):\s*$", line, re.IGNORECASE):
            in_block = True
            continue
        if in_block and line and not line.startswith((" ", "\t")):
            in_block = False
        if in_block:
            match = re.match(r"^\s{2,}([A-Za-z0-9._-]+):", line)
            if match is not None:
                names.add(match.group(1))
    return len(names)


def _integration_observations(
    snapshot: InspectionSnapshot, collected_at: datetime
) -> tuple[Observation, ...]:
    entries = [
        entry
        for entry in _all_entries(snapshot)
        if Path(entry.relative_path).name in INTEGRATION_BASENAMES
        and _INTEGRATION_PATH_PARTS
        & {part.lower() for part in Path(entry.relative_path).parts[:-1]}
    ]
    observations: list[Observation] = []
    for source_id in sorted({entry.source.source_id for entry in entries}):
        source_entries = [entry for entry in entries if entry.source.source_id == source_id]
        provider_count = sum(_integration_provider_count(entry) for entry in source_entries)
        source_kinds = sorted(
            {Path(entry.relative_path).suffix.lstrip(".") for entry in source_entries}
        )
        observations.append(
            _entry_observation(
                min(
                    source_entries,
                    key=lambda item: (
                        item.relative_path.count("/"),
                        item.relative_path,
                    ),
                ),
                collected_at,
                kind=ObservationKind.INTEGRATION_REGISTRY,
                identity="local-integrations",
                label="Local integrations",
                operational_state=OperationalState.IMPLEMENTED,
                attributes=_attributes(
                    _attribute("provider-count", provider_count),
                    _attribute("source-kind", "+".join(source_kinds) or "unknown"),
                ),
            )
        )
    return tuple(observations)


def _plist_fact(entry: SnapshotEntry) -> tuple[str, str, str]:
    label = Path(entry.relative_path).stem
    schedule = "cadence-not-readable"
    run_at_load = "not-declared"
    try:
        document = plistlib.loads(entry.content)
    except (plistlib.InvalidFileException, ValueError, TypeError):
        document = None
    if isinstance(document, Mapping):
        raw_label = document.get("Label")
        if isinstance(raw_label, str):
            label = raw_label
        if "StartCalendarInterval" in document:
            schedule = "calendar-schedule"
        elif isinstance(document.get("StartInterval"), int):
            schedule = f"every-{document['StartInterval']}-seconds"
        run_at_load = "yes" if document.get("RunAtLoad") is True else "no"
    else:
        interval = _PLIST_INTERVAL.search(entry.content)
        if _PLIST_CALENDAR.search(entry.content):
            schedule = "calendar-schedule"
        elif interval is not None:
            schedule = f"every-{interval.group(1).decode('ascii')}-seconds"
    return label, schedule, run_at_load


def _automation_observations(
    snapshot: InspectionSnapshot,
    collected_at: datetime,
    live_states: tuple[_LiveStateLike, ...],
) -> tuple[Observation, ...]:
    observations: list[Observation] = []
    for entry in _all_entries(snapshot):
        path = Path(entry.relative_path)
        suffix = path.suffix.lower()
        basename = path.name
        is_crontab = basename in {"crontab", "crontab.txt"}
        if suffix not in AUTOMATION_SUFFIXES and not is_crontab:
            continue
        source_kind = "cron" if is_crontab else suffix.lstrip(".")
        if suffix == ".plist":
            label, schedule, run_at_load = _plist_fact(entry)
            attributes = _attributes(
                _attribute("schedule", schedule),
                _attribute("run-at-load", run_at_load),
                _attribute("source-kind", source_kind),
            )
            observations.append(
                _entry_observation(
                    entry,
                    collected_at,
                    kind=ObservationKind.AUTOMATION,
                    identity=label,
                    label=label,
                    operational_state=OperationalState.IMPLEMENTED,
                    attributes=attributes,
                )
            )
        elif suffix == ".cron" or is_crontab:
            for index, line in enumerate(entry.content.decode("utf-8", "replace").splitlines()):
                match = _CRON_LINE.match(line)
                if match is None:
                    continue
                command_basename = Path(match.group(2).split()[0]).name
                label = command_basename or f"cron-job-{index + 1}"
                observations.append(
                    _entry_observation(
                        entry,
                        collected_at,
                        kind=ObservationKind.AUTOMATION,
                        identity=label,
                        label=label,
                        operational_state=OperationalState.IMPLEMENTED,
                        attributes=_attributes(
                            _attribute("schedule", match.group(1)),
                            _attribute("source-kind", source_kind),
                        ),
                    )
                )
        else:
            label = Path(entry.relative_path).stem
            observations.append(
                _entry_observation(
                    entry,
                    collected_at,
                    kind=ObservationKind.AUTOMATION,
                    identity=label,
                    label=label,
                    operational_state=OperationalState.IMPLEMENTED,
                    attributes=_attributes(_attribute("source-kind", source_kind)),
                )
            )

    live_by_key = {(state.kind, _identity(state.identity)): state for state in live_states}
    upgraded = []
    for observation in observations:
        if observation.provenance.source_class is SourceClass.WORKING_COPY:
            upgraded.append(observation)
            continue
        live = live_by_key.get((observation.kind.value, observation.identity))
        if live is None:
            upgraded.append(observation)
            continue
        upgraded.append(
            observation.model_copy(update={"operational_state": live.operational_state})
        )
    return tuple(upgraded)


def _health_and_recovery_observations(
    snapshot: InspectionSnapshot, collected_at: datetime
) -> tuple[Observation, ...]:
    observations: list[Observation] = []
    for entry in _all_entries(snapshot):
        path = Path(entry.relative_path)
        parent_parts = {part.lower() for part in path.parts[:-1]}
        if not parent_parts & _SAFE_PROBE_FOLDERS:
            continue
        stem = _identity(path.stem)
        words = frozenset(stem.replace("_", "-").split("-"))
        if words & _HEALTH_WORDS:
            observations.append(
                _entry_observation(
                    entry,
                    collected_at,
                    kind=ObservationKind.HEALTH_CHECK,
                    identity=stem,
                    label=path.stem,
                    operational_state=OperationalState.IMPLEMENTED,
                    attributes=_attributes(
                        _attribute("source-kind", path.suffix.lstrip(".") or "file")
                    ),
                )
            )
        if "restore" in words and words & {"proof", "check", "test", "verify"}:
            observations.append(
                _entry_observation(
                    entry,
                    collected_at,
                    kind=ObservationKind.RECOVERY_PROOF,
                    identity=stem,
                    label=path.stem,
                    operational_state=OperationalState.IMPLEMENTED,
                    attributes=_attributes(
                        _attribute("source-kind", path.suffix.lstrip(".") or "file")
                    ),
                )
            )
    return tuple(observations)


def _fold_exact_duplicates(observations: Iterable[Observation]) -> tuple[Observation, ...]:
    by_key: dict[tuple[ObservationKind, str, str], Observation] = {}
    for observation in sorted(
        observations,
        key=lambda item: (
            item.kind.value,
            item.identity,
            item.provenance.source_id,
            item.evidence.reference,
        ),
    ):
        by_key.setdefault(
            (
                observation.kind,
                observation.identity,
                observation.provenance.source_id,
            ),
            observation,
        )
    return tuple(
        by_key[key] for key in sorted(by_key, key=lambda item: (item[0].value, item[1], item[2]))
    )


def _render_limits(
    snapshot: InspectionSnapshot, live_states: tuple[_LiveStateLike, ...]
) -> tuple[str, ...]:
    limits = [
        "Configured MCP doorways do not prove that their tools or outcomes work.",
        "Files describing scheduled work do not prove that the operating system loaded or ran it.",
    ]
    unreadable_configs = sum(
        1
        for entry in _all_entries(snapshot)
        if Path(entry.relative_path).name in MCP_CONFIG_BASENAMES and not _documents(entry)
    )
    if unreadable_configs:
        noun = "file" if unreadable_configs == 1 else "files"
        limits.append(
            f"{unreadable_configs} MCP configuration {noun} could not be parsed; "
            "its declarations were not assessed."
        )
    if not snapshot.complete:
        limits.append(
            "The approved scope was only partly captured because collection bounds were reached."
        )
    if not live_states:
        limits.append("Live operating-system state was not assessed.")
    return tuple(limits)


def discover_fingerprint(
    snapshot: InspectionSnapshot,
    *,
    collected_at: datetime,
    live_states: tuple[_LiveStateLike, ...] = (),
) -> EvidenceFingerprint:
    """Build one local-only fingerprint from the approved immutable snapshot."""
    observations = (
        *_release_observations(snapshot, collected_at),
        *_skill_observations(snapshot, collected_at),
        *_mcp_observations(snapshot, collected_at),
        *_hook_observations(snapshot, collected_at),
        *_integration_observations(snapshot, collected_at),
        *_automation_observations(snapshot, collected_at, live_states),
        *_health_and_recovery_observations(snapshot, collected_at),
    )
    return EvidenceFingerprint(
        adapter_id="claude-code-local",
        collected_at=collected_at,
        observations=_fold_exact_duplicates(observations),
        limits=_render_limits(snapshot, live_states),
    )
