"""A two-user vault with a team file, shared by the people and commit-signing tests."""

from unittest import mock

from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault

from litterbox.team import team_editing
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.team import team_setup
from litterbox.team import team_store
from litterbox import diagnostics
from litterbox.parts import get_latest
from litterbox.git import lfs_locks


@SKIP_ON_WINDOWS
class TeamFixture(TwoUserVault):
    def setUp(self):
        super().setUp()
        self.quiet = mock.patch.object(diagnostics, "LOG", lambda *_: None)
        self.quiet.start()
        self.addCleanup(self.quiet.stop)

    def setup_team(self):
        with self.user("Alex"):
            return team_setup.setup_team(self.a, "Alex Smith", "alex@x.com")

    def add_bea(self, access=team_model.MEMBER):
        with self.user("Alex"):
            team_store.edit_directory(self.a, lambda d, who: team_editing.add_person(
                d, who, "bea", "Bea Jones", "bea@x.com", ["Bea"], access), "Team: add Bea")
        with self.user("Bea"):
            get_latest.get_latest(self.b)

    def locks_of(self, repo, user):
        with self.user(user):
            return lfs_locks.get_locks(repo, strict=True)

    def who(self, repo, user, **kwargs):
        with self.user(user):
            return team_identity.current(repo, **kwargs)
