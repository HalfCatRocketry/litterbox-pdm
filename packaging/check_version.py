"""Used by the release pipeline.

    python packaging/check_version.py v0.1.0      fails unless that tag matches VERSION in app/version.py
    python packaging/check_version.py --print     prints VERSION (so the pipeline can use it)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import version  # noqa: E402


def main(argv):
    if argv[1:] == ["--print"]:
        print(version.VERSION)
        return 0
    if len(argv) != 2:
        print(__doc__)
        return 2
    tag = argv[1].removeprefix("refs/tags/")
    if tag != f"v{version.VERSION}":
        print(f"The tag is '{tag}' but app/version.py says VERSION = \"{version.VERSION}\".\n"
              f"Change VERSION to match (or tag v{version.VERSION}), commit, and tag again.")
        return 1
    print(f"Tag {tag} matches VERSION {version.VERSION}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
