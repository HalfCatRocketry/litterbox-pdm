import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from litterbox.user import updater  # noqa: E402
from litterbox import version  # noqa: E402

REPO = "someone/litterbox-pdm"
PRIVATE, PUBLIC = updater.generate_keypair()
INSTALLER = b"pretend installer bytes" * 100


def manifest(**changes):
    data = {"schema": 1, "version": "0.2.0", "notes": "Fixes things.",
            "installer": {"name": "Litterbox-Setup-0.2.0.exe",
                          "url": f"https://github.com/{REPO}/releases/download/v0.2.0/Litterbox-Setup-0.2.0.exe",
                          "sha256": hashlib.sha256(INSTALLER).hexdigest(), "size": len(INSTALLER)}}
    for key, value in changes.items():
        if key in data["installer"]:
            data["installer"][key] = value
        else:
            data[key] = value
    return json.dumps(data).encode()


def fetcher(raw, key=PRIVATE):
    files = {updater.release_url(REPO, updater.MANIFEST_NAME): raw,
             updater.release_url(REPO, updater.SIGNATURE_NAME): updater.sign(raw, key).encode()}
    return lambda url: files[url]


class Signing(unittest.TestCase):
    def test_round_trip_and_tampering(self):
        sig = updater.sign(b"hello", PRIVATE)
        self.assertTrue(updater.signature_is_good(b"hello", sig, PUBLIC))
        self.assertFalse(updater.signature_is_good(b"hellp", sig, PUBLIC))
        other_private, other_public = updater.generate_keypair()
        self.assertFalse(updater.signature_is_good(b"hello", sig, other_public))
        self.assertFalse(updater.signature_is_good(b"hello", "not base64 !!", PUBLIC))
        self.assertEqual(updater.public_from_private(PRIVATE), PUBLIC)


class FindingUpdates(unittest.TestCase):
    def find(self, raw, current="0.1.0", key=PRIVATE):
        return updater.find_update(REPO, PUBLIC, current, fetch=fetcher(raw, key))

    def test_a_newer_signed_release_is_found(self):
        found = self.find(manifest())
        self.assertEqual((found.version, found.name, found.notes), ("0.2.0", "Litterbox-Setup-0.2.0.exe", "Fixes things."))

    def test_same_or_older_means_no_update(self):
        self.assertIsNone(self.find(manifest(), current="0.2.0"))
        self.assertIsNone(self.find(manifest(), current="0.10.0"))

    def test_a_wrong_signature_is_ignored(self):
        other_private, _ = updater.generate_keypair()
        with self.assertRaisesRegex(updater.UpdateError, "not signed"):
            self.find(manifest(), key=other_private)

    def test_changed_content_after_signing_is_ignored(self):
        raw = manifest()
        files = {updater.release_url(REPO, updater.MANIFEST_NAME): raw.replace(b"0.2.0", b"9.9.9"),
                 updater.release_url(REPO, updater.SIGNATURE_NAME): updater.sign(raw, PRIVATE).encode()}
        with self.assertRaises(updater.UpdateError):
            updater.find_update(REPO, PUBLIC, "0.1.0", fetch=lambda url: files[url])

    def test_installer_must_come_from_this_projects_releases(self):
        with self.assertRaisesRegex(updater.UpdateError, "somewhere other"):
            self.find(manifest(url="https://evil.example/Litterbox-Setup-0.2.0.exe"))
        with self.assertRaisesRegex(updater.UpdateError, "somewhere other"):
            self.find(manifest(url="https://github.com/other/repo/releases/download/v1/Litterbox-Setup-0.2.0.exe"))

    def test_odd_file_names_and_fingerprints_are_refused(self):
        for bad in ({"name": "..\\evil.exe"}, {"name": "setup.bat"}, {"sha256": "abc"}, {"size": 0}):
            with self.assertRaises(updater.UpdateError, msg=str(bad)):
                self.find(manifest(**bad))

    def test_garbage_and_newer_formats_give_plain_errors(self):
        with self.assertRaisesRegex(updater.UpdateError, "could not be understood"):
            self.find(b"not json")
        with self.assertRaisesRegex(updater.UpdateError, "newer format"):
            self.find(manifest(schema=2))
        with self.assertRaises(updater.UpdateError):
            self.find(manifest(version="soon"))

    def test_offline_is_an_update_error_not_a_crash(self):
        def offline(url):
            raise updater.UpdateError("Could not reach GitHub")
        with self.assertRaises(updater.UpdateError):
            updater.find_update(REPO, PUBLIC, "0.1.0", fetch=offline)

    def test_not_configured_in_a_development_copy(self):
        self.assertFalse(updater.configured("", ""))
        self.assertFalse(updater.configured("no-slash", PUBLIC))
        self.assertTrue(updater.configured(REPO, PUBLIC))
        with self.assertRaisesRegex(updater.UpdateError, "not set up"):
            updater.find_update("", "", "0.1.0", fetch=lambda url: b"")


