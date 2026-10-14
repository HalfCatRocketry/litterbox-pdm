"""
Tests for people.py: the team file, who the current user is, what each role may do, read-only mode,
the check before pushing, and saving changes to the team file. Uses the two-user vault from vault_fixture
(Alex and Bea; the fake LFS reports the user name as the lock owner). They need Linux, macOS or WSL.

Run from the app folder with:  python -m unittest discover -s tests -t . -v
"""

import time
import unittest
from unittest import mock

from tests.support.vault_fixture import DRW, PART, PRT, REC, git

from litterbox.parts import engine as eng
from litterbox.team import people
from litterbox.records import registry
from tests.support.team_fixture import TeamFixture
from litterbox.errors import LitterboxError


def directory(*extra, roles=("Quality", "Manufacturing")):
    d = people.Directory([people.Person("alex", "Alex Smith", "alex@x.com", ["Alex"], people.OWNER)], list(roles))
    d.people.extend(extra)
    people.validate(d)
    return d


class TestRules(unittest.TestCase):
    def setUp(self):
        self.d = directory()
        self.owner = self.d.get("alex")

    def test_exactly_one_owner(self):
        d = directory()
        d.people.append(people.Person("bea", "Bea", "", [], people.OWNER))
        with self.assertRaises(people.PeopleError):
            people.validate(d)
        d.people[1].access = people.MEMBER
        d.people[0].access = people.ADMIN
        with self.assertRaises(people.PeopleError):
            people.validate(d)

    def test_bad_entries_are_refused(self):
        for bad in (people.Person("Bad Id", "x"), people.Person("x", ""), people.Person("x", "X", "no-at-sign"),
                    people.Person("x", "X", access="king"), people.Person("alex", "Dup"),
                    people.Person("x", "X", host_names=["alex"]),                     # host name of another person
                    people.Person("x", "X", roles=["Wizard"]),
                    people.Person("x", "X", signing_keys=["not a key"])):
            d = directory()
            d.people.append(bad)
            with self.assertRaises(people.PeopleError, msg=bad):
                people.validate(d)

    def test_role_names_are_tidied_to_the_orgs_spelling(self):
        d = directory(people.Person("bea", "Bea", roles=["quality"]))
        self.assertEqual(d.get("bea").roles, ["Quality"])

    def test_file_round_trip(self):
        d = directory(people.Person("bea", "Bea", "b@x.com", ["bea1", "Bea B"], people.ADMIN, ["Quality"], False,
                                    ["ssh-ed25519 AAAA"]))
        again = people.from_dict(__import__("yaml").safe_load(people._dump(d)))
        self.assertEqual(again.to_dict(), d.to_dict())

    def test_lookup_by_host_name_ignores_case(self):
        self.assertEqual(self.d.find_by_host_name("ALEX").id, "alex")
        self.assertIsNone(self.d.find_by_host_name("nobody"))
        self.assertIsNone(self.d.find_by_host_name(""))

    def test_admins_manage_members_but_not_admins(self):
        people.add_person(self.d, self.owner, "bea", "Bea", host_names=["Bea"], access=people.ADMIN)
        people.add_person(self.d, self.owner, "cy", "Cy", host_names=["Cy"])
        bea = self.d.get("bea")
        people.update_person(self.d, bea, "cy", email="cy@x.com", roles=["Quality"])        # a member: fine
        people.set_active(self.d, bea, "cy", False)
        with self.assertRaises(people.PeopleError):
            people.add_person(self.d, bea, "dee", "Dee", access=people.ADMIN)               # only the Owner makes Admins
        with self.assertRaises(people.PeopleError):
            people.set_active(self.d, self.d.get("cy"), "bea", False)
        people.add_person(self.d, self.owner, "dee", "Dee", access=people.ADMIN)
        with self.assertRaises(people.PeopleError):
            people.set_active(self.d, bea, "dee", False)                                     # an Admin can't switch an Admin off
        people.set_active(self.d, self.owner, "dee", False)

    def test_the_owner_cannot_be_switched_off_or_created(self):
        with self.assertRaises(people.PeopleError):
            people.set_active(self.d, self.owner, "alex", False)
        with self.assertRaises(people.PeopleError):
            people.add_person(self.d, self.owner, "bea", "Bea", access=people.OWNER)
        with self.assertRaises(people.PeopleError):
            people.update_person(self.d, self.owner, "alex", access=people.MEMBER)

    def test_transfer_ownership(self):
        people.add_person(self.d, self.owner, "bea", "Bea", host_names=["Bea"], access=people.ADMIN)
        with self.assertRaises(people.PeopleError):
            people.transfer_owner(self.d, self.d.get("bea"), "bea")                         # only the Owner
        people.add_person(self.d, self.owner, "cy", "Cy", host_names=["Cy"])
        people.set_active(self.d, self.owner, "cy", False)
        with self.assertRaises(people.PeopleError):
            people.transfer_owner(self.d, self.owner, "cy")                                 # switched off
        people.transfer_owner(self.d, self.owner, "bea")
        self.assertEqual((self.d.get("bea").access, self.d.get("alex").access), (people.OWNER, people.ADMIN))
        self.assertEqual(self.d.owner().id, "bea")

    def test_roles_in_use_cannot_be_removed(self):
        people.add_person(self.d, self.owner, "bea", "Bea", roles=["Quality"])
        with self.assertRaises(people.PeopleError):
            people.set_roles(self.d, self.owner, ["Manufacturing"])
        people.update_person(self.d, self.owner, "bea", roles=[])
        people.set_roles(self.d, self.owner, ["Manufacturing", "Chief"])
        self.assertEqual(self.d.roles, ["Manufacturing", "Chief"])

    def test_scrub_takes_role_off_everyone(self):
        people.add_person(self.d, self.owner, "bea", "Bea", roles=["Quality", "Manufacturing"])
        self.assertEqual(people.holders_of(self.d, "quality"), ["Bea"])
        people.set_roles(self.d, self.owner, ["Manufacturing"], scrub=True)
        self.assertEqual(self.d.get("bea").roles, ["Manufacturing"])
        self.assertEqual(self.d.roles, ["Manufacturing"])

    def test_role_with_comma_rejected(self):
        with self.assertRaises(people.PeopleError):
            people.set_roles(self.d, self.owner, ["Quality", "A,B"])

    def test_what_each_identity_allows(self):
        admin = people.Identity(people.OK, "a", people.Person("a", "A", access=people.ADMIN))
        member = people.Identity(people.OK, "m", people.Person("m", "M"))
        self.assertTrue(admin.allows("manage_people")[0])
        self.assertFalse(member.allows("manage_people")[0])
        self.assertFalse(admin.allows("transfer_owner")[0])
        self.assertTrue(member.allows("checkout")[0])
        for state in (people.NOT_LISTED, people.INACTIVE, people.UNVERIFIED):
            who = people.Identity(state, "x")
            self.assertFalse(who.allows("checkout")[0], state)
            self.assertTrue(who.allows("open")[0], state)
            self.assertTrue(who.message())
        self.assertTrue(people.Identity(people.LEGACY).allows("release")[0])


