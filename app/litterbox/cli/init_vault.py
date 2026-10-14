"""
init_vault.py - Create new vault on the command line: python -m litterbox.cli.init_vault --help
"""

import argparse
import sys

from litterbox import diagnostics
from litterbox.core import part_number
from litterbox.errors import LitterboxError
from litterbox.vault import create_vault


def main(argv=None):
    parser = argparse.ArgumentParser(description="Turn an empty cloned repository into a Litterbox vault.")
    parser.add_argument("folder", help="the cloned, empty repository")
    parser.add_argument("--org", required=True, help="org code, 2 to 4 letters (HCR)")
    parser.add_argument("--start", type=int, default=1, help="first part number to hand out (default 1)")
    parser.add_argument("--base-digits", type=int, default=part_number.NEW_VAULT_BASE_DIGITS)
    parser.add_argument("--variant-digits", type=int, default=part_number.DEFAULT_VARIANT_DIGITS)
    parser.add_argument("--no-push", action="store_true", help="commit locally only")
    parser.add_argument("--no-team", action="store_true", help="don't set up the team (do it later in Team...)")
    parser.add_argument("--name", help="your name for the team list (default: git's user.name)")
    parser.add_argument("--email", help="your email for the team list (default: git's user.email)")
    parser.add_argument("--yes", action="store_true", help="go ahead even when there are warnings")
    args = parser.parse_args(argv)
    diagnostics.LOG = print

    checked = create_vault.plan(args.folder, args.org, args.start, args.base_digits, args.variant_digits, not args.no_push)
    if not checked.ok:
        print("The vault can't be set up yet:")
        for problem in checked.problems:
            print(f"- {problem}")
        return 1
    for warning in checked.warnings:
        print(f"WARNING: {warning}")
    if checked.warnings and not args.yes:
        if input("Go ahead anyway? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was changed.")
            return 1
    try:
        result = create_vault.create(args.folder, args.org, args.start, args.base_digits, args.variant_digits,
                        push=not args.no_push, set_up_team=not args.no_team, name=args.name, email=args.email)
    except LitterboxError as e:
        print(f"Failed. Nothing was left behind.\n{e}")
        return 1
    print(f"\nThe {result.org} vault is set up" + (" and uploaded." if result.pushed else " (not uploaded)."))
    if result.owner:
        print(f"{result.owner.name} is the Owner.")
    elif result.team_error:
        print(f"The team was not set up: {result.team_error}\nYou can do it later with Team... in Litterbox.")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
