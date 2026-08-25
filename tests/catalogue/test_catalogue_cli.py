"""`dex-lens catalogue` and `dex-lens brief`, exercised as a caller runs them.

Both of the bugs these tests were written for reached a pull request: the
`--offline` path called a method the store does not have, and `--since`
was answered after the output format rather than before it, so a recurring
check asking for JSON printed the whole catalogue every run.

Neither was subtle. Both survived because the tests underneath went straight
to the rendering functions and never ran the commands. A command with a flag
nobody invokes is a command that does not work.
"""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import sign_envelope, unsigned_envelope

from capability_exchange.catalogue import cli, fetch
from capability_exchange.catalogue.delta import CatalogueSnapshot, CatalogueSnapshotStore
from capability_exchange.catalogue.subscription import CatalogueSubscriptionStore
from capability_exchange.catalogue.v2 import KeyRing, VerifiedCatalogueStore

KEY_ID = "dex-core-2026-08-test"


class _NetworkTouched(AssertionError):
    """Raised in place of any real request these tests must never make."""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this file is allowed to reach the public catalogue host.

    The fetcher binds `urlopen` as a default argument, so patching the module
    attribute alone would leave a real request possible; the fetcher itself is
    replaced as well, which also makes "the URL was accepted" observable
    without anything leaving the machine.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise _NetworkTouched("the network was touched")

    class RefusingFetcher:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch(self, consent: object) -> None:
            raise _NetworkTouched("a fetch was attempted")

    monkeypatch.setattr(fetch, "urlopen", refuse)
    monkeypatch.setattr(cli, "ConsentedCatalogueFetcher", RefusingFetcher)


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    seed = b"dex-lens-catalogue-cli-test-key!"
    assert len(seed) == 32
    return Ed25519PrivateKey.from_private_bytes(seed)


@pytest.fixture
def keyring(signing_key: Ed25519PrivateKey) -> KeyRing:
    raw = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return KeyRing({KEY_ID: base64.b64encode(raw).decode("ascii")})


@pytest.fixture
def cached_catalogue(
    tmp_path: Path,
    signing_key: Ed25519PrivateKey,
    keyring: KeyRing,
    monkeypatch: pytest.MonkeyPatch,
) -> VerifiedCatalogueStore:
    """A store holding one genuinely verified catalogue, version 7."""
    from capability_exchange.catalogue.v2 import verify_catalogue_envelope

    storage = tmp_path / "state"
    storage.mkdir()
    store = VerifiedCatalogueStore(storage)
    raw = sign_envelope(unsigned_envelope(version=7, key_id=KEY_ID), signing_key)
    # unsigned_envelope stamps `produced_at` at its own NOW, so verify against
    # that same moment rather than the wall clock.
    from tests.catalogue.test_v2_verifier import NOW

    store.save_verified(verify_catalogue_envelope(raw, keyring=keyring, now=NOW))

    monkeypatch.setattr(cli, "default_lens_app_storage", lambda: storage)
    monkeypatch.setattr(cli, "default_keyring", lambda: keyring)
    return store


def _two_capability_payload() -> dict:
    """The fixture catalogue with a second entry, for narrowing tests."""
    payload = unsigned_envelope(version=7, key_id=KEY_ID)
    second = json.loads(json.dumps(payload["catalogue"]["capabilities"][0]))
    second["capability_id"] = "dex-second-thing"
    second["title"] = "Second Thing"
    payload["catalogue"]["capabilities"].append(second)
    return payload


