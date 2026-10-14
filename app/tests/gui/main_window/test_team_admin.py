"""Tests for read-only mode and the Team window's actions in the main window. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from litterbox.team import team_identity
from litterbox.team import team_model
from tests.support.gui_fakes import FakeBox, fake_jobs, load_gui_with_fakes


class TeamWiring(unittest.TestCase):
    """Read-only mode in the window: who may press what."""

    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        from litterbox.parts.part_status import PartStatus
        from litterbox.core.part_number import PN
        self.pn = PN("HCR", 7, 1)
        row = PartStatus(self.pn, "Part", "in_work", "Available", "ok", files=["cad/HCR-00007-001_A.SLDPRT"],
                         revisions={"A": ["cad/HCR-00007-001_A.SLDPRT"]})
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.rows_by_pn = {self.pn: row}
        app._selected_pns = lambda action=None: [self.pn]
        self.said = []
        app._say = lambda text, tone="normal": self.said.append((text, tone))
        self.app = app

    def test_legacy_vaults_allow_everything(self):
        self.app.identity = team_identity.Identity(team_identity.LEGACY)
        self.assertIsNotNone(self.app._plan("checkout"))

    def test_someone_not_listed_can_look_but_every_change_is_refused_with_the_reason(self):
        self.app.identity = team_identity.Identity(team_identity.NOT_LISTED, "stranger")
        for action in ("checkout", "checkin", "release", "revise", "edit", "void"):
            self.said.clear()
            self.assertIsNone(self.app._plan(action), action)
            self.assertIn("not on this vault's team list", self.said[0][0])
        for action in ("open", "open_drawing", "references"):
            self.assertIsNotNone(self.app._plan(action), action)

    def test_new_part_and_import_are_refused_too(self):
        self.app.identity = team_identity.Identity(team_identity.UNVERIFIED)
        self.app.jobs = fake_jobs()
        self.app.new_part()
        self.app.import_cad()
        self.assertEqual(len(self.said), 2)
        self.assertTrue(all(tone == "warn" for _t, tone in self.said))

    def test_a_member_may_work_but_not_manage_people(self):
        person = team_model.Person("m", "M")
        self.app.identity = team_identity.Identity(team_identity.OK, "m", person)
        self.assertIsNotNone(self.app._plan("checkout"))
        self.assertFalse(self.app._may("manage_people"))
        self.assertIn("Only an Admin", self.said[-1][0])


if __name__ == "__main__":
    unittest.main()
