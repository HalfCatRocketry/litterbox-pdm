"""Tests for the team's Toolbox rule and the team's Toolbox in a real vault (parts/toolbox_check.py,
vault/toolbox_admin.py, team/guarded_push.toolbox_allowed): Check In and Release refuse an assembly that breaks the
rule, and only an Admin or the Owner changes the team's Toolbox. Alex is the Owner; Bea and Cy are Members. The
check-in reader stands in for SolidWorks, so these run without it (and need Linux, macOS or WSL, as git tests do)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.support import temp_folders
from tests.support.vault_fixture import git
from tests.support.workflow_fixture import Fixture

from litterbox.core import toolbox_rules
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import planning
from litterbox.records import record_other_files
from litterbox.records import record_store
from litterbox.references.reference_reader import AssemblyRead
from litterbox.vault import config
from litterbox.vault import settings_admin
from litterbox.vault import toolbox_admin

ASM = PN("HCR", 3, 500)
SLDASM = "cad/HCR-00003-500_A.SLDASM"
SCREW = {"file": "C:\\SOLIDWORKS Data\\browser\\screw.sldprt", "toolbox": True}
NUT = {"file": "toolbox/browser/nut.sldprt", "toolbox": True}


def reader(*other):
    """A check-in reader that says the assembly uses these other files (and no Litterbox parts)."""
    return lambda repo, pn, revision, changed: AssemblyRead(references=[], quantities={}, other_files=list(other))


class ToolboxRule(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        (self.a / SLDASM).write_bytes(b"assembly 1")
        record_store.create_record(self.a, ASM, "Drive assembly", "Alex")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "An assembly")
        git(self.a, "push")
        with self.user("Alex"):
            read_only.enforce_read_only(self.a)
        source = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, source)
        (source / "browser").mkdir()
        (source / "browser" / "nut.sldprt").write_bytes(b"a nut")
        (source / "ToolboxStandards.xml").write_text("<standards/>", encoding="utf-8")
        self.toolbox_source = source

    def set_rule(self, rule):
        self.do("Alex", settings_admin.edit, toolbox=rule)

    def check_in(self, user, *other, changed=b"assembly 2"):
        repo = self.repo_of(user)
        self.do(user, checkout.checkout, ASM)
        (repo / SLDASM).write_bytes(changed)
        return self.do(user, checkin.checkin, ASM, "Update", references_reader=reader(*other))

    def test_a_rule_makes_the_vault_need_0_6_0(self):
        self.set_rule(toolbox_rules.NO_TOOLBOX)
        settings = config.load(self.a)
        self.assertEqual((settings["toolbox"], settings["min_litterbox_version"]), ("none", toolbox_rules.MIN_LITTERBOX))
        self.set_rule(toolbox_rules.OFF)
        self.assertNotIn("toolbox", config.load(self.a))

    def test_without_a_rule_anything_is_checked_in_and_kept(self):
        self.check_in("Alex", SCREW)
        self.assertEqual(record_other_files.entries(record_store.load(self.a, ASM)), [SCREW])

    def test_no_toolbox_refuses_the_check_in_and_the_part_stays_checked_out(self):
        self.set_rule(toolbox_rules.NO_TOOLBOX)
        with self.assertRaises(LitterboxError) as ctx:
            self.check_in("Alex", SCREW)
        self.assertIn("HCR-00003-500 was not checked in. It uses Toolbox parts (screw.sldprt)", str(ctx.exception))
        self.assertIn("pn-logs/hcr-00003-500.yaml", lfs_locks.get_locks(self.a, strict=True))
        self.assertFalse(record_other_files.is_read(record_store.load(self.a, ASM)))
        (self.a / SLDASM).write_bytes(b"assembly 3")
        self.do("Alex", checkin.checkin, ASM, "Without the screw", references_reader=reader())
        self.assertEqual(record_other_files.entries(record_store.load(self.a, ASM)), [])

    def test_release_needs_the_assembly_read_since_it_last_changed(self):
        self.set_rule(toolbox_rules.NO_TOOLBOX)
        self.do("Alex", checkout.checkout, ASM)
        (self.a / SLDASM).write_bytes(b"assembly 2")
        self.do("Alex", checkin.checkin, ASM, "No SolidWorks open")                 # nothing read
        plan = self.do("Alex", planning.release_plan, ASM)
        self.assertTrue(any("Update BOM" in problem for problem in plan.problems))
        self.check_in("Alex", changed=b"assembly 3")
        self.assertFalse(any("Toolbox" in p or "Update BOM" in p for p in self.do("Alex", planning.release_plan, ASM).problems))
        self.set_rule(toolbox_rules.OFF)
        self.assertEqual([p for p in self.do("Alex", planning.release_plan, ASM).problems if "Toolbox" in p], [])

    def test_a_rule_set_after_the_check_in_still_stops_the_release(self):
        self.check_in("Alex", SCREW)
        self.set_rule(toolbox_rules.NO_TOOLBOX)
        plan = self.do("Alex", planning.release_plan, ASM)
        self.assertTrue(any("uses Toolbox parts (screw.sldprt)" in problem for problem in plan.problems))

    def test_the_teams_toolbox_only_once_an_admin_has_uploaded_the_part(self):
        self.set_rule(toolbox_rules.TEAM)
        os.makedirs(self.a / "toolbox" / "browser")
        (self.a / NUT["file"]).write_bytes(b"made by SolidWorks here")
        with self.assertRaises(LitterboxError) as ctx:
            self.check_in("Alex", NUT)
        self.assertIn("not in the team's Toolbox yet (nut.sldprt)", str(ctx.exception))
        os.chmod(self.a / NUT["file"], 0o644)                  # Litterbox keeps the Toolbox folder read-only
        os.remove(self.a / NUT["file"])
        counts = self.do("Alex", toolbox_admin.copy_in, self.toolbox_source)
        self.assertEqual(counts, {"added": 2, "changed": 0, "removed": 0})
        self.assertIn("Toolbox: 2 files added", self.remote_log())
        (self.a / SLDASM).write_bytes(b"assembly 3")
        self.do("Alex", checkin.checkin, ASM, "With the team's nut", references_reader=reader(NUT))
        with self.assertRaises(LitterboxError):
            self.check_in("Bea", SCREW)                     # a Toolbox part from somewhere else

    def test_only_an_admin_changes_the_teams_toolbox(self):
        self.do("Alex", toolbox_admin.copy_in, self.toolbox_source)
        self.get_latest("Bea")
        nut = self.b / NUT["file"]
        self.assertEqual(nut.read_bytes(), b"a nut")
        self.assertFalse(os.access(nut, os.W_OK))                                    # read-only for everyone
        for action in (toolbox_admin.upload, toolbox_admin.open_for_changes):
            with self.assertRaises(LitterboxError) as ctx:
                self.do("Bea", action)
            self.assertIn("Only an Admin", str(ctx.exception))
        with self.assertRaises(LitterboxError):
            self.do("Bea", toolbox_admin.copy_in, self.toolbox_source)
        os.chmod(nut, 0o644)                                                        # git by hand, past Litterbox
        nut.write_bytes(b"a bigger nut")
        git(self.b, "commit", "-am", "Changed the nut")
        with self.assertRaises(LitterboxError) as ctx:
            self.check_in("Bea", changed=b"assembly 9")
        self.assertIn("Nothing was uploaded: your changes include files in the team's Toolbox", str(ctx.exception))
        self.assertNotIn("Changed the nut", self.remote_log())

    def test_an_admin_changes_it_and_uploads_the_changes(self):
        self.do("Alex", toolbox_admin.copy_in, self.toolbox_source)
        self.assertEqual(self.do("Alex", toolbox_admin.open_for_changes), 2)
        (self.a / "toolbox" / "browser" / "bolt.sldprt").write_bytes(b"a new size")
        (self.a / "toolbox" / "ToolboxStandards.xml").write_text("<standards v='2'/>", encoding="utf-8")
        status = self.do("Alex", toolbox_admin.status)
        self.assertEqual((status.files, status.changes["added"], status.changes["changed"]),
                         (2, ["toolbox/browser/bolt.sldprt"], ["toolbox/ToolboxStandards.xml"]))
        self.assertEqual(self.do("Alex", toolbox_admin.upload), {"added": 1, "changed": 1, "removed": 0})
        self.assertFalse(os.access(self.a / "toolbox" / "browser" / "bolt.sldprt", os.W_OK))
        self.assertEqual(self.do("Alex", toolbox_admin.upload), {"added": 0, "changed": 0, "removed": 0})
        shutil.rmtree(self.toolbox_source / "browser")
        (self.toolbox_source / "browser").mkdir()
        self.do("Alex", toolbox_admin.copy_in, self.toolbox_source)                 # nut and bolt are gone
        self.assertEqual(sorted(toolbox_admin.tracked(self.a)), ["toolbox/ToolboxStandards.xml"])

    def test_a_folder_that_isnt_a_toolbox_is_refused(self):
        with self.assertRaisesRegex(LitterboxError, "doesn't look like a SolidWorks Toolbox"):
            self.do("Alex", toolbox_admin.copy_in, self.toolbox_source / "browser")


if __name__ == "__main__":
    unittest.main()
