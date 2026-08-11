from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from tests.catalogue.test_v2_verifier import NOW, sign_envelope, unsigned_envelope

from capability_exchange.catalogue.fetch import (
    CatalogueFetchConsent,
    CatalogueFetchStatus,
    ConsentedCatalogueFetcher,
)
from capability_exchange.catalogue.v2 import (
    KeyRing,
    VerifiedCatalogueStore,
    verify_catalogue_envelope,
)


@pytest.fixture()
def signing_key() -> Ed25519PrivateKey:
    seed = b"dex-lens-catalogue-v2-test-key!!"
    assert len(seed) == 32
    return Ed25519PrivateKey.from_private_bytes(seed)


@pytest.fixture()
def keyring(signing_key: Ed25519PrivateKey) -> KeyRing:
    public_key = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return KeyRing({"dex-core-2026-08-test": base64.b64encode(public_key).decode("ascii")})


class OneShotHTTP:
    def __init__(self, payload: str | Exception) -> None:
        self.payload = payload
        self.requests: list[object] = []

    def __call__(self, request: object, *, timeout: float) -> object:
        self.requests.append(request)
        if isinstance(self.payload, Exception):
            raise self.payload
        return Response(self.payload)


class Response:
    def __init__(self, payload: str) -> None:
        self.payload = payload.encode("utf-8")

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def consent() -> CatalogueFetchConsent:
    return CatalogueFetchConsent(
        catalogue_url="https://heydex.ai/catalogue/dex-lens/v2.json",
        requested_at=NOW,
        statement="fetch-public-signed-dex-catalogue",
    )


def test_fetcher_does_not_request_catalogue_until_called(
    signing_key, keyring: KeyRing, tmp_path: Path
) -> None:
    raw = sign_envelope(unsigned_envelope(), signing_key)
    http = OneShotHTTP(raw)
    fetcher = ConsentedCatalogueFetcher(
        store=VerifiedCatalogueStore(tmp_path),
        keyring=keyring,
        urlopen=http,
        now=lambda: NOW,
    )

    assert http.requests == []
    result = fetcher.fetch(consent())

    assert result.status is CatalogueFetchStatus.VERIFIED
    assert result.catalog_version == 7
    assert len(http.requests) == 1
    request = http.requests[0]
    assert request.method == "GET"
    assert request.data is None
    assert request.full_url == "https://heydex.ai/catalogue/dex-lens/v2.json"
    assert "Cookie" not in request.headers
    assert "Authorization" not in request.headers


def test_failed_verification_is_refused_and_not_cached(
    signing_key, keyring: KeyRing, tmp_path: Path
) -> None:
    decoded = json.loads(sign_envelope(unsigned_envelope(), signing_key))
    decoded["catalogue"]["capabilities"][0]["title"] = "tampered"
    http = OneShotHTTP(json.dumps(decoded, sort_keys=True, separators=(",", ":")))
    store = VerifiedCatalogueStore(tmp_path)
    fetcher = ConsentedCatalogueFetcher(
        store=store,
        keyring=keyring,
        urlopen=http,
        now=lambda: NOW,
    )

    result = fetcher.fetch(consent())

    assert result.status is CatalogueFetchStatus.REFUSED
    assert result.verified is None
    assert not store.cache_path.exists()


def test_offline_fetch_returns_verified_stale_cache_as_stale_not_usable(
    signing_key, keyring: KeyRing, tmp_path: Path
) -> None:
    stale_now = NOW + timedelta(days=45)
    store = VerifiedCatalogueStore(tmp_path)
    store.save_verified(
        verify_catalogue_envelope(
            sign_envelope(unsigned_envelope(), signing_key),
            keyring=keyring,
            now=NOW,
        )
    )
    fetcher = ConsentedCatalogueFetcher(
        store=store,
        keyring=keyring,
        urlopen=OneShotHTTP(URLError("offline")),
        now=lambda: stale_now,
    )

    result = fetcher.fetch(consent())

    assert result.status is CatalogueFetchStatus.STALE_CACHE
    assert result.verified is None
    assert result.stale is not None
    assert result.catalog_version == 7
    assert "offline" in result.message.lower()


@pytest.mark.parametrize(
    "url",
    [
        "http://heydex.ai/catalogue.json",
        "https://evil.test/catalogue.json",
        "file:///tmp/catalogue.json",
    ],
)
def test_consent_is_bound_to_static_public_dex_https_get(url: str) -> None:
    with pytest.raises(ValueError):
        CatalogueFetchConsent(
            catalogue_url=url,
            requested_at=datetime(2026, 8, 11, 15, 30, tzinfo=UTC),
            statement="fetch-public-signed-dex-catalogue",
        )
