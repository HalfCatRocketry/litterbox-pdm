"""Tests for Help > Report a problem's wiring (gui/main_window/problem_reports.py). The window itself is replaced by
stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import types
import unittest
from unittest import mock

from tests.support.gui_fakes import FakeBox, load_gui_with_fakes


class ReportWiring(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.jobs = types.SimpleNamespace(errors=lambda: [])
        app.repo = lambda: "C:/Litterbox/vault"
        app.org = "HCR"
        app._say = lambda text, tone="normal": None
        self.app = app

    def answer_dialog(self, answer):
        """BugReportDialog stands in: notes how it was made and answers `answer`."""
        made = []

        class Dialog:
            def __init__(self, *args):
                made.append(args)

            def show(self):
                return answer
        original = self.gui.bug_report_dialog.BugReportDialog
        self.gui.bug_report_dialog.BugReportDialog = Dialog
        self.addCleanup(setattr, self.gui.bug_report_dialog, "BugReportDialog", original)
        return made

    def test_the_window_lists_the_reports_contents_for_this_vault(self):
        made = self.answer_dialog(None)
        listed = []
        original = self.gui.bug_report.contents
        self.gui.bug_report.contents = lambda repo, leave_out=(): listed.append((repo, leave_out)) or []
        self.addCleanup(setattr, self.gui.bug_report, "contents", original)
        self.app.report_problem()
        list_contents = made[0][3]
        list_contents(("log",))
        self.assertEqual(listed, [("C:/Litterbox/vault", ("log",))])
        self.assertIn("Never in a report", made[0][5])
        self.assertTrue(made[0][6].endswith("/PRIVACY.md"))                # the window links to the privacy policy

    def test_what_is_left_out_is_left_out_of_the_report(self):
        self.answer_dialog(("It froze", ("log",)))
        made = []
        original_make, original_send = self.gui.bug_report.make, self.gui.report_mail.send
        self.gui.bug_report.make = lambda comment, repo, problems, leave_out=(): made.append((comment, leave_out)) or "r.zip"
        self.gui.report_mail.send = lambda *a: "mail_link"
        self.addCleanup(setattr, self.gui.bug_report, "make", original_make)
        self.addCleanup(setattr, self.gui.report_mail, "send", original_send)
        self.app.queue = __import__("queue").Queue()
        with mock.patch.object(self.gui.problem_reports.threading, "Thread",
                               lambda target, **k: types.SimpleNamespace(start=target)):      # runs it right away
            self.app.report_problem()
        self.assertEqual(made, [("It froze", ("log",))])

    def test_with_outlook_it_offers_to_open_the_report(self):
        opened = []
        original = self.gui.opener.open_path
        self.gui.opener.open_path = lambda path: opened.append(path)
        self.addCleanup(setattr, self.gui.opener, "open_path", original)
        self.box.answer = True
        self.app._report_sent("outlook", "r.zip")
        self.assertEqual((self.box.calls[-1][0], opened), ("askyesno", ["r.zip"]))
        self.app._report_sent("mail_link", "r.zip")
        self.assertEqual((self.box.calls[-1][0], opened), ("showinfo", ["r.zip"]))


if __name__ == "__main__":
    unittest.main()
