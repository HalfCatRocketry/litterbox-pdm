"""
code_index.py - the litterbox package as data, for the architecture tests: every module, its source, its parsed
code and what it imports. No tests here.
"""

import ast
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
PACKAGE = APP / "litterbox"
TESTS = APP / "tests"


@dataclass
class Import:
    target: str             # the module imported, e.g. "litterbox.git.runner" (a name imported from a module
                            # counts as importing that module)
    line: int
    local: str              # the name it is bound to in the importing file
    is_module: bool         # True if `local` is a module (from litterbox.git import runner)


@dataclass
class Module:
    name: str               # litterbox.git.runner
    path: Path
    source: str
    tree: ast.Module
    imports: list = field(default_factory=list)

    @property
    def area(self):
        """The top folder (or file) of the package it belongs to: git, parts, gui, errors, ..."""
        parts = self.name.split(".")
        return parts[1] if len(parts) > 1 else ""


def module_name(path):
    return ".".join(path.relative_to(APP).with_suffix("").parts).removesuffix(".__init__")


def is_module(dotted):
    base = APP.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _imports(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("litterbox"):
                    found.append(Import(alias.name, node.lineno, alias.asname or alias.name.split(".")[0], True))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("litterbox"):
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                sub = is_module(dotted)
                found.append(Import(dotted if sub else node.module, node.lineno, alias.asname or alias.name, sub))
    return found


@lru_cache(maxsize=None)
def modules():
    """Every module of the litterbox package, by name."""
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        found[module_name(path)] = Module(module_name(path), path, source, tree, _imports(tree))
    return found


def area_of(dotted):
    parts = dotted.split(".")
    return parts[1] if len(parts) > 1 else ""


def bound_names(tree):
    """Every name a file assigns, takes as a parameter, or defines, at module level or inside functions. Methods and
    class attributes are left out: they live on the class, so they can't hide a module name."""
    class_level = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for member in node.body:
                class_level.add(id(member))
                if isinstance(member, (ast.Assign, ast.AnnAssign)):
                    targets = member.targets if isinstance(member, ast.Assign) else [member.target]
                    class_level |= {id(n) for t in targets for n in ast.walk(t)}
    names = set()
    for node in ast.walk(tree):
        if id(node) in class_level:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names
