"""python -m litterbox <command>: the command line (see litterbox/cli/commands.py)."""

import sys

from litterbox.cli import commands

sys.exit(commands.main())
