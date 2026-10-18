"""
package_map.py - prints the map of the litterbox package used in docs/ARCHITECTURE.md: every folder and module with
the first line of its docstring.

    python tools/package_map.py            (from the repository's top folder)

tools/update_architecture_map.py writes it into docs/ARCHITECTURE.md; run that after adding, moving or renaming
modules. A test (tests/architecture/test_docs.py) checks that every module is mentioned there.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app" / "litterbox"
COLUMN = 42             # where the descriptions start
WIDTH = 74              # longest description


def summary(path):
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    first = doc.strip().split("\n\n")[0].replace("\n", " ")
    first = re.sub(rf"^{re.escape(path.name)}\s*-\s*", "", first)
    first = re.split(r"(?<=[a-z)])\. ", first)[0].rstrip(".:")
    first = re.sub(r"\s{2,}", " ", first)
    if len(first) > WIDTH:
        first = first[:WIDTH - 3].rsplit(" ", 1)[0].rstrip(",;:") + " ..."
    return first


def lines(folder=ROOT, indent="    "):
    entries = sorted((p for p in folder.iterdir() if p.name not in ("__pycache__", "assets")),
                     key=lambda p: (p.is_dir(), p.name))
    for path in entries:
        name = indent + (path.name + "/" if path.is_dir() else path.name)
        if path.is_dir():
            init = path / "__init__.py"
            yield f"{name:<{COLUMN}}{summary(init) if init.exists() else ''}".rstrip()
            yield from lines(path, indent + "    ")
        elif path.suffix == ".py" and path.name != "__init__.py":
            yield f"{name:<{COLUMN}}{summary(path)}".rstrip()


if __name__ == "__main__":
    print("litterbox/")
    print("\n".join(lines()))
