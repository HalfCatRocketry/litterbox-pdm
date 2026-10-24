"""Tests for gui/logic/confirmations.py."""

import unittest
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import confirmations


class TestReviseText(unittest.TestCase):
    def test_void_problem(self):
        class R: pn = "X"; released_revision = "A"
        class N: pn = "X"; released_revision = ""
        self.assertIn("Cancel Revision", confirmations.void_problem(R()))
        self.assertEqual(confirmations.void_problem(N()), "")

    def test_revise_texts(self):
        from types import SimpleNamespace as S
        plan = S(pn="X", name="Bracket", revision="A", new_revision="B",
                 copies=[("cad/a_A.SLDPRT", "cad/a_B.SLDPRT")], kept=["cad/a.pdf"])
        t = confirmations.revise_confirm_text(plan)
        self.assertIn("Rev B", t); self.assertIn("a_B.SLDPRT", t); self.assertIn("a.pdf", t)
        self.assertIn("- no", confirmations.revise_problem_text("X", ["- no"]).replace("- - ", "- "))

    def test_cancel_texts(self):
        from types import SimpleNamespace as S
        plan = S(pn="X", name="Bracket", revision="B", back_to="A",
                 moves=[("cad/a_B.SLDPRT", "cad/cancelled-revs/CANCELLED_a_B.SLDPRT")])
        t = confirmations.cancel_confirm_text(plan)
        self.assertIn("CANCELLED_a_B.SLDPRT", t); self.assertIn("back to Rev A", t)
        self.assertIn("can't be cancelled", confirmations.cancel_problem_text("X", ["why"]))

    def test_allowed_kinds(self):
        self.assertEqual(action_rules.ALLOWED_KINDS["revise"], {"released"})
        self.assertIn("cancel_revision", action_rules.ALLOWED_KINDS)


if __name__ == "__main__":
    unittest.main()
