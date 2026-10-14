"""
import_files.py - running an import on the command line from a manifest made by the scan
(python -m litterbox.cli.import_files --help).
"""

import argparse
import sys

from litterbox.errors import LitterboxError
from litterbox.importing import import_finish
from litterbox.importing import import_journal
from litterbox.importing import import_numbering


def main(argv=None):
    parser = argparse.ArgumentParser(description="Litterbox: import files from a manifest")
    parser.add_argument("repo", help="path to the vault folder")
    parser.add_argument("manifest", nargs="?", help="the manifest file made by scan.py")
    parser.add_argument("--dry-run", action="store_true", help="check everything and show the plan; write nothing")
    parser.add_argument("--allow-external", action="store_true",
                        help="allow references to files that are not part of the import")
    parser.add_argument("--gap", type=int, default=import_numbering.DEFAULT_GAP,
                        help=f"propose part numbers this far past the lowest free one (default {import_numbering.DEFAULT_GAP})")
    parser.add_argument("--cots", action="store_true", help="record every imported part as COTS (purchased)")
    parser.add_argument("--recover", action="store_true", help="clean up after an interrupted import and stop")
    args = parser.parse_args(argv)
    try:
        if args.recover:
            print(f"Recovery: {import_journal.recover(args.repo)}")
            return 0
        if not args.manifest:
            parser.error("the manifest file is required")
        result = import_finish.run(args.repo, args.manifest, dry_run=args.dry_run, allow_external=args.allow_external, gap=args.gap, cots=args.cots,
                     progress=lambda done, total, text: print(f"[{done}/{total}] {text}"))
    except LitterboxError as e:
        print(f"\nERROR: {e}")
        return 1
    if result.dry_run:
        print(f"\nDry run: {len(result.pns)} part(s) would be created, {len(result.plan.order)} file(s) copied.")
        for item, pn in zip(result.plan.items, result.pns):
            print(f"  {pn}  {item.name}")
    else:
        print(f"\nImported {len(result.pns)} part(s), {len(result.files)} file(s): {min(result.pns)} to {max(result.pns)}")
    for warning in result.warnings:
        print(f"  note: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
