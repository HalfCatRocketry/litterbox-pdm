import sys
import tempfile
import unittest
from pathlib import Path


from litterbox.vault import compatibility
from litterbox.vault import config
from litterbox.vault import config_write
from litterbox import version


class Versions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(version.parse("0.1.0"), (0, 1, 0))
        self.assertEqual(version.parse("v1.12.3"), (1, 12, 3))
        for bad in ("1.2", "1.2.3.4", "a.b.c", "", "1.2.x", "1.-2.3"):
            with self.assertRaises(ValueError):
                version.parse(bad)

    def test_numbers_not_text_decide_which_is_newer(self):
        self.assertTrue(version.is_newer("0.10.0", "0.9.0"))
        self.assertFalse(version.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(version.is_newer("0.1.0", "0.1.1"))

    def test_the_version_is_well_formed_and_not_older_than_the_first_release(self):
        self.assertFalse(version.is_newer("0.1.0", version.VERSION))
        self.assertEqual(version.VAULT_FORMAT, 1)
        version.parse(version.VERSION)

    def test_a_source_copy_says_so(self):
        self.assertFalse(version.is_installed_build())
        self.assertIn("from source", version.display())
        sys.frozen = True
        try:
            self.assertEqual(version.display(), version.VERSION)
        finally:
            del sys.frozen


class VaultCompatibility(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = (version.VERSION, version.VAULT_FORMAT)
        self.addCleanup(lambda: (setattr(version, "VERSION", self.saved[0]),
                                 setattr(version, "VAULT_FORMAT", self.saved[1])))

    def write(self, text):
        path = Path(self.dir) / ".litterbox"
        path.mkdir(exist_ok=True)
        (path / "config.yaml").write_text(text, encoding="utf-8")

    def test_old_vaults_without_the_fields_work(self):
        self.write("org: HCR\n")
        compatibility.check_compatible(self.dir)
        compatibility.check_compatible(Path(self.dir) / "nowhere")            # no config at all is fine too

    def test_a_newer_vault_format_is_refused(self):
        self.write("org: HCR\nformat_version: 2\n")
        with self.assertRaisesRegex(config.ConfigError, "newer Litterbox"):
            compatibility.check_compatible(self.dir)
        version.VAULT_FORMAT = 2                                       # a Litterbox that knows format 2 is fine
        compatibility.check_compatible(self.dir)

    def test_a_minimum_version_is_enforced(self):
        self.write("org: HCR\nmin_litterbox_version: 9.0.0\n")
        with self.assertRaisesRegex(config.ConfigError, "needs Litterbox 9.0.0"):
            compatibility.check_compatible(self.dir)
        version.VERSION = "9.0.0"
        compatibility.check_compatible(self.dir)
        version.VERSION = "10.0.0"                                     # compared as numbers, not text
        compatibility.check_compatible(self.dir)

    def test_nonsense_values_get_a_plain_message(self):
        for text in ("format_version: abc\n", "format_version: 0\n", "format_version: true\n",
                     "min_litterbox_version: soon\n"):
            self.write("org: HCR\n" + text)
            with self.assertRaises(config.ConfigError):
                compatibility.check_compatible(self.dir)

    def test_the_check_runs_whenever_a_vault_is_opened(self):
        self.write("org: HCR\nmin_litterbox_version: 9.0.0\n")
        with self.assertRaises(config.ConfigError):
            config.apply(self.dir)

    def test_stamp_records_the_format_and_never_lowers_the_minimum(self):
        self.write("org: HCR\n")
        config_write.stamp(self.dir, min_version="0.1.0")
        data = config.load(self.dir)
        self.assertEqual((data["org"], data["format_version"], data["min_litterbox_version"]), ("HCR", 1, "0.1.0"))
        config_write.stamp(self.dir, min_version="0.3.0")
        self.assertEqual(config.load(self.dir)["min_litterbox_version"], "0.3.0")
        config_write.stamp(self.dir, min_version="0.2.0")                     # lower: ignored
        self.assertEqual(config.load(self.dir)["min_litterbox_version"], "0.3.0")
        with self.assertRaises(ValueError):
            config_write.stamp(self.dir, min_version="soon")

    def test_stamp_never_lowers_the_format(self):
        self.write("org: HCR\nformat_version: 3\n")
        config_write.stamp(self.dir)
        self.assertEqual(config.load(self.dir)["format_version"], 3)


if __name__ == "__main__":
    unittest.main()
