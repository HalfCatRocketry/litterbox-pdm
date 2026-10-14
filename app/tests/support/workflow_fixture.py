"""A two-user vault with a team and workflows, shared by the workflow and vault settings tests."""

from unittest import mock

from tests.support.vault_fixture import PART, SKIP_ON_WINDOWS, TwoUserVault, git

from litterbox.team import people
from litterbox.records import record_store
from litterbox.workflows import workflow as wf
from litterbox.core.part_number import PN
from litterbox import diagnostics
from litterbox.parts import get_latest
from litterbox.git import read_only


ENGINEER, QUALITY, MANAGER, CHIEF = "Responsible Engineer", "Quality", "Manager", "Chief"
PART2 = PN("HCR", 2, 1)
PRT2 = "cad/HCR-00002-001_A.SLDPRT"


@SKIP_ON_WINDOWS
class Fixture(TwoUserVault):
    def setUp(self):
        super().setUp()
        quiet = mock.patch.object(diagnostics, "LOG", lambda *_: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        with self.user("Alex"):
            people.setup_team(self.a, "Alex Smith", "alex@x.com")
            people.edit_directory(self.a, lambda d, who: (
                people.update_person(d, who, "alex", roles=[ENGINEER]),
                people.add_person(d, who, "bea", "Bea Jones", "bea@x.com", ["Bea"], people.MEMBER, [QUALITY]),
                people.add_person(d, who, "cy", "Cy Day", "cy@x.com", ["Cy"], people.MEMBER, [MANAGER])),
                "Team: add Bea and Cy")
        self.get_latest("Bea")

    def get_latest(self, user):
        with self.user(user):
            get_latest.get_latest(self.repo_of(user))

    def repo_of(self, user):
        if user == "Cy":                       # Cy has a copy of his own, so Litterbox knows who is acting
            if not hasattr(self, "c"):
                git(self.root, "clone", str(self.remote), "c")
                self.c = self.root / "c"
                self.config(self.c, "Cy")
                with self.user("Cy"):
                    read_only.enforce_read_only(self.c)
            return self.c
        return self.a if user == "Alex" else self.b

    def second_part(self):
        (self.a / PRT2).write_bytes(b"part two")
        record_store.create_record(self.a, PART2, "Second", "Alex")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "Second part")
        git(self.a, "push")
        with self.user("Alex"):
            read_only.enforce_read_only(self.a)
        self.get_latest("Bea")

    def set_template(self, action=wf.RELEASE, name="T", rows=((QUALITY,), (ENGINEER,)), same=False, requester=True):
        with self.user("Alex"):
            wf.edit_templates(self.a, lambda t, d: wf.set_template(t, action, name, [list(r) for r in rows], same,
                                                                   requester), "Workflow")
        self.get_latest("Bea")

    def do(self, user, func, *args, **kwargs):
        with self.user(user):
            return func(self.repo_of(user), *args, **kwargs)

    def record(self, pn=PART):
        self.get_latest("Alex")                # the newest copy, whoever made the last change
        return record_store.load(self.a, pn)

    def request(self, action=wf.RELEASE, pns=(PART,), name="T", assign=("bea", "alex"), **kwargs):
        if not wf.templates_for(self.a, action):
            self.set_template(action)
        batch = self.do("Alex", wf.request, list(pns), action, name, list(assign), **kwargs)
        self.get_latest("Bea")
        return batch
