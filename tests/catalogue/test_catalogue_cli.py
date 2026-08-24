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

from capability_exchange.catalogue import cli
from capability_exchange.catalogue.subscription import CatalogueSubscriptionStore
from capability_exchange.catalogue.v2 import KeyRing, VerifiedCatalogueStore

KEY_ID = "dex-core-2026-08-test"


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
    """The recurring check, without a version number anyone has to remember."""

    def test_the_first_run_prints_everything_and_records_the_baseline(
        self, cached_catalogue: VerifiedCatalogueStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.catalogue_main(["--offline", "--since-last"]) == 0

        captured = capsys.readouterr()
        assert "Dex capability catalogue" in captured.out
        assert "no catalogue version has been recorded" in captured.err
        assert _recorded_version() == 7

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

    def test_a_newer_catalogue_speaks_again(
        self,
        cached_catalogue: VerifiedCatalogueStore,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _record_seen(3)

        assert cli.catalogue_main(["--offline", "--since-last"]) == 0

        captured = capsys.readouterr()
        assert "Dex capability catalogue" in captured.out
        assert "moved from version 3 to 7" in captured.err
        assert _recorded_version() == 7

    def test_two_ways_of_saying_since_are_refused_together(
        self, cached_catalogue: VerifiedCatalogueStore
    ) -> None:
        with pytest.raises(SystemExit) as refused:
            cli.catalogue_main(["--offline", "--since", "3", "--since-last"])

        assert refused.value.code == 2

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


def _recorded_version() -> int | None:
    return _subscription_store().load().last_seen_catalog_version


def _record_seen(version: int) -> None:
    _subscription_store().record_seen(catalog_version=version)


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
