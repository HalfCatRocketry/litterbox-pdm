"""Tests for user/bug_report.py and user/report_mail.py: Help > Report a problem's zip, and handing it to email."""

import tempfile
import unittest
import urllib.parse
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from litterbox import diagnostics
from litterbox import version
from litterbox.errors import LitterboxError
from litterbox.gui.logic import bug_report_text
from litterbox.user import bug_report
from litterbox.user import report_mail
from litterbox.user import settings

FACTS = [("Litterbox", "0.6.1"), ("Git", "git version 2.47.0")]


class Redaction(unittest.TestCase):
    def test_passwords_and_tokens_are_taken_out(self):
        text = ("> git clone https://alex:s3cret@dev.azure.com/team/_git/vault\n"
                "token ghp_abcdefghijklmnopqrstuvwxyz0123 used\n"
                "Authorization: Basic YWxleDpzM2NyZXQ=\n"
                "ssh://git@github.com/org/repo.git")
        clean = bug_report.redact(text)
        for secret in ("s3cret", "alex:", "ghp_abcdef", "YWxleDpzM2NyZXQ=", "git@"):
            self.assertNotIn(secret, clean)
        self.assertIn("https://dev.azure.com/team/_git/vault", clean)
        self.assertIn("[token removed]", clean)

    def test_ordinary_text_is_left_alone(self):
        text = "Checked in HCR-00042-001 (C:\\Litterbox\\hcr\\cad\\HCR-00042-001_A.SLDPRT) at 12:30"
        self.assertEqual(bug_report.redact(text), text)


class MakingTheReport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        log = self.dir / "logs" / "litterbox.log"
        log.parent.mkdir()
        log.write_text("> git push https://alex:token123@host/repo\n", encoding="utf-8")
        (self.dir / "settings.yaml").write_text("repo: C:\\Litterbox\\hcr\n", encoding="utf-8")
        vault = self.dir / "vault"
        (vault / ".litterbox").mkdir(parents=True)
        (vault / ".litterbox" / "config.yaml").write_text("org_code: HCR\n", encoding="utf-8")
        self.vault = vault
        for name, value in (("LOG_FILE", log), ("SETTINGS_FILE", self.dir / "settings.yaml")):
            patcher = mock.patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(bug_report, "facts", lambda: FACTS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, **kwargs):
        return bug_report.make("I pressed Check In", str(self.vault), [("Checking in 1 part", "Unexpected error")],
                               folder=self.dir / "reports", **kwargs)

    def test_the_zip_holds_the_report_log_and_settings_without_secrets(self):
        diagnostics.note_unexpected("checking in 1 part", "Traceback (most recent call last):\n  KeyError: 'x'\n")
        with zipfile.ZipFile(self.make()) as zipped:
            names = set(zipped.namelist())
            report = zipped.read("report.txt").decode("utf-8")
            log = zipped.read("litterbox.log").decode("utf-8")
        self.assertEqual(names, {"report.txt", "litterbox.log", "settings.yaml", "vault-config.yaml", "CONTENTS.txt"})
        self.assertIn("I pressed Check In", report)
        self.assertIn("Git: git version 2.47.0", report)
        self.assertIn("Checking in 1 part: Unexpected error", report)
        self.assertIn("KeyError: 'x'", report)
        self.assertNotIn("token123", log)

    def test_the_zip_holds_exactly_what_the_window_lists(self):
        for leave_out in ((), (bug_report.LOG,), (bug_report.SETTINGS,), (bug_report.LOG, bug_report.SETTINGS)):
            listed = [item.name for item in bug_report.contents(str(self.vault), leave_out)]
            with zipfile.ZipFile(self.make(leave_out=leave_out, now=datetime(2026, 1, 1, 0, len(leave_out)))) as z:
                self.assertEqual(z.namelist(), listed + ["CONTENTS.txt"], leave_out)
                contents = z.read("CONTENTS.txt").decode("utf-8")
            for name in listed:
                self.assertIn(name, contents)
            self.assertIn("Never in a report", contents)

    def test_leaving_things_out(self):
        names = lambda leave_out: [item.name for item in bug_report.contents(str(self.vault), leave_out)]
        self.assertEqual(names(()), ["report.txt", "litterbox.log", "settings.yaml", "vault-config.yaml"])
        self.assertEqual(names((bug_report.LOG,)), ["report.txt", "settings.yaml", "vault-config.yaml"])
        self.assertEqual(names((bug_report.LOG, bug_report.SETTINGS)), ["report.txt"])
        self.assertTrue(all(item.what for item in bug_report.contents(str(self.vault))))

    def test_sizes_are_listed_and_a_log_is_counted_up_to_what_goes_in(self):
        items = {item.name: item for item in bug_report.contents(str(self.vault))}
        self.assertIsNone(items["report.txt"].size)
        self.assertEqual(items["settings.yaml"].size, (self.dir / "settings.yaml").stat().st_size)
        with mock.patch.object(bug_report, "LOG_BYTES", 5):
            self.assertEqual(bug_report.contents(str(self.vault))[1].size, 5)

    def test_a_comment_is_required(self):
        with self.assertRaises(LitterboxError):
            bug_report.make("  ", str(self.vault), folder=self.dir / "reports")

    def test_only_the_newest_reports_are_kept(self):
        start = datetime(2026, 10, 24, 9, 0, 0)
        for minute in range(bug_report.KEEP + 2):
            self.make(now=start + timedelta(minutes=minute))
        kept = sorted(p.name for p in (self.dir / "reports").glob("*.zip"))
        self.assertEqual(len(kept), bug_report.KEEP)
        self.assertEqual(kept[-1], "litterbox-report-20261024-090600.zip")

    def test_without_a_vault_there_is_no_vault_config(self):
        path = bug_report.make("It wouldn't start", "", folder=self.dir / "reports")
        with zipfile.ZipFile(path) as zipped:
            self.assertNotIn("vault-config.yaml", zipped.namelist())

    def test_the_email(self):
        self.assertIn(version.VERSION, bug_report.subject("HCR"))
        self.assertIn("HCR", bug_report.subject("HCR"))
        body = bug_report.body("I pressed Check In", FACTS)
        self.assertTrue(body.startswith("What I was doing:\nI pressed Check In"))
        self.assertIn("Litterbox: 0.6.1", body)