class TestSetup(TeamFixture, unittest.TestCase):
    def test_a_vault_without_a_team_lets_everyone_do_everything(self):
        self.assertEqual(self.who(self.a, "Alex").state, people.LEGACY)
        self.assertEqual(self.who(self.b, "Bea").state, people.LEGACY)
        with self.user("Bea"):
            eng.checkout(self.b, PART)

    def test_setup_makes_the_runner_the_owner_and_uploads_it(self):
        person = self.setup_team()
        self.assertEqual((person.id, person.name, person.access, person.host_names), ("alex", "Alex Smith", "owner", ["Alex"]))
        self.assertTrue((self.a / people.WHOAMI_FILE).is_file())
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertIn("Team: set up with Alex Smith as Owner", self.remote_log()[0])
        self.assertEqual(self.who(self.a, "Alex").state, people.OK)
        self.assertEqual(self.locks_of(self.a, "Alex"), {})                      # the probe let go of its lock
        with self.assertRaises(people.PeopleError):
            with self.user("Alex"):
                people.setup_team(self.a)

    def test_history_uses_the_team_name_once_there_is_a_team(self):
        self.setup_team()
        with self.user("Alex"):
            self.assertEqual(eng.get_user(self.a), "Alex Smith")
            eng.checkout(self.a, PART)
        self.assertEqual(registry.load(self.a, PART).history[-1]["by"], "Alex Smith")