class ReadingErrors(unittest.TestCase):
    def test_a_http_error_says_which_one_and_for_what(self):
        import urllib.error
        original = updater.urllib.request.urlopen
        updater.urllib.request.urlopen = lambda request, timeout=0: (_ for _ in ()).throw(
            urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None))
        try:
            with self.assertRaises(updater.UpdateError) as caught:
                updater.http_get("https://github.com/x/y/releases/latest/download/latest.json")
        finally:
            updater.urllib.request.urlopen = original
        self.assertIn("404", str(caught.exception))
        self.assertIn("latest.json", str(caught.exception))
        self.assertIn("public", str(caught.exception))


class Downloading(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.update = updater.parse_manifest(manifest(), updater.sign(manifest(), PRIVATE), PUBLIC, REPO)

    @staticmethod
    def stream_of(data):
        def stream(url, path, progress=None):
            Path(path).write_bytes(data)
            return len(data), hashlib.sha256(data).hexdigest()
        return stream

    def test_a_matching_download_is_kept(self):
        path = updater.download(self.update, self.dir, stream=self.stream_of(INSTALLER))
        self.assertEqual(path.read_bytes(), INSTALLER)

    def test_a_download_that_does_not_match_is_deleted(self):
        with self.assertRaisesRegex(updater.UpdateError, "fingerprint"):
            updater.download(self.update, self.dir, stream=self.stream_of(INSTALLER + b"!"))
        self.assertEqual(list(self.dir.glob("*.exe")), [])
        with self.assertRaises(updater.UpdateError):
            updater.download(self.update, self.dir, stream=self.stream_of(b"x" * len(INSTALLER)))
        self.assertEqual(list(self.dir.glob("*.exe")), [])

    def test_old_downloads_are_cleared(self):
        (self.dir / "Litterbox-Setup-0.0.1.exe").write_bytes(b"old")
        updater.download(self.update, self.dir, stream=self.stream_of(INSTALLER))
        self.assertEqual([p.name for p in self.dir.glob("*.exe")], ["Litterbox-Setup-0.2.0.exe"])


class Launching(unittest.TestCase):
    def test_the_installer_runs_quietly_and_on_its_own(self):
        seen = {}
        updater.launch_installer(Path("C:/x/Setup.exe"), popen=lambda cmd, **kw: seen.update(cmd=cmd, kw=kw))
        self.assertIn("/SILENT", seen["cmd"])
        self.assertIn("/CLOSEAPPLICATIONS", seen["cmd"])
        self.assertTrue(seen["kw"]["creationflags"] & 0x8)          # detached: survives Litterbox closing

    def test_a_failure_to_start_is_reported(self):
        def broken(cmd, **kw):
            raise OSError("blocked")
        with self.assertRaisesRegex(updater.UpdateError, "could not be started"):
            updater.launch_installer(Path("Setup.exe"), popen=broken)


if __name__ == "__main__":
    unittest.main()