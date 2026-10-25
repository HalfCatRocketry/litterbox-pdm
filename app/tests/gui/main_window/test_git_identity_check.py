"""Tests for gui/main_window/git_identity_check.py: after a refresh, once per vault and session, a missing git name
or email is asked for, and a name other than the team list's is offered the team list's; the answer is set for the
vault only. The window is replaced by stand-ins."""

import unittest
from types import SimpleNamespace

from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace

from litterbox.git import git_identity


class GitIdentityPrompt(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        check = self.gui.git_identity_check
        app = self.gui.app.App.__new__(self.gui.app.App)
        self.said, self.saved, self.asked = [], [], []
        app.repo = lambda: "/vault"
        app._org_name = lambda: "HCR"
        app._say = lambda text, tone="normal": self.said.append((text, tone))
        app.identity = SimpleNamespace(state=check.team_identity.OK,
                                       person=SimpleNamespace(name="Alex Smith", email="alex@x.com"))
        self.app, self.answer, self.git = app, ("Alex Smith", "alex@x.com"), ("", "")
        replace(self, check.git_identity, "current", lambda repo: self.git)
        replace(self, check.git_identity, "save", lambda repo, name, email: self.saved.append((repo, name, email))
                or (name, email))

        test = self

        class Dialog:
            def __init__(self, parent, wanted, vault_name):
                test.asked.append(wanted)

            def show(self):
                return test.answer
        replace(self, check.git_identity_dialog, "GitIdentityDialog", Dialog)

    def test_a_missing_name_and_email_are_asked_for_once_starting_with_the_team_lists(self):
        self.app._check_git_identity()
        self.app._check_git_identity()                        # the next refresh doesn't ask again
        (wanted,) = self.asked
        self.assertEqual((wanted.missing, wanted.name, wanted.email), (("name", "email"), "Alex Smith", "alex@x.com"))
        self.assertEqual(self.saved, [("/vault", "Alex Smith", "alex@x.com")])

    def test_a_different_name_is_offered_the_team_lists(self):
        self.git = ("alex", "alex@home.com")
        self.answer = None                                    # Keep as it is
        self.app._check_git_identity()
        (wanted,) = self.asked
        self.assertEqual((wanted.differs, wanted.name, wanted.email), (True, "Alex Smith", "alex@home.com"))
        self.assertEqual((self.saved, self.said), ([], []))

    def test_not_now_says_nothing_can_be_uploaded(self):
        self.answer = None
        self.app._check_git_identity()
        self.assertEqual(self.saved, [])
        self.assertEqual(self.said[-1][1], "warn")

    def test_nothing_is_asked_when_git_has_the_team_lists_name(self):
        self.git = ("Alex Smith", "alex@home.com")
        self.app._check_git_identity()
        self.assertEqual(self.asked, [])


class Rules(unittest.TestCase):
    def test_without_a_team_list_the_form_starts_with_what_git_has(self):
        wanted = git_identity.wanted(("Alex", ""))
        self.assertEqual((wanted.missing, wanted.name, wanted.differs), (("email",), "Alex", False))

    def test_nothing_needed_when_both_are_set_and_there_is_no_team_name(self):
        self.assertFalse(git_identity.wanted(("Alex", "a@x.com")).needed)

    def test_check_tidies_and_refuses(self):
        self.assertEqual(git_identity.check("  Alex   Smith ", " a@x.com "), ("Alex Smith", "a@x.com"))
        for name, email in (("", "a@x.com"), ("Alex", ""), ("Alex", "ax.com"), ("Alex", "a @x.com"), ("Alex", "@x")):
            with self.assertRaises(git_identity.LitterboxError):
                git_identity.check(name, email)


if __name__ == "__main__":
    unittest.main()
