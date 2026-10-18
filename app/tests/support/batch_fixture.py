"""Five parts in the two-user vault, and the helpers the tests of actions on many parts share. No tests here."""

from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault, git
from litterbox.records import record_store
from litterbox.core.part_number import PN
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.git import read_only
from litterbox.git import runner


COUNT = 5


def cad(pn, ext="SLDPRT", rev="A"):
    return f"cad/{pn}_{rev}.{ext}"


@SKIP_ON_WINDOWS
class BatchFixture(TwoUserVault):
    def setUp(self):
        super().setUp()
        self.pns = [PN("HCR", n, 1) for n in range(2, 2 + COUNT)]          # five more parts, each with two files
        for pn in self.pns:
            record_store.create_record(self.a, pn, f"Part {pn.base}", "Alex")
            (self.a / cad(pn)).write_bytes(b"v1 " + str(pn).encode())
            (self.a / cad(pn, "SLDDRW")).write_bytes(b"d1 " + str(pn).encode())
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "Add parts")
        git(self.a, "push")
        with self.user("Alex"):
            read_only.enforce_read_only(self.a)
        with self.user("Bea"):
            get_latest.get_latest(self.b)

    def commands(self, func, *args, **kwargs):
        """Run func, returning (result, [every command it ran])."""
        seen, real = [], runner.run

        def recording(command, repo, quiet=False):
            seen.append(" ".join(command))
            return real(command, repo, quiet)

        with mock.patch.object(runner, "run", recording):
            result = func(*args, **kwargs)
        return result, seen

    @staticmethod
    def count(commands, prefix):
        return sum(1 for c in commands if c.startswith(prefix))

    def subjects(self, repo=None):
        return git(repo or self.a, "log", "--format=%s", "-20").splitlines()

    def change(self, pns, text=b"changed"):
        for pn in pns:
            (self.a / cad(pn)).write_bytes(text + str(pn).encode())

    def use_style(self, style):
        from litterbox.vault import settings_admin as vault_settings
        with self.user("Alex"):
            vault_settings.edit(self.a, commit_style=style)

    def snapshot(self, pns):
        return checkin.watch_files(self.a, {pn: "A" for pn in pns})

    def saving_during_add(self, victim):
        """runner.run that rewrites the victim's file while 'git add' is reading it."""
        real = runner.run

        def run(command, repo, quiet=False):
            if command[:2] == ["git", "add"] and cad(victim) in command:
                (self.a / cad(victim)).write_bytes(b"saved in the middle of the upload!")
            return real(command, repo, quiet)
        return run

    def check_save_during_add(self):
        victim = self.pns[1]
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:3])
            self.change(self.pns[:3])
            record_before = (self.a / record_store.record_relpath(victim)).read_bytes()
            with mock.patch.object(runner, "run", self.saving_during_add(victim)):
                done, failed = checkin.checkin_many(self.a, self.pns[:3], "Tweaks")
            self.assertEqual([pn for pn, _r in done], [self.pns[0], self.pns[2]])
            self.assertEqual([pn for pn, _why in failed], [victim])
            self.assertIn("was saved while Litterbox was reading it", failed[0][1])
            self.assertEqual((self.a / record_store.record_relpath(victim)).read_bytes(), record_before)
            self.assertEqual(git(self.a, "diff", "--cached", "--name-only"), "")        # nothing left staged
            self.assertIn(cad(victim).lower(), self.locks(self.a))                       # still checked out
        log = self.remote_log()
        self.assertIn(f"{self.pns[0]}: Tweaks", " ".join(log) + " ".join(
            git(self.a, "log", "-3", "--format=%B").splitlines()))
        self.assertFalse(any(f"{victim}: Tweaks" in line for line in git(self.a, "log", "-5", "--format=%B").splitlines()))
