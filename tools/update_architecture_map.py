"""
update_architecture_map.py - writes the current package map (tools/package_map.py) into docs/ARCHITECTURE.md.

    python tools/update_architecture_map.py        (from the repository's top folder)
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import package_map  # noqa: E402

DOC = Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE.md"

if __name__ == "__main__":
    text = DOC.read_text(encoding="utf-8")
    new_map = "litterbox/\n" + "\n".join(package_map.lines())
    text, count = re.subn(r"(## Map of the package\n.*?```\n)litterbox/\n.*?(\n```)", lambda m: m[1] + new_map + m[2],
                          text, count=1, flags=re.S)
    if count != 1:
        sys.exit("The map was not found in docs/ARCHITECTURE.md (it follows '## Map of the package').")
    DOC.write_text(text, encoding="utf-8", newline="\n")
    print("docs/ARCHITECTURE.md: map updated")