class Sending(unittest.TestCase):
    def test_the_mail_link_fills_in_subject_and_body_and_stays_short(self):
        link = report_mail.mail_link("contact+litterbug@halfcatrocketry.com", "Problem (0.6.1)", "x" * 5000)
        self.assertTrue(link.startswith("mailto:contact+litterbug@halfcatrocketry.com?"))
        query = urllib.parse.parse_qs(link.split("?", 1)[1])
        self.assertEqual(query["subject"], ["Problem (0.6.1)"])
        self.assertLess(len(query["body"][0]), report_mail.MAX_LINK_BODY + 10)

    def test_outlook_when_it_opens_the_message(self):
        with mock.patch.object(report_mail, "has_outlook", return_value=True), \
                mock.patch.object(report_mail, "_outlook", return_value=True) as outlook:
            how = report_mail.send("a@b.c", "s", "body", Path("r.zip"))
        self.assertEqual(how, report_mail.OUTLOOK)
        outlook.assert_called_once()

    def test_otherwise_the_mail_link_and_explorer(self):
        opened = []
        with mock.patch.object(report_mail, "has_outlook", return_value=True), \
                mock.patch.object(report_mail, "_outlook", return_value=False), \
                mock.patch.object(report_mail.os, "startfile", opened.append, create=True), \
                mock.patch.object(report_mail.subprocess, "Popen") as popen:
            how = report_mail.send("a@b.c", "s", "body", Path("r.zip"))
        self.assertEqual(how, report_mail.MAIL_LINK)
        self.assertIn("r.zip", urllib.parse.unquote(opened[0]))
        self.assertEqual(popen.call_args[0][0][:2], ["explorer", "/select,"])


class Words(unittest.TestCase):
    def test_intro_counts_the_problems(self):
        self.assertIn("The 1 problem in the red status bar goes in too", bug_report_text.intro("a@b.c", 1))
        self.assertIn("The 2 problems in the red status bar go in too", bug_report_text.intro("a@b.c", 2))
        self.assertNotIn("status bar", bug_report_text.intro("a@b.c", 0))
        self.assertIn("a@b.c", bug_report_text.intro("a@b.c", 0))

    def test_sizes_in_plain_words(self):
        self.assertEqual(bug_report_text.size_text(None), "")
        self.assertEqual(bug_report_text.size_text(10), "under 1 KB")
        self.assertEqual(bug_report_text.size_text(12_500), "about 12 KB")
        self.assertEqual(bug_report_text.size_text(2_000_000), "about 1.9 MB")
        item = bug_report.Item("litterbox.log", "x", size=12_500)
        self.assertEqual(bug_report_text.item_heading(item), "litterbox.log  (about 12 KB)")
        self.assertEqual(bug_report_text.item_heading(bug_report.Item("report.txt", "x")), "report.txt")

    def test_after_sending(self):
        self.assertIn("Press Send", bug_report_text.sent_text(report_mail.OUTLOOK, "r.zip"))
        self.assertIn("Attach the report", bug_report_text.sent_text(report_mail.MAIL_LINK, "r.zip"))


if __name__ == "__main__":
    unittest.main()
