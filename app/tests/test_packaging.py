"""Tests for the release scripts in packaging/ (they sit at <repo>/packaging, next to the app folder)."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
PACKAGING = next((p for p in (APP.parent / "packaging", APP / "litterbox-pdm" / "packaging") if p.is_dir()), None)

from litterbox.user import updater
from litterbox import version
from tests.support import temp_folders


@unittest.skipIf(PACKAGING is None, "packaging folder not found next to the app")
class ReleaseScripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PACKAGING))
        import check_version
        import make_manifest
        import third_party_licenses
        import write_build_info
        cls.check_version, cls.make_manifest, cls.write_build_info = check_version, make_manifest, write_build_info
        cls.licences = third_party_licenses

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.dir)
        self.private, self.public = updater.generate_keypair()

    def test_notes_come_from_the_changelog_section_of_that_version(self):
        text = "# Changelog\n\nintro\n\n## 0.2.0\n\nNew thing.\n\n## [0.1.0] - 2026-10-10\n\n- First.\n- Second.\n"
        self.assertEqual(self.make_manifest.notes_for(text, "0.1.0"), "- First.\n- Second.")
        self.assertEqual(self.make_manifest.notes_for(text, "0.2.0"), "New thing.")
        self.assertEqual(self.make_manifest.notes_for(text, "0.3.0"), "")
        self.assertEqual(self.make_manifest.notes_for("## 0.10.0\nx\n", "0.1.0"), "")        # not a prefix match

    def test_the_manifest_is_signed_and_the_program_accepts_it(self):
        installer = self.dir / "Litterbox-Setup-0.1.0.exe"
        installer.write_bytes(b"installer" * 50)
        manifest = self.make_manifest.build("0.1.0", "me/litterbox-pdm", installer, self.dir / "out", self.private,
                                            "## 0.1.0\nHello.\n")
        raw = (self.dir / "out" / "latest.json").read_bytes()
        signature = (self.dir / "out" / "latest.json.sig").read_text()
        found = updater.parse_manifest(raw, signature, self.public, "me/litterbox-pdm")
        self.assertEqual((found.version, found.notes, found.size), ("0.1.0", "Hello.", len(b"installer" * 50)))
        self.assertEqual(found.sha256, hashlib.sha256(b"installer" * 50).hexdigest())
        self.assertEqual(json.loads(raw)["installer"]["url"],
                         "https://github.com/me/litterbox-pdm/releases/download/v0.1.0/Litterbox-Setup-0.1.0.exe")
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual((self.dir / "out" / "notes.md").read_text(), "Hello.")

    def test_the_tag_must_match_version_py(self):
        self.assertEqual(self.check_version.main(["x", f"v{version.VERSION}"]), 0)
        self.assertEqual(self.check_version.main(["x", f"refs/tags/v{version.VERSION}"]), 0)
        self.assertEqual(self.check_version.main(["x", "v9.9.9"]), 1)
        self.assertEqual(self.check_version.main(["x", version.VERSION]), 1)         # missing the v

    def test_the_runtime_packages_come_from_requirements(self):
        text = ("# x\npyinstaller>=6.0\n# --- To run ---\ncustomtkinter>=6.0.0   # the toolkit\nPyYAML>=6.0\n"
                "pywin32>=306; sys_platform == \"never\"\n\n# --- To build ---\npyinstaller>=6.0\n")
        self.assertEqual(self.licences.runtime_requirements(text), ["customtkinter", "PyYAML"])
        with self.assertRaises(SystemExit):
            self.licences.runtime_requirements("PyYAML\n")

    def test_every_bundled_package_gets_its_licence(self):
        out = self.dir / "licenses"
        rows = self.licences.write(out, PACKAGING.parent, build_tools={})      # PyInstaller isn't needed to run tests
        folders = [folder for _what, _licence, folder in rows]
        self.assertEqual(folders[0], "Litterbox")
        self.assertTrue(folders[1].startswith("Python-"))
        for name in ("customtkinter", "PyYAML", "cryptography", "darkdetect"):
            self.assertTrue(any(f.startswith(name + "-") for f in folders), name)
        self.assertIn("Roboto-font", folders)
        for folder in folders:
            self.assertTrue(any((out / folder).rglob("*")), folder)
        readme = (out / "README.txt").read_text(encoding="utf-8")
        self.assertIn("MIT licence", readme)
        self.assertIn("customtkinter", readme)

    def test_build_info_is_written_from_the_public_key_alone(self):
        out = self.dir / "build_info.py"
        os.environ.pop("LITTERBOX_SIGNING_KEY", None)                     # the build never has the private key
        write = lambda repo, key: self.write_build_info.main(["--repo", repo, "--public-key", key, "--out", str(out)])
        self.assertEqual(write("me/litterbox-pdm", self.public), 0)
        namespace = {}
        exec(out.read_text(), namespace)
        self.assertEqual((namespace["REPO"], namespace["PUBLIC_KEY"]), ("me/litterbox-pdm", self.public))
        self.assertTrue(updater.configured(namespace["REPO"], namespace["PUBLIC_KEY"]))
        self.assertEqual(write("not a repo", self.public), 1)
        self.assertEqual(write("me/litterbox-pdm", "garbage"), 1)
        self.assertEqual(write("me/litterbox-pdm", ""), 1)

    def test_signing_refuses_a_private_key_that_isnt_the_built_ins(self):
        installer = self.dir / "Litterbox-Setup-0.1.0.exe"
        installer.write_bytes(b"x")
        _other_private, other_public = updater.generate_keypair()
        args = ["--version", version.VERSION, "--repo", "me/litterbox-pdm", "--installer", str(installer),
                "--out", str(self.dir / "out"), "--public-key"]
        os.environ["LITTERBOX_SIGNING_KEY"] = self.private
        try:
            self.assertEqual(self.make_manifest.main(args + [other_public]), 1)
            self.assertFalse((self.dir / "out").exists())
            self.assertEqual(self.make_manifest.main(args + [self.public]), 0)
        finally:
            os.environ.pop("LITTERBOX_SIGNING_KEY", None)

    def test_notices_go_with_the_release_when_there_are_any(self):
        installer = self.dir / "Litterbox-Setup-0.1.0.exe"
        installer.write_bytes(b"x")
        self.make_manifest.build("0.1.0", "me/r", installer, self.dir / "plain", self.private, notices_dir=self.dir)
        self.assertFalse((self.dir / "plain" / "notices.json").exists())
        (self.dir / "notices.json").write_text("{}")
        (self.dir / "notices.json.sig").write_text("sig")
        self.make_manifest.build("0.1.0", "me/r", installer, self.dir / "out", self.private, notices_dir=self.dir)
        self.assertEqual((self.dir / "out" / "notices.json.sig").read_text(), "sig")

    def test_a_betas_notes_are_its_own_section(self):
        text = "## 0.7.0\n\nFinal.\n\n## 0.7.0-beta.1\n\nFirst beta.\n"
        self.assertEqual(self.make_manifest.notes_for(text, "0.7.0-beta.1"), "First beta.")
        self.assertEqual(self.make_manifest.notes_for(text[text.index("## 0.7.0-"):], "0.7.0"), "")

    def test_a_spare_signs_notices_and_a_release_key_cannot(self):
        import sign_notice
        spare_private, spare_public = updater.generate_keypair()
        _, leaked = updater.generate_keypair()
        original = updater.SPARE_PUBLIC_KEYS
        updater.SPARE_PUBLIC_KEYS = (spare_public,)
        try:
            with self.assertRaisesRegex(SystemExit, "SPARE_PUBLIC_KEYS"):
                sign_notice.write(self.private, [leaked], folder=self.dir)
            with self.assertRaisesRegex(SystemExit, "itself"):
                sign_notice.write(spare_private, [spare_public], folder=self.dir)
            found = sign_notice.write(spare_private, [leaked], folder=self.dir)
            self.assertEqual(found.revoked, (leaked,))
            found = sign_notice.write(spare_private, moved_to="new/place", folder=self.dir)    # keeps the revoked
            self.assertEqual((found.revoked, found.moved_to), ((leaked,), "new/place"))
            self.assertEqual(sign_notice.current(self.dir), found)
        finally:
            updater.SPARE_PUBLIC_KEYS = original


if __name__ == "__main__":
    unittest.main()
