"""
status.py - the part commands on the command line:

    python -m litterbox.cli.status <repo_folder> <action> [PN] [-m "text"]

    status                      list every part and who has it
    latest                      get the latest changes from the vault
    checkout  PN                lock a part so you can edit it
    checkin   PN -m "comment"   upload your changes and release the lock
                                (add --anyway to check in even if nothing changed)
    save      PN -m "comment"   upload your changes but KEEP the lock
    undo      PN                throw away your changes and release the lock
    release   PN                freeze the part and its drawing
    makecots  PN                record the part as COTS
    reopen    PN -m "reason"    make a released part editable again
    void      PN -m "reason"    abandon a part (its number is never reused)
"""

import argparse
import sys

from litterbox.errors import LitterboxError, NoChangesError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import part_status
from litterbox.parts import planning
from litterbox.parts import undoing


def _print_status(repo):
    rows = part_status.get_status(repo)
    if not rows:
        print("No parts yet.")
    for row in rows:
        print(f"{row.pn}  {row.state:<38} {row.name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Litterbox engine")
    parser.add_argument("repo", help="path to the repo folder")
    parser.add_argument("action", choices=["status", "latest", "checkout", "checkin", "save",
                                           "undo", "release", "makecots", "reopen", "void"])
    parser.add_argument("pn", nargs="?", help="part number, for example HCR-00042-001")
    parser.add_argument("-m", "--message", default="", help="comment or reason")
    parser.add_argument("--anyway", action="store_true",
                        help="check in even if no changes were detected")
    args = parser.parse_args(argv)

    try:
        if args.action == "status":
            _print_status(args.repo)
        elif args.action == "latest":
            changed = get_latest.get_latest(args.repo)
            print(f"{len(changed)} file(s) changed." + ("\n  " + "\n  ".join(changed) if changed else ""))
        else:
            if not args.pn:
                parser.error(f"'{args.action}' needs a part number")
            if args.action in ("reopen", "void") and not args.message.strip():
                parser.error(f"'{args.action}' needs a reason: -m \"why\"")

            if args.action == "checkout":
                result = checkout.checkout(args.repo, args.pn)
                if result.changed_upstream:
                    print("Newer versions were downloaded. Close and reopen these in SolidWorks:")
                    print("  " + "\n  ".join(result.changed_upstream))
            elif args.action in ("checkin", "save"):
                result = checkin.checkin(args.repo, args.pn, args.message, keep_lock=(args.action == "save"),
                                 allow_unchanged=args.anyway)
                if not result.uploaded:
                    print("There were no changes to upload.")
            elif args.action == "undo":
                left = undoing.undo_checkout(args.repo, args.pn)
                if left:
                    print("These new files were never uploaded, so they were left alone:")
                    print("  " + "\n  ".join(left))
            elif args.action == "release":
                plan = planning.release_plan(args.repo, args.pn)
                if not plan.ok:
                    print("Can't release yet:\n- " + "\n- ".join(plan.problems))
                    sys.exit(1)
                print(f"This will release {plan.pn} ({plan.name}) and freeze:")
                print("  " + "\n  ".join(plan.files))
                if input("Release these files? [y/N] ").strip().lower() != "y":
                    print("Cancelled.")
                    return
                lifecycle.release(args.repo, args.pn)
            elif args.action == "makecots":
                plan = planning.make_cots_plan(args.repo, args.pn)
                if not plan.ok:
                    print("Can't make it COTS yet:\n- " + "\n- ".join(plan.problems))
                    sys.exit(1)
                print(f"This will record {plan.pn} ({plan.name}) as a COTS part, which can't be checked out:")
                print("  " + "\n  ".join(plan.files))
                if input("Make it COTS? [y/N] ").strip().lower() != "y":
                    print("Cancelled.")
                    return
                lifecycle.make_cots(args.repo, args.pn)
            elif args.action == "reopen":
                lifecycle.reopen(args.repo, args.pn, args.message)
            elif args.action == "void":
                lifecycle.void(args.repo, args.pn, args.message)
        print("\nDone.")
    except LitterboxError as e:
        print(f"\nERROR: {e}")
        if isinstance(e, NoChangesError):
            print("Add --anyway to check in anyway.")
        sys.exit(1)


if __name__ == "__main__":
    main()
