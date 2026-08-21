"""``dex-lens catalogue`` and ``dex-lens brief``: the catalogue, for an agent.

These two commands are the whole of what the Dex Lens skill cannot do for
itself. The skill reads the person's system and forms the judgement; these
commands establish that the thing it is comparing against really is Dex's
published catalogue and not something that arrived over the network claiming
to be.

Both write nothing except Lens's own verified-catalogue cache, which lives in
app storage and is required to sit outside any folder Lens may read.

Exit codes are meaningful because an agent reads them: 0 means the output is
verified, 1 means it is not, and in that case stdout carries nothing that
could be mistaken for a catalogue.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from capability_exchange.catalogue.agent import (
    render_capability_brief_markdown,
    render_catalogue_digest,
)
from capability_exchange.catalogue.fetch import (
    CONSENT_STATEMENT,
    DEFAULT_CATALOGUE_URL,
    CatalogueFetchConsent,
    CatalogueFetchResult,
    CatalogueFetchStatus,
    ConsentedCatalogueFetcher,
)
from capability_exchange.catalogue.subscription import default_lens_app_storage
from capability_exchange.catalogue.v2 import (
    CatalogueVerificationError,
    VerifiedCatalogueStore,
    default_keyring,
)

__all__ = ["brief_main", "catalogue_main"]


def _fetch(url: str, *, offline: bool) -> CatalogueFetchResult | None:
    """One verified catalogue, or ``None`` after explaining why not.

    Failure prints to stderr and returns ``None`` rather than falling back to
    unverified bytes. An unverified catalogue is worse than no catalogue: it
    is a list of changes to someone's system, from an unproven source.
    """
    store = VerifiedCatalogueStore(default_lens_app_storage())

    if offline:
        # The signature is re-checked on the way out of the cache, not trusted
        # because it was checked once on the way in. A cached catalogue is a
        # file on disk like any other and may have been altered since.
        try:
            state = store.load_last_verified_state(keyring=default_keyring())
        except CatalogueVerificationError as exc:
            print(f"dex-lens: stored catalogue refused: {exc}", file=sys.stderr)
            return None
        if state.catalogue is None:
            print(
                "dex-lens: no verified catalogue has been fetched on this machine yet, "
                "so there is nothing to read offline.",
                file=sys.stderr,
            )
            return None
        if state.status == "stale":
            print(
                f"dex-lens: using a previously verified catalogue: {state.message}",
                file=sys.stderr,
            )
        return CatalogueFetchResult(
            status=CatalogueFetchStatus.VERIFIED,
            message=state.message,
            catalog_version=state.catalogue.metadata.catalog_version,
            verified=state.catalogue,
            stale=None,
            fetched_at=datetime.now(UTC),
        )

    fetcher = ConsentedCatalogueFetcher(store=store)
    result = fetcher.fetch(
        CatalogueFetchConsent(
            catalogue_url=url,
            requested_at=datetime.now(UTC),
            statement=CONSENT_STATEMENT,
        )
    )
    if result.status is not CatalogueFetchStatus.VERIFIED or result.verified is None:
        print(f"dex-lens: {result.message}", file=sys.stderr)
        if result.stale is not None:
            print(
                "dex-lens: a previously verified catalogue is on this machine; "
                "re-run with --offline to read it.",
                file=sys.stderr,
            )
        return None
    return result


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--url",
        default=DEFAULT_CATALOGUE_URL,
        help=(
            "Where to fetch the signed catalogue from. The default is the public "
            "Dex catalogue, identical for everyone; the request carries nothing "
            "about this system."
        ),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Read the last catalogue verified on this machine; make no request.",
    )


def catalogue_main(argv: list[str] | None = None) -> int:
    """Fetch, verify, and print Dex's published capability catalogue."""

    parser = argparse.ArgumentParser(
        prog="dex-lens catalogue",
        description=(
            "Fetch the public signed Dex catalogue, verify its signature on this "
            "machine, and print it. Nothing about this system is sent."
        ),
    )
    _add_source_arguments(parser)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the verified catalogue as JSON instead of a readable digest.",
    )
    parser.add_argument(
        "--since",
        type=int,
        metavar="VERSION",
        help=(
            "Print only capabilities added or changed after this catalogue "
            "version, for a recurring check. Prints nothing when there is "
            "nothing new."
        ),
    )
    args = parser.parse_args(argv)

    result = _fetch(args.url, offline=args.offline)
    if result is None:
        return 1
    assert result.verified is not None
    envelope = result.verified
    catalogue = envelope.catalogue
    version = envelope.metadata.catalog_version

    # `--since` decides whether there is anything to print at all, so it is
    # answered before the output format. Checking it after the `--json` branch
    # meant a recurring check asking for JSON printed the whole catalogue on
    # every run, which is exactly the "reports every release, gets turned off"
    # failure the flag exists to avoid.
    if args.since is not None:
        if version <= args.since:
            print(
                f"Nothing new. The published catalogue is still version {version}.",
                file=sys.stderr,
            )
            return 0
        # `changed_in` carries the Core releases an entry changed in, which is
        # not the catalogue version, so it cannot answer "since version N".
        # The honest fallback is to say what the whole catalogue now contains
        # and let the reader compare, rather than infer a delta the data does
        # not support.
        print(
            f"The catalogue moved from version {args.since} to {version}. "
            "Published entries do not record which catalogue version they "
            "changed in, so this is the full current list, not a delta.",
            file=sys.stderr,
        )

    if args.json:
        print(envelope.model_dump_json(indent=2))
        return 0

    print(
        f"<!-- verified catalogue version {version}, "
        f"Dex Core {envelope.metadata.core_release} -->"
    )
    print(render_catalogue_digest(catalogue), end="")
    return 0


def brief_main(argv: list[str] | None = None) -> int:
    """Print the portable brief for one capability."""

    parser = argparse.ArgumentParser(
        prog="dex-lens brief",
        description=(
            "Print everything needed to rebuild one Dex capability inside a "
            "different system. Guidance only; this command changes nothing."
        ),
    )
    parser.add_argument("capability_id", help="Capability id, as printed by `dex-lens catalogue`.")
    _add_source_arguments(parser)
    parser.add_argument(
        "--why",
        default="",
        help=(
            "The reasoning behind recommending this to this person, passed "
            "through verbatim and attributed to whoever wrote it. Dex does not "
            "supply one: a catalogue entry knows nothing about the reader."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write the brief to this file as well as printing it.",
    )
    args = parser.parse_args(argv)

    result = _fetch(args.url, offline=args.offline)
    if result is None:
        return 1
    assert result.verified is not None

    try:
        brief = render_capability_brief_markdown(
            result.verified.catalogue,
            args.capability_id,
            why=args.why,
        )
    except KeyError as exc:
        print(f"dex-lens: {exc.args[0]}", file=sys.stderr)
        return 1

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(brief, encoding="utf-8")
        print(f"dex-lens: written to {args.out}", file=sys.stderr)
    print(brief, end="")
    return 0
