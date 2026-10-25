"""Signed notices (keys withdrawn, releases moved) and the beta channel in the update check (user/updater.py,
user/update_notices.py), and what the settings keep from them."""

import hashlib
import json
import unittest

from litterbox.user import settings
from litterbox.user import update_notices
from litterbox.user import updater
from tests.user.test_updater import INSTALLER, serve

REPO, NEW_REPO = "someone/litterbox-pdm", "elsewhere/litterbox"
RELEASE_PRIVATE, RELEASE_PUBLIC = updater.generate_keypair()
SPARE_PRIVATE, SPARE_PUBLIC = updater.generate_keypair()


def manifest(version, repo=REPO):
    name = f"Litterbox-Setup-{version}.exe"
    return json.dumps({"schema": 1, "version": version, "notes": "",
                       "installer": {"name": name, "url": f"https://github.com/{repo}/releases/download/v{version}/{name}",
                                     "sha256": hashlib.sha256(INSTALLER).hexdigest(), "size": len(INSTALLER)}}).encode()


class Server:
    """Releases on pretend GitHub: the latest release's and the beta channel's files, per repository."""

    def __init__(self):
        self.files = {}

    def release(self, version, repo=REPO, key=RELEASE_PRIVATE, beta=False):
        url = updater.beta_url if beta else updater.release_url
        raw = manifest(version, repo)
        self.files[url(repo, updater.MANIFEST_NAME)] = raw
        self.files[url(repo, updater.SIGNATURE_NAME)] = updater.sign(raw, key).encode()

    def notices(self, repo=REPO, key=SPARE_PRIVATE, **fields):
        raw = update_notices.build(**fields)
        self.files[updater.release_url(repo, update_notices.NOTICES_NAME)] = raw
        self.files[updater.release_url(repo, update_notices.NOTICES_SIGNATURE_NAME)] = updater.sign(raw, key).encode()

    def check(self, current="0.6.5", channel=updater.STABLE, revoked=()):
        return updater.check(REPO, RELEASE_PUBLIC, current, channel, revoked, fetch=serve(self.files))


class WithASpare(unittest.TestCase):
    def setUp(self):
        saved = updater.SPARE_PUBLIC_KEYS, updater.REVOKED_PUBLIC_KEYS
        updater.SPARE_PUBLIC_KEYS, updater.REVOKED_PUBLIC_KEYS = (SPARE_PUBLIC,), ()
        self.addCleanup(lambda: (setattr(updater, "SPARE_PUBLIC_KEYS", saved[0]),
                                 setattr(updater, "REVOKED_PUBLIC_KEYS", saved[1])))
        self.server = Server()


class RevokedKeys(WithASpare):
    def test_no_notices_change_nothing(self):
        self.server.release("0.7.0")
        found = self.server.check()
        self.assertEqual((found.update.version, found.revoked, found.moved_to, found.problem), ("0.7.0", (), "", ""))

    def test_a_spare_signed_notice_withdraws_the_release_key(self):
        self.server.release("0.7.0")                                        # signed with the leaked release key
        self.server.notices(revoked=[RELEASE_PUBLIC])
        found = self.server.check()
        self.assertEqual(found.revoked, (RELEASE_PUBLIC,))
        self.assertIsNone(found.update)
        self.assertIn("not signed", found.problem)

    def test_after_withdrawing_it_a_release_signed_by_the_spare_is_still_offered(self):
        self.server.release("0.7.0", key=SPARE_PRIVATE)
        self.server.notices(revoked=[RELEASE_PUBLIC])
        self.assertEqual(self.server.check().update.version, "0.7.0")

    def test_the_release_key_cannot_sign_notices(self):
        self.server.release("0.7.0")
        self.server.notices(key=RELEASE_PRIVATE, revoked=[SPARE_PUBLIC], moved_to=NEW_REPO)
        found = self.server.check()
        self.assertEqual((found.revoked, found.moved_to, found.update.version), ((), "", "0.7.0"))

    def test_a_key_revoked_on_this_computer_stays_revoked_without_the_notice(self):
        self.server.release("0.7.0")
        found = self.server.check(revoked=(RELEASE_PUBLIC,))
        self.assertIsNone(found.update)
        self.assertEqual(found.revoked, ())                              # nothing new to keep

    def test_a_built_in_revoked_key_is_never_trusted(self):
        updater.REVOKED_PUBLIC_KEYS = (RELEASE_PUBLIC,)
        self.assertEqual(updater.trusted_keys(RELEASE_PUBLIC), (SPARE_PUBLIC,))
        self.server.release("0.7.0")
        self.assertIn("not signed", self.server.check().problem)

    def test_a_revoked_spare_cannot_sign_notices(self):
        self.server.release("0.7.0")
        self.server.notices(moved_to=NEW_REPO)
        found = self.server.check(revoked=(SPARE_PUBLIC,))
        self.assertEqual(found.moved_to, "")

    def test_with_every_key_withdrawn_it_says_to_download_by_hand(self):
        self.server.notices(revoked=[RELEASE_PUBLIC, SPARE_PUBLIC])
        found = self.server.check()
        self.assertIn("withdrawn", found.problem)
        self.assertEqual(set(found.revoked), {RELEASE_PUBLIC, SPARE_PUBLIC})

    def test_garbled_or_newer_notices_are_ignored(self):
        self.server.release("0.7.0")
        raw = b'{"schema": 2, "revoked": []}'
        self.server.files[updater.release_url(REPO, update_notices.NOTICES_NAME)] = raw
        self.server.files[updater.release_url(REPO, update_notices.NOTICES_SIGNATURE_NAME)] = \
            updater.sign(raw, SPARE_PRIVATE).encode()
        self.assertEqual(self.server.check().update.version, "0.7.0")
        with self.assertRaises(update_notices.NoticeError):
            update_notices.build(moved_to="not a repo")


