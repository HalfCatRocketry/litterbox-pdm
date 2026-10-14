"""Tests for gui/logic/action_rules.py: which buttons act on which parts, and batch summaries."""

import unittest
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import confirmations
from litterbox.gui.logic import history_text
from litterbox.gui.logic import list_view
from litterbox.gui.logic import opening_text
from litterbox.gui.logic import team_text
from litterbox.errors import LitterboxError
from litterbox.core.part_number import PN
from tests.support.part_rows import row, ROWS, BY_PN


class TestPlanAction(unittest.TestCase):
    def plan(self, action, *bases):
        return action_rules.plan_action(action, [PN("HCR", b, 1) for b in bases], BY_PN)

    def test_nothing_selected(self):
        self.assertEqual(self.plan("checkout").message, "Select a part first (use its box on the left).")

    def test_checkout_uses_only_available_parts(self):
        plan = self.plan("checkout", 1, 2, 3)
        self.assertEqual([p.base for p in plan.targets], [1])
        self.assertEqual([(p.base, why) for p, why in plan.skipped],
                         [(2, "Checked out by you"), (3, "Checked out by Alex")])
        self.assertEqual(plan.message, "")

    def test_checkin_undo_save_need_your_own_checkout(self):
        for action in ("checkin", "save", "undo"):
            with self.subTest(action=action):
                self.assertEqual([p.base for p in self.plan(action, 1, 2, 3).targets], [2])

    def test_message_when_nothing_qualifies(self):
        plan = self.plan("checkout", 3)
        self.assertEqual(plan.targets, [])
        self.assertEqual(plan.message, "Can't check out HCR-00003-001: Checked out by Alex.")
        self.assertIn("None of the selected", self.plan("checkout", 3, 4).message)

    def test_single_part_actions_refuse_multiple_selection(self):
        for action in ("edit", "revise", "open"):
            with self.subTest(action=action):
                self.assertIn("just one", self.plan(action, 1, 6).message)

    def test_release_reopen_void_eligibility(self):
        self.assertEqual([p.base for p in self.plan("release", 1).targets], [1])
        self.assertIn("Can't release", self.plan("release", 4).message)      # already released
        self.assertIn("Can't release", self.plan("release", 2).message)      # checked out
        self.assertEqual([p.base for p in self.plan("reopen", 4).targets], [4])
        self.assertIn("Can't unrelease", self.plan("reopen", 1).message)
        self.assertEqual([p.base for p in self.plan("void", 1).targets], [1])
        self.assertIn("Can't void", self.plan("void", 4).message)

    def test_make_cots_and_cots_rows(self):
        cots = row(7, "COTS part", "cots", "Bolt")
        by_pn = {**BY_PN, cots.pn: cots}
        self.assertEqual([p.base for p in action_rules.plan_action("make_cots", [ROWS[0].pn], by_pn).targets], [1])
        for base in (2, 3, 4):                                   # checked out / released
            self.assertIn("Can't make COTS", action_rules.plan_action("make_cots", [PN("HCR", base, 1)], by_pn).message)
        self.assertIn("Can't make COTS", action_rules.plan_action("make_cots", [cots.pn], by_pn).message)
        self.assertIn("COTS part", action_rules.plan_action("checkout", [cots.pn], by_pn).message)
        self.assertIn("Can't release", action_rules.plan_action("release", [cots.pn], by_pn).message)
        self.assertEqual(action_rules.plan_action("reopen", [cots.pn], by_pn).targets, [cots.pn])
        self.assertIn("checked out", confirmations.reopen_cots_warning("HCR-00007-001"))
        self.assertEqual(action_rules.plan_action("void", [cots.pn], by_pn).targets, [cots.pn])

    def test_edit_details_needs_one_part_you_have_checked_out(self):
        self.assertEqual([p.base for p in self.plan("edit", 2).targets], [2])
        self.assertIn("Can't edit the details of", self.plan("edit", 1).message)       # not checked out
        self.assertIn("Can't edit the details of", self.plan("edit", 3).message)       # someone else's
        self.assertIn("just one", self.plan("edit", 2, 6).message)

    def test_edit_details_result(self):
        self.assertEqual(confirmations.edit_details_result("A", "d", "  ", "d"), ("A name is required.", False))
        self.assertEqual(confirmations.edit_details_result("A", "d", "A ", " d"), ("", False))
        self.assertEqual(confirmations.edit_details_result("A", "d", "B", "d"), ("", True))
        self.assertEqual(confirmations.edit_details_result("A", "", "A", "x"), ("", True))

    def test_history_shows_edit_changes(self):
        event = {"event": "edited", "by": "Alex", "at": "2026-10-05T14:02:41Z", "changes": ["name: 'A' -> 'B'"]}
        fake = type("R", (), {"history": [event]})()
        _when, _who, what, details = history_text.format_history(fake)[0]
        self.assertEqual((what, details), ("Edited details", "name: 'A' -> 'B'"))

    def test_open_is_for_one_downloaded_part(self):
        self.assertEqual([p.base for p in self.plan("open", 1).targets], [1])
        for base in (2, 3, 4, 5, 6):                   # mine, theirs, released, void, stray
            self.assertEqual(len(self.plan("open", base).targets), 1, base)
        self.assertIn("just one", self.plan("open", 1, 2).message)
        missing = row(8, "Not downloaded", "missing", "Gone")
        message = action_rules.plan_action("open", [missing.pn], {missing.pn: missing}).message
        self.assertIn("Can't open", message)
        self.assertIn("no CAD files", opening_text.open_message(row(9, files=[])))
        self.assertEqual(opening_text.open_message(row(9, files=["cad/x.SLDPRT"])), "")
        self.assertIn("no drawing", opening_text.open_message(row(9, files=["cad/x.SLDPRT"]), drawing=True))
        self.assertEqual(opening_text.open_message(row(9, files=["cad/x.SLDPRT", "cad/x.SLDDRW"]), drawing=True), "")
        self.assertEqual([p.base for p in self.plan("open_drawing", 4).targets], [4])
        self.assertIn("just one", self.plan("open_drawing", 1, 2).message)

    def test_make_cots_texts(self):
        text = confirmations.make_cots_confirm_text("HCR-00001-001", "Bolt", ["cad/a.SLDPRT"])
        self.assertIn("NOT modified", text)
        self.assertIn("cad/a.SLDPRT", text)
        self.assertIn("- It is checked out", confirmations.make_cots_problem_text("HCR-00001-001", ["It is checked out"]))

    def test_part_not_in_list(self):
        plan = action_rules.plan_action("checkout", [PN("HCR", 99, 1)], BY_PN)
        self.assertIn("not in the list", plan.message)

    def test_every_action_is_described(self):
        for action in action_rules.ALLOWED_KINDS:
            self.assertIn(action, action_rules.NAME)
            self.assertIn(action, action_rules.PAST)


