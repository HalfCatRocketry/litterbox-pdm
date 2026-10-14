"""
The command line:  python -m litterbox <command> [options]      (run from the app folder)

    status      part status and the part actions: status, latest, checkout, checkin, save, undo, release,
                makecots, reopen, void                                  (cli/status.py)
    new-part    New Part and New Variant                                (cli/new_part.py)
    scan        phase 1 of an import: scan old folders, write a manifest (cli/scan.py)
    import      phase 3 of an import: import from a manifest            (cli/import_files.py)
    init-vault  turn an empty clone into a vault                        (cli/init_vault.py)

    python -m litterbox <command> --help      shows that command's options
"""

import importlib
import sys

COMMANDS = {
    "status": "litterbox.cli.status",
    "new-part": "litterbox.cli.new_part",
    "scan": "litterbox.cli.scan",
    "import": "litterbox.cli.import_files",
    "init-vault": "litterbox.cli.init_vault",
}


def main(argv=None):
    """Run one command. Returns the exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print(__doc__.strip("\n"))
        if argv and argv[0] not in ("-h", "--help"):
            print(f"\nUnknown command: {argv[0]}")
            return 2
        return 0
    command, rest = argv[0], argv[1:]
    module = importlib.import_module(COMMANDS[command])
    return module.main(rest, prog=f"python -m litterbox {command}") or 0
