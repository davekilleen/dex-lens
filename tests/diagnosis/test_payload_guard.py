"""The wire guard refuses absolute-path SHAPE, never lawful relative references.

Finding B3 (2026-09-03 adversarial review): ``ABSOLUTE_PATH`` matched its
prefixes anywhere in a string, so a vault containing any folder named
``private``, ``home`` or ``Users`` below the root could never be diagnosed —
its lawful relative references, accepted by provenance validation and produced
verbatim by the snapshot adapter, were refused as hostile content forever.

Finding C4: the vocabulary missed real absolute home and system roots
(``/root/``, ``/srv/``, ``/opt/``, ``/Volumes/``, ``/var/home/``) while bare
``/var/`` and ``/tmp/`` must stay out — macOS temporary directories live under
``/var/folders/...`` and Linux test fixtures under ``/tmp/...``, and the
replay and MCP result paths depend on those strings passing.
"""

from __future__ import annotations

import pytest

from capability_exchange.diagnosis.payload_guard import (
    HostilePayloadError,
    refuse_hostile_payload,
)
from capability_exchange.diagnosis.provenance import relative_reference_rejection_reason

# The three shapes from the finding: every one is a lawful vault-relative
# reference (provenance validation accepts it, the snapshot adapter produces
# it verbatim), yet each carries a guarded prefix mid-path.
LAWFUL_NESTED_REFERENCES = (
    "notes/private/journal.md",
    "dotfiles/home/config.md",
    "sync/Users/list.md",
)

ABSOLUTE_HOME_SHAPES = (
    "/Users/invented-owner/vault/note.md",
    "/home/invented-owner/notes/journal.md",
    "/private/var/invented/thing.md",
    "/root/.config/invented.md",
    "/srv/invented-share/data.md",
    "/opt/invented-tool/config.md",
    "/Volumes/InventedDrive/vault/note.md",
    "/var/home/invented-owner/notes/journal.md",
)


@pytest.mark.parametrize("reference", LAWFUL_NESTED_REFERENCES)
def test_provenance_accepts_the_nested_relative_references(reference: str) -> None:
    """The premise of B3: these references lawfully cross the trust boundary."""

    assert relative_reference_rejection_reason(reference) is None


@pytest.mark.parametrize("reference", LAWFUL_NESTED_REFERENCES)
def test_guard_passes_every_relative_reference_provenance_accepts(reference: str) -> None:
    refuse_hostile_payload(reference)
    refuse_hostile_payload({"relative_reference": reference})


@pytest.mark.parametrize("path", ABSOLUTE_HOME_SHAPES)
def test_guard_refuses_a_standalone_absolute_path(path: str) -> None:
    with pytest.raises(HostilePayloadError) as caught:
        refuse_hostile_payload(path)
    assert caught.value.required_step == "remove_absolute_path"


@pytest.mark.parametrize("path", ABSOLUTE_HOME_SHAPES)
def test_guard_refuses_an_absolute_path_embedded_after_a_space(path: str) -> None:
    """A reason that mentions an absolute path is still refused."""

    with pytest.raises(HostilePayloadError):
        refuse_hostile_payload(f"seen in {path} during the invented run")


@pytest.mark.parametrize(
    "text",
    [
        '"/Users/invented-owner/vault/note.md"',
        "'/home/invented-owner/notes.md'",
        "`/var/home/invented-owner/notes.md`",
        "(see /root/.config/invented.md)",
        "[/srv/invented-share/data.md",
        "path=/opt/invented-tool/config.md",
        "location:/Volumes/InventedDrive/note.md",
        "line one\n/home/invented-owner/notes.md",
    ],
)
def test_guard_refuses_an_absolute_path_after_a_text_boundary(text: str) -> None:
    with pytest.raises(HostilePayloadError):
        refuse_hostile_payload(text)


def test_guard_refuses_a_windows_drive_path() -> None:
    with pytest.raises(HostilePayloadError):
        refuse_hostile_payload("C:\\Invented\\vault\\note.md")


def test_guard_passes_macos_temporary_directory_strings() -> None:
    """C4 keeps bare /var/ out of the vocabulary on purpose.

    macOS temporary directories live under ``/var/folders/...``; the replay
    and MCP result paths carry such strings and must keep passing.
    """

    refuse_hostile_payload("/var/folders/ab/invented0000gn/T/pytest-of-invented/item.md")
    refuse_hostile_payload("read from /var/folders/ab/invented0000gn/T/item.md")


def test_guard_passes_linux_tmp_strings() -> None:
    refuse_hostile_payload("/tmp/pytest-of-invented/pytest-0/test0/item.md")
    refuse_hostile_payload("wrote /tmp/pytest-of-invented/pytest-0/test0/item.md")