class TestReadOnlyAndRoles(TeamFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.setup_team()
        with self.user("Bea"):
            eng.get_latest(self.b)

    def test_someone_not_listed_can_look_but_not_change(self):
        who = self.who(self.b, "Bea")
        self.assertEqual((who.state, who.host_name), (people.NOT_LISTED, "Bea"))
        with self.user("Bea"):
            self.assertEqual(len(eng.get_status(self.b)), 1)                      # looking is fine
            with self.assertRaises(LitterboxError) as ctx:
                eng.checkout(self.b, PART)
        self.assertIn("not on this vault's team list", str(ctx.exception))
        self.assertEqual(self.locks_of(self.b, "Bea"), {})

    def test_every_changing_action_is_refused_for_them(self):
        from litterbox.parts import create
        with self.user("Bea"):
            for action in (lambda: eng.checkout(self.b, PART), lambda: eng.undo_checkout(self.b, PART),
                           lambda: eng.edit_details(self.b, PART, "x", ""), lambda: eng.release(self.b, PART),
                           lambda: create.new_part(self.b, "Nope")):
                with self.assertRaises(LitterboxError):
                    action()
        self.assertEqual(len([p for p in registry.list_pns(self.b)]), 1)

    def test_adding_bea_lets_her_work(self):
        self.add_bea()
        self.assertEqual(self.who(self.b, "Bea").state, people.OK)
        with self.user("Bea"):
            eng.checkout(self.b, PART)
            self.assertEqual(eng.get_user(self.b), "Bea Jones")
            eng.undo_checkout(self.b, PART)
        self.assertIn("Team: add Bea", self.remote_log()[0])

    def test_a_member_cannot_manage_people(self):
        self.add_bea()
        with self.user("Bea"):
            with self.assertRaises(LitterboxError) as ctx:
                people.edit_directory(self.b, lambda d, who: people.add_person(d, who, "cy", "Cy"), "x")
        self.assertIn("Only an Admin", str(ctx.exception))

    def test_an_admin_can(self):
        self.add_bea(people.ADMIN)
        with self.user("Bea"):
            people.edit_directory(self.b, lambda d, who: people.add_person(d, who, "cy", "Cy", host_names=["Cy"]),
                                  "Team: add Cy")
        with self.user("Alex"):
            eng.get_latest(self.a)
        self.assertIsNotNone(people.load(self.a).get("cy"))

    def test_switched_off_people_are_read_only(self):
        self.add_bea()
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.set_active(d, who, "bea", False), "Team: off")
        with self.user("Bea"):
            eng.get_latest(self.b)
        self.assertEqual(self.who(self.b, "Bea").state, people.INACTIVE)
        with self.user("Bea"), self.assertRaises(LitterboxError):
            eng.checkout(self.b, PART)

    def test_a_change_that_fails_is_rolled_back(self):
        before = (self.a / people.PEOPLE_FILE).read_text()
        with self.user("Alex"), mock.patch.object(eng, "_push_with_retry", side_effect=LitterboxError("offline")):
            with self.assertRaises(LitterboxError):
                people.edit_directory(self.a, lambda d, who: people.add_person(d, who, "cy", "Cy"), "Team: add Cy")
        self.assertEqual((self.a / people.PEOPLE_FILE).read_text(), before)
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertEqual(self.locks_of(self.a, "Alex"), {})

    def test_a_refused_change_leaves_nothing_behind(self):
        with self.user("Alex"), self.assertRaises(people.PeopleError):
            people.edit_directory(self.a, lambda d, who: people.add_person(d, who, "alex", "Again"), "x")
        self.assertEqual(self.locks_of(self.a, "Alex"), {})
        self.assertEqual(git(self.a, "status", "--porcelain"), "")

    def test_signing_keys_produce_the_allowed_signers_file(self):
        self.add_bea()
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample"
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.update_person(d, who, "bea", signing_keys=[key]),
                                  "Team: add key")
        text = (self.a / people.ALLOWED_SIGNERS_FILE).read_text()
        self.assertEqual(text, f'bea namespaces="git" {key}\n')
        self.assertEqual(git(self.a, "ls-files", people.ALLOWED_SIGNERS_FILE), people.ALLOWED_SIGNERS_FILE)
        with self.user("Alex"):                                    # switching her off drops her key
            people.edit_directory(self.a, lambda d, who: people.set_active(d, who, "bea", False), "Team: off")
        self.assertEqual((self.a / people.ALLOWED_SIGNERS_FILE).read_text(), "")

    def test_transfer_ownership_through_the_vault(self):
        self.add_bea(people.ADMIN)
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.transfer_owner(d, who, "bea"), "Team: new Owner",
                                  action="transfer_owner")
        with self.user("Bea"):
            eng.get_latest(self.b)
        self.assertEqual(self.who(self.b, "Bea").access, people.OWNER)
        self.assertEqual(people.load(self.b).get("alex").access, people.ADMIN)