@pytest.fixture
def cached_two_capabilities(
    tmp_path: Path,
    signing_key: Ed25519PrivateKey,
    keyring: KeyRing,
    monkeypatch: pytest.MonkeyPatch,
) -> VerifiedCatalogueStore:
    """A verified catalogue with two entries, so narrowing can exclude one."""
    from tests.catalogue.test_v2_verifier import NOW

    from capability_exchange.catalogue.v2 import verify_catalogue_envelope

    payload = _two_capability_payload()
    storage = tmp_path / "state"
    storage.mkdir()
    store = VerifiedCatalogueStore(storage)
    raw = sign_envelope(payload, signing_key)
    store.save_verified(verify_catalogue_envelope(raw, keyring=keyring, now=NOW))

    monkeypatch.setattr(cli, "default_lens_app_storage", lambda: storage)
    monkeypatch.setattr(cli, "default_keyring", lambda: keyring)
    return store


class TestOffline:
    def test_it_reads_the_cached_catalogue(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The path that shipped calling a method the store does not have."""
        assert cli.catalogue_main(["--offline"]) == 0

        out = capsys.readouterr().out
        assert "verified catalogue version 7" in out
        assert "Dex capability catalogue" in out

    def test_nothing_cached_is_refused_not_crashed(
        self, tmp_path: Path, keyring: KeyRing, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        storage = tmp_path / "empty"
        storage.mkdir()
        monkeypatch.setattr(cli, "default_lens_app_storage", lambda: storage)
        monkeypatch.setattr(cli, "default_keyring", lambda: keyring)

        assert cli.catalogue_main(["--offline"]) == 1

        captured = capsys.readouterr()
        assert "nothing to read offline" in captured.err
        assert captured.out == "", "a failed read must print nothing catalogue-shaped"

    def test_a_tampered_cache_is_refused(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Cached does not mean trusted: the signature is checked on the way out.

        A verified catalogue is written to disk and could be edited afterwards
        by anything with write access. Re-checking on read is the difference
        between "was signed once" and "is signed".
        """
        payload = json.loads(cached_catalogue.cache_path.read_text(encoding="utf-8"))
        envelope = json.loads(payload["verified_envelope_json"])
        envelope["catalogue"]["capabilities"][0]["title"] = "Tampered"
        payload["verified_envelope_json"] = json.dumps(envelope, sort_keys=True)
        cached_catalogue.cache_path.write_text(json.dumps(payload), encoding="utf-8")

        assert cli.catalogue_main(["--offline"]) == 1

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Tampered" not in captured.out


class TestSince:
    def test_an_unchanged_catalogue_prints_nothing(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A recurring check that speaks every run gets turned off."""
        assert cli.catalogue_main(["--offline", "--since", "7"]) == 0

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Nothing new" in captured.err

    def test_json_output_respects_since(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The bug: --json returned before --since was ever consulted."""
        assert cli.catalogue_main(["--offline", "--since", "7", "--json"]) == 0

        assert capsys.readouterr().out == ""

    def test_a_newer_catalogue_prints_and_says_it_is_not_a_delta(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--offline", "--since", "3"]) == 0

        captured = capsys.readouterr()
        assert "Dex capability catalogue" in captured.out
        assert "not a delta" in captured.err


class TestNarrowing:
    """A whole catalogue is the right default and the wrong thing to re-read.

    Once the person's jobs are known, the rest is context the assistant pays
    for and never uses. The failure that matters is narrowing to nothing and
    printing it: an empty digest reads as "Dex has nothing for you", which is
    a conclusion invented by a typo.
    """

    def test_jobs_narrows_to_that_job(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--offline", "--jobs", "remember-what-matters"]) == 0

        out = capsys.readouterr().out
        assert "narrowed to 1 of 1" in out
        assert "dex-durable-memory-provenance" in out

    def test_only_narrows_to_named_capabilities(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--offline", "--only", "dex-durable-memory-provenance"]) == 0

        assert "dex-durable-memory-provenance" in capsys.readouterr().out

    def test_an_unknown_job_is_refused_rather_than_narrowed_to_nothing(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--offline", "--jobs", "wash-the-car"]) == 1

        captured = capsys.readouterr()
        assert "Dex capability catalogue" not in captured.out
        assert "no such job" in captured.err
        assert "remember-what-matters" in captured.err, "say what is available"

    def test_an_unknown_capability_id_is_refused(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--offline", "--only", "no-such-thing"]) == 1

        assert "no such capability" in capsys.readouterr().err

    def test_narrowing_the_signed_json_is_refused(
        self, cached_catalogue: VerifiedCatalogueStore
    ) -> None:
        """--json is the published bytes; a narrowed one was never signed."""
        with pytest.raises(SystemExit) as refused:
            cli.catalogue_main(["--offline", "--json", "--only", "dex-durable-memory-provenance"])

        assert refused.value.code == 2


class TestSinceLast:
    """The recurring check: no version number to remember, and quiet by default.

    It answers with a per-entry delta rather than a version comparison,
    because "these two are new" is an answer and "the catalogue moved" is a
    chore. The delta is against what *this machine* has seen, which is the
    only thing it can honestly compare against.
    """

    def test_the_first_run_prints_everything_and_records_every_entry(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--offline", "--since-last"]) == 0

        captured = capsys.readouterr()
        assert "Dex capability catalogue" in captured.out
        assert "has not looked at the catalogue before" in captured.err
        assert _snapshot().fingerprints, "with nothing recorded the next run repeats itself"

    def test_the_next_run_stays_quiet_when_nothing_changed(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.catalogue_main(["--offline", "--since-last"])
        capsys.readouterr()

        assert cli.catalogue_main(["--offline", "--since-last"]) == 0

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Nothing new" in captured.err

    def test_an_ordinary_run_records_the_baseline_too(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Someone who ran the catalogue once should not be told about it again."""
        assert cli.catalogue_main(["--offline"]) == 0
        capsys.readouterr()

        assert _recorded_version() == 7
        assert cli.catalogue_main(["--offline", "--since-last"]) == 0
        assert capsys.readouterr().out == ""

    def test_a_new_capability_is_named_and_is_all_that_prints(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The whole point: what prints is the delta, not the catalogue."""
        _snapshot_of({"something-else-entirely": "0" * 64})

        assert cli.catalogue_main(["--offline", "--since-last"]) == 0

        captured = capsys.readouterr()
        assert "1 new" in captured.err
        assert "withdrawn" in captured.err, "an entry that vanished is also news"
        assert "narrowed to 1 of 1" in captured.out
        assert "dex-durable-memory-provenance" in captured.out

    def test_a_reworded_entry_counts_as_changed(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Better a cosmetic change reported than a real one dropped."""
        _snapshot_of({"dex-durable-memory-provenance": "f" * 64})

        assert cli.catalogue_main(["--offline", "--since-last"]) == 0

        captured = capsys.readouterr()
        assert "1 changed" in captured.err
        assert "dex-durable-memory-provenance" in captured.out

    def test_narrowing_away_the_change_says_so_rather_than_printing_nothing(
        self,
        cached_two_capabilities: VerifiedCatalogueStore,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Silence here would read as "nothing changed", which is false."""
        fingerprints = _current_fingerprints(_two_capability_payload())
        fingerprints["dex-durable-memory-provenance"] = "f" * 64
        _snapshot_of(fingerprints)

        assert cli.catalogue_main(["--offline", "--since-last", "--only", "dex-second-thing"]) == 0

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Nothing new inside that narrowing" in captured.err

    def test_a_withdrawn_capability_is_named_and_nothing_is_printed_to_read(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A digest of things that no longer exist is not a recommendation."""
        fingerprints = _current_fingerprints()
        fingerprints["dex-retired-thing"] = "b" * 64
        _snapshot_of(fingerprints)

        assert cli.catalogue_main(["--offline", "--since-last"]) == 0

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "dex-retired-thing" in captured.err
        assert "no longer published" in captured.err

    def test_json_prints_the_whole_signed_catalogue_and_says_so(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A narrowed envelope was never signed, so it is printed whole."""
        _snapshot_of({"dex-durable-memory-provenance": "f" * 64})

        assert cli.catalogue_main(["--offline", "--since-last", "--json"]) == 0

        captured = capsys.readouterr()
        assert captured.out.startswith("{")
        assert "not only what changed" in captured.err

    def test_two_ways_of_saying_since_are_refused_together(
        self, cached_catalogue: VerifiedCatalogueStore
    ) -> None:
        with pytest.raises(SystemExit) as refused:
            cli.catalogue_main(["--offline", "--since", "3", "--since-last"])

        assert refused.value.code == 2

    def test_an_unreadable_snapshot_costs_one_noisy_run_not_the_command(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Refusing to print a verified catalogue because a convenience file
        is corrupt would be the wrong trade every time."""
        store = _snapshot_store()
        store.app_storage.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{not json", encoding="utf-8")

        assert cli.catalogue_main(["--offline", "--since-last"]) == 0

        assert "Dex capability catalogue" in capsys.readouterr().out

    def test_a_recording_failure_does_not_fail_the_command(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A verified catalogue was already printed; a local convenience file
        failing to write is a thing to say, not a reason to fail."""

        def refuse(_self: CatalogueSubscriptionStore, **_kwargs: object) -> None:
            raise OSError("read-only file system")

        monkeypatch.setattr(CatalogueSubscriptionStore, "record_seen", refuse)

        assert cli.catalogue_main(["--offline"]) == 0
        assert "could not record catalogue version 7" in capsys.readouterr().err


def _subscription_store() -> CatalogueSubscriptionStore:
    return CatalogueSubscriptionStore(cli.default_lens_app_storage())


def _snapshot_store() -> CatalogueSnapshotStore:
    return CatalogueSnapshotStore(cli.default_lens_app_storage())


def _snapshot() -> CatalogueSnapshot:
    return _snapshot_store().load()


def _current_fingerprints(payload: dict | None = None) -> dict[str, str]:
    """The fingerprints of a catalogue as it stands, to vary one at a time."""
    from capability_exchange.catalogue.delta import entry_fingerprints
    from capability_exchange.catalogue.v2 import CatalogueV2

    envelope = payload or unsigned_envelope(version=7, key_id=KEY_ID)
    return dict(entry_fingerprints(CatalogueV2.model_validate(envelope["catalogue"])))


def _snapshot_of(fingerprints: dict[str, str]) -> None:
    """Plant a snapshot describing a catalogue this machine never saw."""
    store = _snapshot_store()
    store.app_storage.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"catalog_version": 6, "fingerprints": fingerprints}),
        encoding="utf-8",
    )


def _recorded_version() -> int | None:
    return _subscription_store().load().last_seen_catalog_version


class TestBrief:
    def test_it_prints_a_brief_for_a_known_capability(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        catalogue = unsigned_envelope(version=7, key_id=KEY_ID)["catalogue"]
        capability_id = catalogue["capabilities"][0]["capability_id"]

        assert cli.brief_main([capability_id, "--offline", "--why", "Because."]) == 0

        out = capsys.readouterr().out
        assert "Portable brief" in out
        assert "Because." in out

    def test_an_unknown_capability_fails_without_printing_a_brief(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.brief_main(["no-such-thing", "--offline"]) == 1

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "no-such-thing" in captured.err

    def test_out_writes_the_same_bytes_it_prints(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        catalogue = unsigned_envelope(version=7, key_id=KEY_ID)["catalogue"]
        capability_id = catalogue["capabilities"][0]["capability_id"]
        destination = tmp_path / "briefs" / "one.md"

        cli.brief_main([capability_id, "--offline", "--out", str(destination)])

        assert destination.read_text(encoding="utf-8") == capsys.readouterr().out


class TestPinnedUrl:
    """`--url` is pinned to the public Dex host, and says so instead of crashing.

    The pin is the point: an unpinned catalogue URL is a way to hand someone
    a list of changes to their system from a host they never chose. What was
    wrong was the delivery — a pydantic traceback, which reads as a broken
    tool rather than a refused request, and buries the reason under a stack.
    """

    REFUSED = [
        "http://example.com/x.json",
        "file:///etc/passwd",
        "not-a-url",
        "",
        "https://127.0.0.1:1/x",
        "https://heydex.ai.evil.example/catalogue.json",
        "https://heydex.ai/catalogue.json?who=dave",
        "https://user:pw@heydex.ai/catalogue.json",
    ]

    @pytest.mark.parametrize("url", REFUSED)
    def test_catalogue_refuses_in_words_and_never_tracebacks(
        self, url: str, no_network: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--url", url]) == 1

        captured = capsys.readouterr()
        assert captured.out == "", "a refused fetch prints nothing that reads as a catalogue"
        assert captured.err.startswith("dex-lens: ")
        assert "Traceback" not in captured.err
        assert "pydantic" not in captured.err.lower()
        assert "validation error" not in captured.err.lower()

    @pytest.mark.parametrize("url", REFUSED)
    def test_brief_refuses_the_same_way(
        self, url: str, no_network: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`brief` shares the fetch path, so it must share the refusal."""
        assert cli.brief_main(["dex-durable-memory-provenance", "--url", url]) == 1

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("dex-lens: ")
        assert "Traceback" not in captured.err

    def test_the_refusal_carries_the_reason_the_validator_gave(
        self, no_network: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--url", "https://127.0.0.1:1/x"]) == 1
        assert "pinned to the public Dex host" in capsys.readouterr().err

        assert cli.catalogue_main(["--url", "http://heydex.ai/catalogue.json"]) == 1
        assert "https" in capsys.readouterr().err

    def test_the_default_url_is_accepted_and_is_the_only_one_that_is(
        self, no_network: None
    ) -> None:
        """The pin stays: the default reaches the fetcher, everything else is
        refused before it. Proven against a fetcher that raises rather than a
        real request, so the assertion costs no egress."""
        from capability_exchange.catalogue.fetch import DEFAULT_CATALOGUE_URL

        with pytest.raises(_NetworkTouched):
            cli.catalogue_main(["--url", DEFAULT_CATALOGUE_URL])

    def test_the_help_says_the_host_is_pinned(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A flag that reads as configurable and is not teaches a wrong model."""
        for command in (cli.catalogue_main, cli.brief_main):
            with pytest.raises(SystemExit):
                command(["--help"])
            help_text = capsys.readouterr().out
            assert "pinned" in help_text
            assert "heydex.ai" in help_text


class TestBriefWritesNothingIntoWhatItDescribes:
    """`brief` says it changes nothing, so it must not land a file in the system.

    An `--out` inside the folder being inspected drops a file the person's
    assistant loads as a skill on its next run — guidance turning itself into
    an instruction, from a command whose help promises the opposite. The same
    containment guard `reports save --for` uses answers this one.
    """

    @pytest.fixture
    def inspected(self, tmp_path: Path) -> Path:
        root = tmp_path / "vault"
        (root / ".claude" / "skills").mkdir(parents=True)
        return root

    def _brief(self, *arguments: str) -> int:
        return cli.brief_main(["dex-durable-memory-provenance", "--offline", *arguments])

    def test_out_inside_the_inspected_folder_is_refused(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        inspected: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        destination = inspected / ".claude" / "skills" / "borrowed" / "SKILL.md"

        assert self._brief("--for", str(inspected), "--out", str(destination)) == 2

        captured = capsys.readouterr()
        assert not destination.exists(), "nothing may be written into what is described"
        assert captured.out == ""
        assert "dex-lens: " in captured.err

    def test_a_symlink_pointing_back_inside_is_refused(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        inspected: Path,
        tmp_path: Path,
    ) -> None:
        """Resolution happens before the comparison, or the guard is decoration."""
        bypass = tmp_path / "elsewhere"
        bypass.symlink_to(inspected, target_is_directory=True)

        assert self._brief("--for", str(inspected), "--out", str(bypass / "SKILL.md")) == 2
        assert not (inspected / "SKILL.md").exists()

    def test_a_relative_path_is_refused_from_inside_the_folder(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        inspected: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(inspected)

        assert self._brief("--for", str(inspected), "--out", "notes/SKILL.md") == 2
        assert not (inspected / "notes").exists()

    def test_the_folder_itself_named_as_the_out_path_is_refused(
        self, cached_catalogue: VerifiedCatalogueStore, inspected: Path
    ) -> None:
        assert self._brief("--for", str(inspected), "--out", str(inspected)) == 2

    def test_a_home_relative_folder_is_expanded_before_comparing(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        home = tmp_path / "home"
        (home / "vault").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))

        assert self._brief("--for", "~/vault", "--out", str(home / "vault" / "x.md")) == 2
        assert not (home / "vault" / "x.md").exists()

    def test_out_outside_the_inspected_folder_is_written(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        inspected: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        destination = tmp_path / "briefs" / "one.md"

        assert self._brief("--for", str(inspected), "--out", str(destination)) == 0
        assert "Portable brief" in destination.read_text(encoding="utf-8")

    def test_without_for_the_command_says_it_could_not_check(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Unverified is said out loud rather than passed off as verified."""
        destination = tmp_path / "one.md"

        assert self._brief("--out", str(destination)) == 0

        assert "--for" in capsys.readouterr().err

    def test_the_help_no_longer_promises_more_than_the_flag_allows(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            cli.brief_main(["--help"])

        help_text = capsys.readouterr().out
        assert "--for" in help_text
        assert "changes nothing" not in help_text, (
            "the command writes a file when --out is given; the help must say so"
        )


class TestBriefOutFailure:
    """A failed optional copy must not cost the brief that was already made."""

    def test_the_brief_prints_before_the_copy_is_attempted(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        blocked = tmp_path / "a-file"
        blocked.write_text("not a directory", encoding="utf-8")

        assert cli.brief_main(
            ["dex-durable-memory-provenance", "--offline", "--out", str(blocked / "x.md")]
        ) == 0

        captured = capsys.readouterr()
        assert "Portable brief" in captured.out, "the work is not lost with the copy"
        assert "dex-lens: " in captured.err
        assert "not written" in captured.err

    def test_the_warning_names_the_path_and_the_reason(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        blocked = tmp_path / "a-file"
        blocked.write_text("not a directory", encoding="utf-8")
        destination = blocked / "x.md"

        cli.brief_main(["dex-durable-memory-provenance", "--offline", "--out", str(destination)])

        err = capsys.readouterr().err
        assert str(destination) in err


def test_the_fetch_url_default_is_the_public_catalogue() -> None:
    """The request must carry nothing about the person, and be the same for all."""
    from capability_exchange.catalogue.fetch import DEFAULT_CATALOGUE_URL

    assert DEFAULT_CATALOGUE_URL.startswith("https://")
    assert "?" not in DEFAULT_CATALOGUE_URL, "a query string could carry identity"


def test_expiry_is_reported_as_stale_not_hidden(
    cached_catalogue: VerifiedCatalogueStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old catalogue may still be useful, but the reader must be told.

    Staleness is decided inside the store, against its own clock, so that is
    the clock to move. Patching the command's clock would have proved nothing
    and quietly passed.
    """
    from tests.catalogue.test_v2_verifier import NOW

    from capability_exchange.catalogue import v2

    far_future = NOW + timedelta(days=400)
    monkeypatch.setattr(v2, "_utcnow", lambda: far_future)

    assert cli.catalogue_main(["--offline"]) == 0

    captured = capsys.readouterr()
    assert "previously verified catalogue" in captured.err
    assert "Dex capability catalogue" in captured.out, "stale is still usable"
