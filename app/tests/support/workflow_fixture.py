"""A two-user vault with a team and workflows, shared by the workflow and vault settings tests."""

from unittest import mock

from tests.support.vault_fixture import PART, SKIP_ON_WINDOWS, TwoUserVault, git

from litterbox.team import team_editing
from litterbox.team import team_model
from litterbox.team import team_setup
from litterbox.team import team_store
from litterbox.records import record_store
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_templates
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
            team_setup.setup_team(self.a, "Alex Smith", "alex@x.com")
            team_store.edit_directory(self.a, lambda d, who: (
                team_editing.update_person(d, who, "alex", roles=[ENGINEER]),
                team_editing.add_person(d, who, "bea", "Bea Jones", "bea@x.com", ["Bea"], team_model.MEMBER, [QUALITY]),
                team_editing.add_person(d, who, "cy", "Cy Day", "cy@x.com", ["Cy"], team_model.MEMBER, [MANAGER])),
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

    def make_rev_b(self, pn=PART):
        """The part released at Rev A and now in work at Rev B, with Rev B's files: made by hand, as Revise would
        leave it once checked in."""
        with self.user("Alex"):
            stem = f"cad/{pn}"
            for ext in ("SLDPRT", "SLDDRW"):
                old = self.a / f"{stem}_A.{ext}"
                if old.exists():
                    (self.a / f"{stem}_B.{ext}").write_bytes(old.read_bytes())
            path = record_store.record_path(self.a, pn)
            path.chmod(0o644)
            record = record_store.load(self.a, pn)
            record.history.append({"event": "released", "by": "Alex Smith", "at": "2026-10-01T00:00:00Z",
                                   "revision": "A"})
            record.revision, record.released_revision = "B", "A"
            record_store.save(self.a, record)
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", f"{pn} at Rev B")
            git(self.a, "push")
            read_only.enforce_read_only(self.a)
        self.get_latest("Bea")

    def set_template(self, action=workflow_templates.RELEASE, name="T", rows=((QUALITY,), (ENGINEER,)), same=False, requester=True,
                     eco=False):
        with self.user("Alex"):
            workflow_store.edit_templates(self.a, lambda t, d: workflow_editing.set_template(t, action, name, [list(r) for r in rows], same,
                                                                   requester, require_eco=eco), "Workflow")
        self.get_latest("Bea")

    def do(self, user, func, *args, **kwargs):
        with self.user(user):
            return func(self.repo_of(user), *args, **kwargs)

    def record(self, pn=PART):
        self.get_latest("Alex")                # the newest copy, whoever made the last change
        return record_store.load(self.a, pn)

    def request(self, action=workflow_templates.RELEASE, pns=(PART,), name="T", assign=("bea", "alex"), **kwargs):
        if not workflow_store.templates_for(self.a, action):
            self.set_template(action)
        batch = self.do("Alex", workflow_request.request, list(pns), action, name, list(assign), **kwargs)
        self.get_latest("Bea")
        return batch