class TestNoTeamNoCheck(TeamFixture, unittest.TestCase):
    def test_a_vault_without_a_team_is_not_checked_before_pushing(self):
        with mock.patch.object(eng, "run", side_effect=AssertionError("should not run git")):
            self.assertIsNone(people.check_before_push(self.a))


class TestIdentityCache(TeamFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.setup_team()
        self.add_bea()

    def test_the_host_is_asked_once_and_remembered(self):
        people.forget_identity(self.b)
        with self.user("Bea"), mock.patch.object(people, "probe_host_name", wraps=people.probe_host_name) as probe:
            for _ in range(3):
                self.assertEqual(people.current(self.b).state, people.OK)
        self.assertEqual(probe.call_count, 1)

    def test_probe_false_never_uses_the_internet(self):
        people.forget_identity(self.b)
        with self.user("Bea"), mock.patch.object(people, "probe_host_name") as probe:
            self.assertEqual(people.current(self.b, probe=False).state, people.UNVERIFIED)
        probe.assert_not_called()

    def test_an_old_name_is_asked_again_but_kept_if_the_host_cannot_be_reached(self):
        with self.user("Bea"):
            people.current(self.b, refresh=True)
        old = time.time() - people.IDENTITY_MAX_AGE - 10
        people._cache_path(self.b).write_text(f'{{"host_name": "Bea", "checked_at": {old}}}')
        with self.user("Bea"), mock.patch.object(people, "probe_host_name", side_effect=LitterboxError("offline")) as probe:
            self.assertEqual(people.current(self.b).state, people.OK)               # offline: the remembered name is used
        probe.assert_called_once()

    def test_never_verified_and_offline_is_read_only(self):
        people.forget_identity(self.b)
        with self.user("Bea"), mock.patch.object(people, "probe_host_name", side_effect=LitterboxError("offline")):
            who = people.current(self.b)
            self.assertEqual(who.state, people.UNVERIFIED)
            with self.assertRaises(LitterboxError) as ctx:
                eng.checkout(self.b, PART)
        self.assertIn("could not find out", str(ctx.exception))

    def test_refresh_that_fails_does_not_keep_a_stale_name(self):
        with self.user("Bea"):
            people.current(self.b, refresh=True)
        with self.user("Bea"), mock.patch.object(people, "probe_host_name", side_effect=LitterboxError("offline")):
            self.assertEqual(people.current(self.b, refresh=True).state, people.UNVERIFIED)

    def test_changing_account_is_noticed_by_who_am_i(self):
        with self.user("Bea"):
            self.assertEqual(people.current(self.b).state, people.OK)
        with self.user("Zed"):                                       # signed in as someone else now
            self.assertEqual(people.current(self.b, refresh=True).state, people.NOT_LISTED)


class TestCheckBeforePush(TeamFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.setup_team()
        self.add_bea()

    def test_work_done_offline_is_not_uploaded_after_access_is_removed(self):
        with self.user("Bea"):
            eng.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"Bea's offline work")
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.set_active(d, who, "bea", False), "Team: Bea off")
        with self.user("Bea"):
            with self.assertRaises(LitterboxError) as ctx:
                eng.checkin(self.b, PART, "My work")
        self.assertIn("Nothing was uploaded", str(ctx.exception))
        self.assertIn("switched off", str(ctx.exception))
        self.assertEqual(git(self.b, "rev-list", "--count", "@{u}..HEAD"), "1")     # the commit is still there, locally
        self.assertNotIn(f"{PART}: My work", self.remote_log())
        self.assertEqual(sorted(self.locks_of(self.b, "Bea")), sorted([PRT.lower(), DRW.lower(), REC.lower()]))   # she keeps her locks

    def test_allowed_people_push_normally(self):
        with self.user("Bea"):
            eng.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"fine")
            eng.checkin(self.b, PART, "Fine")
        self.assertIn(f"{PART}: Fine", self.remote_log())


if __name__ == "__main__":
    unittest.main()