class MovedTo(WithASpare):
    def test_a_signed_move_is_followed_and_reported(self):
        self.server.notices(moved_to=NEW_REPO)
        self.server.release("0.7.0", repo=NEW_REPO)
        found = self.server.check()
        self.assertEqual((found.moved_to, found.update.version), (NEW_REPO, "0.7.0"))
        self.assertTrue(found.update.url.startswith(f"https://github.com/{NEW_REPO}/"))

    def test_only_one_move_is_followed_in_a_check(self):
        self.server.notices(moved_to=NEW_REPO)
        self.server.notices(repo=NEW_REPO, moved_to="third/place")
        self.server.release("0.7.0", repo=NEW_REPO)
        self.assertEqual(self.server.check().moved_to, NEW_REPO)

    def test_the_new_places_revocations_count_too(self):
        self.server.notices(moved_to=NEW_REPO)
        self.server.notices(repo=NEW_REPO, revoked=[RELEASE_PUBLIC])
        self.server.release("0.7.0", repo=NEW_REPO)
        found = self.server.check()
        self.assertEqual((found.moved_to, found.revoked, found.update), (NEW_REPO, (RELEASE_PUBLIC,), None))

    def test_a_move_to_where_it_already_looks_is_nothing(self):
        self.server.notices(moved_to=REPO.upper())
        self.server.release("0.7.0")
        self.assertEqual(self.server.check().moved_to, "")


class BetaChannel(WithASpare):
    def test_the_stable_channel_never_offers_a_beta(self):
        self.server.release("0.6.5")
        self.server.release("0.7.0-beta.1", beta=True)
        self.assertIsNone(self.server.check().update)
        self.server.release("0.7.0-beta.1")                              # even one published as the latest by mistake
        self.assertIsNone(self.server.check().update)

    def test_the_beta_channel_offers_the_newer_of_the_two(self):
        self.server.release("0.6.5")
        self.server.release("0.7.0-beta.2", beta=True)
        self.assertEqual(self.server.check(channel=updater.BETA).update.version, "0.7.0-beta.2")
        self.server.release("0.7.0")                                     # the final is out: offered over the beta
        self.assertEqual(self.server.check("0.7.0-beta.2", updater.BETA).update.version, "0.7.0")

    def test_a_beta_copy_with_no_beta_channel_yet_still_gets_releases(self):
        self.server.release("0.7.0")
        self.assertEqual(self.server.check(channel=updater.BETA).update.version, "0.7.0")

    def test_nothing_newer_on_either_is_no_update(self):
        self.server.release("0.6.5")
        self.server.release("0.7.0-beta.1", beta=True)
        self.assertIsNone(self.server.check("0.7.0-beta.1", updater.BETA).update)


class Settings(unittest.TestCase):
    def test_the_channel_defaults_to_releases(self):
        self.assertEqual(settings.update_channel({}), "stable")
        self.assertEqual(settings.update_channel({"update_channel": " Beta "}), "beta")
        self.assertEqual(settings.update_channel({"update_channel": True}), "stable")

    def test_what_a_check_learned_is_kept_once(self):
        data = {}
        self.assertTrue(settings.remember_update_notices(data, ("k1",), NEW_REPO))
        self.assertEqual((data["revoked_update_keys"], settings.update_repo(data)), (["k1"], NEW_REPO))
        self.assertFalse(settings.remember_update_notices(data, ("k1",), NEW_REPO))
        self.assertTrue(settings.remember_update_notices(data, ("k2",)))
        self.assertEqual(settings.revoked_update_keys(data), ("k1", "k2"))

    def test_odd_values_are_ignored(self):
        self.assertIsNone(settings.update_repo({"update_repo": "not a repo"}))
        self.assertEqual(settings.revoked_update_keys({"revoked_update_keys": "k1"}), ())


if __name__ == "__main__":
    unittest.main()
