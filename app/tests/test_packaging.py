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

import updater  # noqa: E402
import version  # noqa: E402


@unittest.skipIf(PACKAGING is None, "packaging folder not found next to the app")
class ReleaseScripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PACKAGING))
        import check_version
        import make_manifest
        import write_build_info
        cls.check_version, cls.make_manifest, cls.write_build_info = check_version, make_manifest, write_build_info

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
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

    def test_build_info_is_written_from_the_private_key(self):
        out = self.dir / "build_info.py"
        os.environ["LITTERBOX_SIGNING_KEY"] = self.private
        try:
            self.assertEqual(self.write_build_info.main(["--repo", "me/litterbox-pdm", "--out", str(out)]), 0)
            namespace = {}
            exec(out.read_text(), namespace)
            self.assertEqual((namespace["REPO"], namespace["PUBLIC_KEY"]), ("me/litterbox-pdm", self.public))
            self.assertTrue(updater.configured(namespace["REPO"], namespace["PUBLIC_KEY"]))
            self.assertEqual(self.write_build_info.main(["--repo", "not a repo", "--out", str(out)]), 1)
            os.environ["LITTERBOX_SIGNING_KEY"] = "garbage"
            self.assertEqual(self.write_build_info.main(["--repo", "me/litterbox-pdm", "--out", str(out)]), 1)
            os.environ["LITTERBOX_SIGNING_KEY"] = ""
            self.assertEqual(self.write_build_info.main(["--repo", "me/litterbox-pdm", "--out", str(out)]), 1)
        finally:
            os.environ.pop("LITTERBOX_SIGNING_KEY", None)


if __name__ == "__main__":
    unittest.main()
