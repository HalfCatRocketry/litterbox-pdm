"""python -m litterbox <command>: the command line (see litterbox/cli/__init__.py)."""

import sys

from litterbox import cli

sys.exit(cli.main())