class TestBatchAndSummary(unittest.TestCase):
    def test_run_batch_carries_on_after_a_failure(self):
        def func(pn):
            if pn == "bad":
                raise LitterboxError("nope")
            return pn.upper()
        done, failed = action_rules.run_batch(["a", "bad", "c"], func)
        self.assertEqual(done, [("a", "A"), ("c", "C")])
        self.assertEqual(failed, [("bad", "nope")])

    def test_run_batch_does_not_hide_programming_errors(self):
        with self.assertRaises(ZeroDivisionError):
            action_rules.run_batch([1], lambda pn: 1 / 0)

    def test_summary(self):
        self.assertEqual(action_rules.summary("checkout", 1), "Checked out 1 part")
        self.assertEqual(action_rules.summary("checkout", 3), "Checked out 3 parts")
        self.assertEqual(action_rules.summary("checkin", 2, failed=1), "Checked in 2 parts, 1 failed")
        self.assertEqual(action_rules.summary("checkout", 1, skipped=2), "Checked out 1 part, skipped 2")
        self.assertEqual(action_rules.summary("checkout", 0, failed=2), "Could not check out 2 parts")
        self.assertEqual(action_rules.summary("save", 1), "Saved progress on 1 part")


class TestTicks(unittest.TestCase):
    A, B, C = PN("HCR", 1, 1), PN("HCR", 2, 1), PN("HCR", 3, 1)

    def test_actions_that_change_things_use_only_the_selected_boxes(self):
        for action in ("checkout", "checkin", "save", "undo", "release", "edit", "revise", "void"):
            self.assertEqual(action_rules.choose_targets(action, [self.A, self.B], [self.C]), [self.A, self.B])
            self.assertEqual(action_rules.choose_targets(action, [], [self.C]), [])

    def test_looking_at_a_part_uses_the_highlighted_row(self):
        for action in ("open", "open_drawing", "references"):
            self.assertEqual(action_rules.choose_targets(action, [self.A, self.B], [self.C]), [self.C])

    def test_looking_falls_back_to_the_only_selected_part(self):
        self.assertEqual(action_rules.choose_targets("open", [self.A], []), [self.A])
        self.assertEqual(action_rules.choose_targets("open", [self.A, self.B], []), [])

    def test_row_tags(self):
        self.assertEqual(list_view.row_tags("mine", False), ("mine",))
        self.assertEqual(list_view.row_tags("mine", True), ("mine", "ticked"))

    def test_undo_prompt_lists_each_part_on_its_own_line(self):
        text = checkin_text.undo_prompt([self.A, self.B])
        self.assertTrue(text.startswith("This will discard changes and release the lock on these parts:"))
        self.assertIn(f"\n{self.A}\n{self.B}\n", text)
        self.assertTrue(text.endswith("Continue?"))

    def test_the_banner_shows_only_the_name(self):
        from litterbox.team import team_identity
        from litterbox.team import team_model
        who = team_model.Person("bea", "Bea Jones", "", ["Bea"], "member", ["Quality"])
        self.assertEqual(team_identity.Identity.describe(type("I", (), {"state": team_identity.OK, "person": who})()),
                         "Bea Jones")

    def test_tick_text(self):
        self.assertEqual(list_view.tick_text(0), "Nothing selected.")
        self.assertTrue(list_view.tick_text(1).startswith("1 part selected."))
        self.assertTrue(list_view.tick_text(3).startswith("3 parts selected."))

    def test_person_unchanged(self):
        from litterbox.team import team_model
        who = team_model.Person("bea", "Bea", "b@x.com", ["Bea"], "member", ["Quality"])
        same = {"name": "Bea", "email": "b@x.com", "host_names": ["Bea"], "access": "member", "roles": ["Quality"]}
        self.assertTrue(team_text.person_unchanged(who, same))
        self.assertFalse(team_text.person_unchanged(who, dict(same, roles=[])))
        self.assertFalse(team_text.person_unchanged(who, dict(same, name="Bea J")))


