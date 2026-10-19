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
