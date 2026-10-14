"""A two-user vault with a team file, shared by the people and commit-signing tests."""

from unittest import mock

from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault

from litterbox.parts import engine as eng
from litterbox.team import people
from litterbox import diagnostics


@SKIP_ON_WINDOWS
class TeamFixture(TwoUserVault):
    def setUp(self):
        super().setUp()
        self.quiet = mock.patch.object(diagnostics, "LOG", lambda *_: None)
        self.quiet.start()
        self.addCleanup(self.quiet.stop)

    def setup_team(self):
        with self.user("Alex"):
            return people.setup_team(self.a, "Alex Smith", "alex@x.com")

    def add_bea(self, access=people.MEMBER):
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.add_person(
                d, who, "bea", "Bea Jones", "bea@x.com", ["Bea"], access), "Team: add Bea")
        with self.user("Bea"):
            eng.get_latest(self.b)

    def locks_of(self, repo, user):
        with self.user(user):
            return eng.get_locks(repo, strict=True)

    def who(self, repo, user, **kwargs):
        with self.user(user):
            return people.current(repo, **kwargs)