class TestButtonStates(unittest.TestCase):
    P = {r.pn.base: r.pn for r in ROWS}                 # base number -> PN (1 ok, 2 mine, 3 theirs, 4 released, 5 void, 6 stray)

    def states(self, ticked=(), highlighted=()):
        return action_rules.button_states([self.P[b] for b in ticked], [self.P[b] for b in highlighted], BY_PN)

    def test_nothing_selected_greys_everything(self):
        self.assertFalse(any(self.states().values()))

    def test_one_available_part(self):
        s = self.states(ticked=[1])
        self.assertTrue(s["Check Out"])
        self.assertTrue(s["Release"] and s["Void"] and s["Make COTS"])
        self.assertFalse(s["Check In"] or s["Undo Checkout"] or s["Save Progress"] or s["Edit Details"])
        self.assertFalse(s["Revise"] or s["Unrelease"])

    def test_one_checked_out_part_in_the_selection_greys_check_out(self):
        self.assertFalse(self.states(ticked=[1, 2])["Check Out"])
        self.assertTrue(self.states(ticked=[1, 3])["Check Out"] is False)

    def test_check_in_needs_every_part_to_be_yours(self):
        self.assertTrue(self.states(ticked=[2])["Check In"])
        self.assertFalse(self.states(ticked=[2, 1])["Check In"])

    def test_revise_and_unrelease_need_released_parts(self):
        s = self.states(ticked=[4])
        self.assertTrue(s["Revise"] and s["Unrelease"])
        self.assertFalse(s["Check Out"] or s["Release"])
        self.assertFalse(self.states(ticked=[1])["Revise"])

    def test_single_part_buttons_grey_with_two_parts(self):
        self.assertTrue(self.states(ticked=[2])["Edit Details"])
        both = action_rules.button_states([self.P[4], self.P[1]], [], BY_PN)
        self.assertFalse(both["Revise"] or both["Edit Details"])

    def test_looking_buttons_follow_the_highlight(self):
        s = self.states(ticked=[1, 2], highlighted=[3])
        self.assertTrue(s["Open"] and s["Open Drawing"] and s["References..."] and s["History"])
        self.assertFalse(s["Check In"])                          # the changing buttons ignore the highlight
        self.assertFalse(self.states(ticked=[1, 2])["Open"])      # two ticks, nothing highlighted
        self.assertTrue(self.states(ticked=[1])["History"])       # one tick stands in for a highlight

    def test_void_parts_can_be_looked_at_but_not_changed(self):
        s = self.states(ticked=[5])
        self.assertTrue(s["Open"])
        self.assertFalse(s["Check Out"] or s["Release"] or s["Void"])

    def test_the_unrelease_button_uses_the_reopen_action(self):
        self.assertEqual(action_rules.BUTTON_ACTIONS["Unrelease"], "reopen")
        self.assertEqual(action_rules.NAME["reopen"], "unrelease")
        self.assertEqual(action_rules.PAST["reopen"], "Unreleased")


if __name__ == "__main__":
    unittest.main()
