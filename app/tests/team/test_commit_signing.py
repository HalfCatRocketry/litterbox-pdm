"""
Tests for signing.py and the require_signatures rule. This machine has no OpenSSH, so a real signature can't
be made here: these tests check the Git settings, the parsing, and the pre-push rule (using real unsigned
commits, and a pretend 'good' result). Making a real key and a real signature has to be tried on Windows.

Run from the app folder with:  python -m unittest discover -s tests -t . -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support.team_fixture import TeamFixture
from tests.support.vault_fixture import PART, PRT, SKIP_ON_WINDOWS, git

from litterbox.vault import config
from litterbox.vault import config_write
from litterbox.team import commit_signing as signing
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.team import guarded_push
from tests.support import temp_folders


@SKIP_ON_WINDOWS
class SigningSettings(TeamFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.key = Path(tmp.name) / "key"
        self.key.write_text("PRIVATE")
        self.key.with_name("key.pub").write_text("ssh-ed25519 AAAAexample litterbox\n")

    def test_nothing_is_signed_by_default(self):
        self.assertFalse(signing.status(self.a).enabled)

    def test_enable_sets_this_vaults_git_settings_and_returns_the_public_key(self):
        with self.user("Alex"):
            public = signing.enable(self.a, self.key)
        self.assertEqual(public, "ssh-ed25519 AAAAexample litterbox")
        state = signing.status(self.a)
        self.assertTrue(state.enabled)
        self.assertEqual(state.public_key, "ssh-ed25519 AAAAexample litterbox")
        self.assertEqual(git(self.a, "config", "--local", "gpg.format"), "ssh")
        self.assertEqual(git(self.a, "config", "--local", "commit.gpgsign"), "true")
        self.assertFalse(signing.status(self.b).enabled)                       # other clones are untouched
        signing.disable(self.a)
        self.assertFalse(signing.status(self.a).enabled)

    def test_a_missing_openssh_is_explained(self):
        with mock.patch.object(signing, "ssh_keygen", return_value=None):
            with self.assertRaises(signing.SigningError) as ctx:
                folder = Path(tempfile.mkdtemp())
                self.addCleanup(temp_folders.remove, folder)
                signing.create_key(folder / "k")
        self.assertIn("OpenSSH", str(ctx.exception))

    def test_an_existing_key_is_reused_not_replaced(self):
        with mock.patch.object(signing, "ssh_keygen", return_value=None):          # would fail if it tried to make one
            self.assertEqual(signing.create_key(self.key), "ssh-ed25519 AAAAexample litterbox")


@SKIP_ON_WINDOWS
class RequireSignatures(TeamFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.setup_team()
        self.add_bea()
        config_write.save(self.a, org="HCR")
        data = config.load(self.a)
        data["require_signatures"] = True
        import yaml
        (self.a / ".litterbox" / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "require signatures")
        git(self.a, "push")
        with self.user("Bea"):
            get_latest.get_latest(self.b)

    def work(self):
        with self.user("Bea"):
            checkout.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"signed work?")
            checkin.checkin(self.b, PART, "Bea's work")

    def test_unsigned_commits_are_not_uploaded(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.work()
        text = str(ctx.exception)
        self.assertIn("Nothing was uploaded", text)
        self.assertIn("Bea's work", text)
        self.assertIn("not signed", text)
        self.assertNotIn(f"{PART}: Bea's work", self.remote_log())

    def test_commits_signed_by_a_team_key_go_through(self):
        good = lambda repo, rev_range, path: [signing.CommitSignature("abc", signing.GOOD, "bea", "x")]
        with mock.patch.object(signing, "verify", good):
            self.work()
        self.assertIn(f"{PART}: Bea's work", self.remote_log())

    def test_the_rule_is_off_by_default(self):
        import yaml
        path = self.b / ".litterbox" / "config.yaml"
        data = yaml.safe_load(path.read_text())
        data["require_signatures"] = False
        path.write_text(yaml.safe_dump(data))
        with mock.patch.object(config, "get_require_signatures", return_value=False):
            self.work()
        self.assertIn(f"{PART}: Bea's work", self.remote_log())

    def test_untrusted_unpushed_lists_the_unsigned_commits(self):
        with self.user("Bea"):
            checkout.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"x")
            with mock.patch.object(guarded_push, "push"):                    # commit but do not upload
                checkin.checkin(self.b, PART, "Local only")
        bad = signing.untrusted_unpushed(self.b)
        self.assertEqual([(s.result, s.subject) for s in bad], [(signing.NONE, f"{PART}: Local only")])

    def test_a_bad_value_in_the_setting_is_explained(self):
        import yaml
        path = self.a / ".litterbox" / "config.yaml"
        data = yaml.safe_load(path.read_text())
        data["require_signatures"] = "yes please"
        path.write_text(yaml.safe_dump(data))
        with self.assertRaises(config.ConfigError):
            config.get_require_signatures(self.a)


if __name__ == "__main__":
    unittest.main()
