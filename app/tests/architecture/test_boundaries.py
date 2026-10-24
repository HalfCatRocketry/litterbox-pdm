"""
Which code may do what (docs/ARCHITECTURE.md): run other programs, talk to SolidWorks, touch the window.
"""

import ast
import unittest

from tests.architecture.code_index import modules

# The modules that may start other programs (import subprocess), and what they run. git runs through git/runner.
MAY_START_PROGRAMS = {
    "litterbox.git.runner": "git and git-lfs: every git command goes through run()",
    "litterbox.vault.clone": "git clone, before there is a vault, with its own environment so the credential "
                             "manager can show its window",
    "litterbox.team.commit_signing": "ssh-keygen, to make a signing key",
    "litterbox.user.updater": "the downloaded installer",
    "litterbox.cad.opener": "the program a file opens in",
    "litterbox.cad.solidworks.sw_process": "tasklist and taskkill, to find and end a SolidWorks it started",
}
# The build self-test imports every library, only to check it made it into the build.
CHECKS_THE_BUILD = "litterbox.user.selftest"
# Libraries only cad/solidworks may import.
COM_LIBRARIES = ("win32com", "pythoncom", "pywintypes", "win32api")
WINDOW_LIBRARIES = ("tkinter", "customtkinter")


def imported_libraries(module):
    """Top-level names of every non-litterbox module the file imports (with 'import' or 'from ... import')."""
    names = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names - {"litterbox"}


class Boundaries(unittest.TestCase):
    def test_only_the_listed_modules_start_other_programs(self):
        users = {m.name for m in modules().values() if "subprocess" in imported_libraries(m)}
        self.assertEqual(sorted(users - set(MAY_START_PROGRAMS)), [],
                         "run git through litterbox.git.runner; anything else needs an entry in MAY_START_PROGRAMS")
        self.assertEqual(sorted(set(MAY_START_PROGRAMS) - users), [], "no longer starts programs: remove it")

    def test_only_cad_solidworks_talks_to_com(self):
        wrong = sorted(m.name for m in modules().values()
                       if imported_libraries(m) & set(COM_LIBRARIES) and not m.name.startswith("litterbox.cad.solidworks")
                       and m.name != CHECKS_THE_BUILD)
        self.assertEqual(wrong, [], "SolidWorks (COM) code belongs in litterbox/cad/solidworks")

    def test_only_cad_reaches_a_cad_programs_own_code(self):
        wrong = sorted(f"{m.name} imports {imp.target}" for m in modules().values() for imp in m.imports
                       if (imp.target == "litterbox.cad.solidworks" or imp.target.startswith("litterbox.cad.solidworks."))
                       and not m.name.startswith("litterbox.cad."))
        self.assertEqual(wrong, [], "reach a CAD program through litterbox.cad.cad_programs (cad/cad_program.py)")

    def test_only_the_window_imports_tkinter(self):
        wrong = sorted(m.name for m in modules().values()
                       if imported_libraries(m) & set(WINDOW_LIBRARIES) and m.name != CHECKS_THE_BUILD
                       and (not m.name.startswith("litterbox.gui.") or m.name.startswith("litterbox.gui.logic")))
        self.assertEqual(wrong, [], "window code belongs in litterbox/gui (and never in gui/logic)")

    def test_gui_logic_uses_no_window_code(self):
        wrong = sorted(f"{m.name} imports {imp.target}" for m in modules().values()
                       if m.name.startswith("litterbox.gui.logic") for imp in m.imports
                       if imp.target.startswith("litterbox.gui.") and not imp.target.startswith("litterbox.gui.logic"))
        self.assertEqual(wrong, [], "gui/logic holds decisions only, so it can be tested without a window")


if __name__ == "__main__":
    unittest.main()
