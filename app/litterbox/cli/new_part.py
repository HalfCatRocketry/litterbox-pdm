"""
new_part.py - New Part and New Variant on the command line. Run with --help to see how.
"""

import argparse
import sys

from litterbox.core.part_number import format_base, format_variant
from litterbox.errors import LitterboxError
from litterbox.parts import create
from litterbox.parts import number_suggestions


def main(argv=None, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description="Litterbox: create part numbers")
    parser.add_argument("repo", help="path to the vault folder")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("part", help="create a new part number")
    p.add_argument("name")
    p.add_argument("--description", default="", help="optional extra context or tags")
    p.add_argument("--number", type=int, help="ask for this part number instead of the next free one")
    p.add_argument("--variant", type=int, help="ask for this variant number instead of the lowest free one")
    p.add_argument("--assembly", action="store_true", help="an assembly: its variants start at 500 (or the org's start)")
    p.add_argument("--project", help="the project to take the number from")

    p = sub.add_parser("variant", help="create a new variant of an existing part number")
    p.add_argument("base", type=int, help="the existing part number, for example 42")
    p.add_argument("name")
    p.add_argument("--description", default="", help="optional extra context or tags")
    p.add_argument("--variant", type=int, help="ask for this variant number instead of the next free one")

    p = sub.add_parser("variants", help="list the variants of a part number")
    p.add_argument("base", type=int)

    sub.add_parser("next", help="show the next free part number")
    args = parser.parse_args(argv)

    try:
        if args.command == "part":
            kind = create.ASSEMBLY if args.assembly else create.PART
            print(f"Created {create.new_part(args.repo, args.name, args.description, base=args.number, variant=args.variant, project=args.project, kind=kind)}")
        elif args.command == "variant":
            print(f"Created {create.new_variant(args.repo, args.base, args.name, args.description, variant=args.variant)}")
        elif args.command == "variants":
            records = number_suggestions.list_variants(args.repo, args.base)
            if not records:
                print(f"No variants of part number {format_base(args.base)} yet.")
            for r in records:
                print(f"{r.pn}  {r.status:<9} {r.name}")
            if records:
                print(f"Next free variant: {format_variant(number_suggestions.suggest_variant_number(args.repo, args.base))}")
        else:
            print(f"Next free part number: {format_base(number_suggestions.suggest_part_number(args.repo))}")
    except LitterboxError as e:
        print(f"\nERROR: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
