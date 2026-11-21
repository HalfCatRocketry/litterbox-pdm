"""Tests for gui/logic/team_text.py."""

import unittest
from litterbox.gui.logic import team_text
from litterbox.team import team_identity


class TestTeamText(unittest.TestCase):
    def setUp(self):
        from litterbox.team import team_model
        self.d = team_model.Directory([team_model.Person("alex", "Alex Smith", "a@x.com", ["alexs"], team_model.OWNER, ["Quality"]),
                                   team_model.Person("bea", "Bea", "", [], team_model.MEMBER, [], False, ["ssh-ed25519 AAAA"])],
                                  ["Quality"])

    def test_banner(self):
        self.assertEqual(team_text.identity_banner(team_identity.Identity(team_identity.LEGACY))[1], "normal")
        text, tone = team_text.identity_banner(team_identity.resolve(self.d, "alexs"))
        self.assertEqual((tone, "Alex Smith" in text, "Owner" in text, "Quality" in text), ("normal", True, False, False))
        for host in ("stranger", "", ):
            self.assertEqual(team_text.identity_banner(team_identity.resolve(self.d, host))[1], "warn")
        self.assertEqual(team_text.identity_banner(team_identity.Identity(team_identity.INACTIVE))[1], "warn")

    def test_people_table(self):
        rows = team_text.people_table(self.d)
        self.assertEqual(rows[0], ("alex", ("Alex Smith", "a@x.com", "Owner", "Quality", "Yes", "alexs", "")))
        self.assertEqual(rows[1][1][4:], ("No", "", 1))

    def test_person_details(self):
        text = team_text.person_details(self.d.people[0])
        self.assertIn("Alex Smith (alex): Owner", text)
        self.assertIn("Roles: Quality", text)
        self.assertIn("Host names: alexs", text)
        self.assertIn("Signing keys: none", text)
        self.assertIn("switched off", team_text.person_details(self.d.people[1]))
        self.assertIn("Signing keys: 1", team_text.person_details(self.d.people[1]))

    def test_lists_and_ids(self):
        self.assertEqual(team_text.split_list("a, b\nc,, "), ["a", "b", "c"])
        self.assertEqual(team_text.suggest_person_id("Alex Smith", []), "alex-smith")
        self.assertEqual(team_text.suggest_person_id("Alex Smith", ["alex-smith", "alex-smith-2"]), "alex-smith-3")
        self.assertEqual(team_text.suggest_person_id("!!!", []), "person")

    def test_who_am_i(self):
        self.assertIn("matches Alex Smith", team_text.who_am_i_text(team_identity.resolve(self.d, "ALEXS")))
        self.assertIn("not on this vault's team list", team_text.who_am_i_text(team_identity.resolve(self.d, "stranger")))
        self.assertIn("no team list yet", team_text.who_am_i_text(team_identity.Identity(team_identity.LEGACY, "x")))

    def test_who_am_i_says_which_name_to_add(self):
        text = team_text.who_am_i_text(team_identity.resolve(self.d, "cubesat-cy"))
        self.assertIn("with 'cubesat-cy' as your user name on the host", text)
        self.assertNotIn("as your user name", team_text.who_am_i_text(team_identity.resolve(self.d, "alexs")))


class TestProbeFailures(unittest.TestCase):
    """Why the host couldn't say who you are: only a busy lock is worth waiting for, and each reason says what to do."""

    def test_only_a_busy_lock_is_waited_for(self):
        self.assertTrue(team_identity.lock_is_busy("Locking .litterbox/whoami failed: Lock exists"))
        self.assertTrue(team_identity.lock_is_busy("Lock failed: .litterbox/whoami already locked by Alex"))
        for other in ("error: 403 Forbidden", "fatal: Authentication failed", "Could not resolve host: github.com"):
            self.assertFalse(team_identity.lock_is_busy(other))

    def test_reasons(self):
        cases = {"Locking failed: You must have push access to verify locks (403)": "Write role",
                 "fatal: Authentication failed for 'https://github.com/x/y.git/'": "isn't signed in",
                 "remote: Repository not found.": "accepted the invitation",
                 "fatal: unable to access: Could not resolve host: github.com": "Could not resolve host"}
        for error, words in cases.items():
            self.assertIn(words, team_identity.probe_failure_text(error), error)
        self.assertEqual(team_identity.probe_failure_text(""), "Could not ask the host who you are (offline?).")

    def test_a_reason_that_is_a_sentence_reads_as_one(self):
        who = team_identity.Identity(team_identity.UNVERIFIED, detail=team_identity.HOST_NOT_REACHED)
        self.assertIn("signed in as. Git couldn't reach", who.message())
        self.assertTrue(who.message().endswith("You can still look at parts and open files."))
        short = team_identity.Identity(team_identity.UNVERIFIED, detail="offline?").message()
        self.assertIn("signed in as (offline?). Connect to the internet", short)

    def test_person_form(self):
        form = {"name": " Cy  Ng ", "email": "cy@x.com", "host_names": "cyng, Cy Ng", "roles": "Quality",
                "keys": "ssh-ed25519 AAA, with comma\nssh-ed25519 BBB", "access": "Member"}
        problem, fields = team_text.person_form_result(None, form, ["alex"])
        self.assertEqual(problem, "")
        self.assertEqual((fields["id"], fields["name"], fields["host_names"], fields["access"]),
                         ("cy-ng", "Cy Ng", ["cyng", "Cy Ng"], "member"))
        self.assertEqual(fields["signing_keys"], ["ssh-ed25519 AAA, with comma", "ssh-ed25519 BBB"])
        self.assertNotIn("id", team_text.person_form_result("cy", form, [])[1])                # editing: the id stays
        self.assertIn("name", team_text.person_form_result(None, dict(form, name=" "), [])[0])
        self.assertIn("email", team_text.person_form_result(None, dict(form, email="nope"), [])[0])


class TestRoleHelpers(unittest.TestCase):
    def test_add_role_result(self):
        self.assertEqual(team_text.add_role_result("  Welding   Lead ", ["Quality"]), ("", "Welding Lead"))
        self.assertTrue(team_text.add_role_result("", [])[0])
        self.assertTrue(team_text.add_role_result("a,b", [])[0])
        self.assertIn("already", team_text.add_role_result("quality", ["Quality"])[0])

    def test_role_removal_text(self):
        self.assertIn("Remove the role 'Q'", team_text.role_removal_text("Q", []))
        t = team_text.role_removal_text("Q", ["Ann", "Bob"])
        self.assertIn("Ann, Bob", t)
        self.assertIn("Save", t)

    def test_roles_to_choose(self):
        self.assertEqual(team_text.roles_to_choose(["A", "B", "C"], ["b"]), ["A", "C"])


if __name__ == "__main__":
    unittest.main()
