"""
The layers of the program (docs/ARCHITECTURE.md): a module imports from its own layer and the layers below it,
never from a layer above. Imports inside functions count too.
"""

import unittest

from tests.architecture.code_index import area_of, modules

# Higher number = higher layer. Every top-level folder and file of the package has one.
LAYERS = {
    "errors": 0, "diagnostics": 0, "version": 0, "layout": 0, "build_info": 0, "util": 0,
    "core": 1,
    "records": 2,
    "git": 3,
    "vault": 4, "team": 4, "cad": 4, "parts": 4, "references": 4, "workflows": 4, "importing": 4, "change_orders": 4,
    "jobs": 5, "user": 5, "cli": 5,
    "gui": 6, "__main__": 6,
}

# Imports that go up a layer, on purpose or for now. Each says why. A test fails if one is no longer needed, so
# this list only ever shrinks.
KNOWN_EXCEPTIONS = {
    ("litterbox.git.repository", "litterbox.vault.config"):
        "validate_repo applies the vault's part-number digits as it checks the folder is a vault",
    ("litterbox.git.repository", "litterbox.team.team_identity"):
        "get_user asks the team who you are when git has no user name",
    ("litterbox.user.selftest", "litterbox.gui.logic.icon_files"):
        "the build self-test checks the window's icon files are in the build",
}


def upward_imports():
    found = {}
    for module in modules().values():
        if not module.area:                     # litterbox/__init__.py: only a docstring
            continue
        here = LAYERS[module.area]
        for imp in module.imports:
            area = area_of(imp.target)
            if area and LAYERS[area] > here:
                found.setdefault((module.name, imp.target), imp.line)
    return found


class Layers(unittest.TestCase):
    def test_every_part_of_the_package_has_a_layer(self):
        missing = sorted({m.area for m in modules().values() if m.area and m.area not in LAYERS})
        self.assertEqual(missing, [], "add these to LAYERS (and to docs/ARCHITECTURE.md)")

    def test_nothing_imports_from_a_higher_layer(self):
        wrong = [f"{a} (line {line}) imports {b}" for (a, b), line in sorted(upward_imports().items())
                 if (a, b) not in KNOWN_EXCEPTIONS]
        self.assertEqual(wrong, [], "a module may only import from its own layer or a lower one")

    def test_every_known_exception_is_still_needed(self):
        stale = sorted(set(KNOWN_EXCEPTIONS) - set(upward_imports()))
        self.assertEqual(stale, [], "these no longer happen: remove them from KNOWN_EXCEPTIONS")


if __name__ == "__main__":
    unittest.main()
