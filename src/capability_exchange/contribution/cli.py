"""Fresh-process contributor controls for hosted Capability Cards."""

from __future__ import annotations

import argparse
import sys

from capability_exchange.catalogue.subscription import default_lens_app_storage
from capability_exchange.contribution.hosted_intake import (
    HostedContributionIntake,
    HostedIntakeError,
    HostedSessionCredentials,
)


def _new_intake() -> HostedContributionIntake:
    credentials = HostedSessionCredentials()
    return HostedContributionIntake(
        session_token=credentials.session_token,
        receipt_store=(
            default_lens_app_storage() / "hosted-contribution-receipts.json"
        ),
    )


def contributions_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dex-lens contributions",
        description="Check, correct, withdraw or delete contributions you sent to Dex.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List locally saved contribution receipts.")
    status = commands.add_parser("status", help="Fetch one contribution's review status.")
    status.add_argument("receipt_id")
    withdraw = commands.add_parser("withdraw", help="Withdraw one contribution.")
    withdraw.add_argument("receipt_id")
    withdraw.add_argument("--yes", action="store_true", help="Confirm the withdrawal.")
    delete = commands.add_parser(
        "delete-all", help="Delete all hosted contributions for the linked account."
    )
    delete.add_argument("--yes", action="store_true", help="Confirm account deletion.")
    args = parser.parse_args(argv)
    intake = _new_intake()
    try:
        if args.command == "list":
            receipts = intake.saved_receipts()
            if not receipts:
                print("No saved contribution receipts.")
            for receipt_id, saved_status in receipts:
                print(f"{receipt_id}\t{saved_status}")
            return 0
        if args.command == "status":
            result = intake.status_saved(args.receipt_id)
            print(f"{result.receipt_id}\t{result.status}")
            if result.moderation_reason:
                print(result.moderation_reason)
            return 0
        if args.command == "withdraw":
            if not args.yes:
                print(
                    "Nothing was changed. Add --yes to confirm this withdrawal.",
                    file=sys.stderr,
                )
                return 2
            intake.withdraw_saved(args.receipt_id)
            print(f"Withdrawn: {args.receipt_id}")
            return 0
        if not args.yes:
            print(
                "Nothing was changed. Add --yes to delete all hosted contributions.",
                file=sys.stderr,
            )
            return 2
        receipt = intake.delete_all_saved()
        print(f"Deleted {receipt.deleted_count} contribution(s).")
        print(receipt.retention_disclosure)
        return 0
    except HostedIntakeError as exc:
        print(f"dex-lens contributions: {exc}", file=sys.stderr)
        return 2
