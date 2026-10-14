"""Tests for config.py. Run from the app folder with:  python -m unittest discover -s tests -t . -v"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from litterbox.vault import config
from litterbox.parts import engine as eng
from litterbox.core import pn as pn_module
from litterbox.records import registry
from litterbox.core.pn import PN
from litterbox.errors import LitterboxError


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)

    def write_config(self, text):
        path = config.config_path(self.repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def make(self, org, base=1):
        registry.create_record(self.repo, PN(org, base, 1), "A part", "Alex")

    def test_config_file_wins(self):
        self.make("HCR")
        self.write_config("org: fsae\n")
        self.assertEqual(config.get_org(self.repo), "FSAE")

    def test_works_with_no_records_when_configured(self):
        self.write_config("org: HCR\n")
        self.assertEqual(config.get_org(self.repo), "HCR")

    def test_inferred_from_records_when_there_is_no_file(self):
        self.make("HCR", 1)
        self.make("HCR", 2)
        self.assertEqual(config.get_org(self.repo), "HCR")

    def test_empty_vault_without_a_file_explains_what_to_do(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.get_org(self.repo)
        self.assertIn("org: HCR", str(ctx.exception))

    def test_several_orgs_need_a_decision(self):
        self.make("HCR", 1)
        self.make("FSAE", 1)
        with self.assertRaises(config.ConfigError) as ctx:
            config.get_org(self.repo)
        self.assertIn("FSAE, HCR", str(ctx.exception))
        self.write_config("org: HCR\n")
        self.assertEqual(config.get_org(self.repo), "HCR")

    def test_bad_values_are_reported(self):
        for text in ("org: H\n", "org: TOOLONG\n", "org: 12\n"):
            with self.subTest(text=text):
                self.write_config(text)
                with self.assertRaises(config.ConfigError):
                    config.get_org(self.repo)

    def test_broken_files_are_reported(self):
        for text in ("just: [broken\n", "- a list\n- not settings\n"):
            with self.subTest(text=text):
                self.write_config(text)
                with self.assertRaises(config.ConfigError):
                    config.load(self.repo)

    def test_empty_file_is_fine(self):
        self.write_config("")
        self.assertEqual(config.load(self.repo), {})
        self.make("HCR")
        self.assertEqual(config.get_org(self.repo), "HCR")

    def test_start_number(self):
        self.assertEqual(config.get_start_number(self.repo), 1)
        self.write_config("org: HCR\nstart_number: 10001\n")
        self.assertEqual(config.get_start_number(self.repo), 10001)
        for text in ("start_number: 0\n", "start_number: abc\n", "start_number: 1.5\n", "start_number: true\n"):
            with self.subTest(text=text):
                self.write_config(text)
                with self.assertRaises(config.ConfigError):
                    config.get_start_number(self.repo)

    def test_save_keeps_other_values(self):
        config.save(self.repo, org="hcr")
        config.save(self.repo, start_number=10001)
        self.assertEqual(config.load(self.repo), {"org": "HCR", "start_number": 10001})
        with self.assertRaises(config.ConfigError):
            config.save(self.repo, start_number=0)

    def test_no_org_has_its_own_error(self):
        with self.assertRaises(config.NoOrgError):
            config.get_org(self.repo)

    def test_digits_default_to_five_and_three(self):
        self.assertEqual(config.get_digits(self.repo), (5, 3))
        self.write_config("org: HCR\npn_base_digits: 6\n")
        self.assertEqual(config.get_digits(self.repo), (6, 3))
        self.write_config("org: HCR\npn_base_digits: 6\npn_variant_digits: 2\n")
        self.assertEqual(config.get_digits(self.repo), (6, 2))

    def test_bad_digits_are_reported(self):
        for text in ("pn_base_digits: 0\n", "pn_base_digits: 10\n", "pn_variant_digits: 5\n",
                     "pn_variant_digits: abc\n", "pn_base_digits: true\n", "pn_variant_digits: 2.5\n"):
            with self.subTest(text=text):
                self.write_config(text)
                with self.assertRaises(config.ConfigError):
                    config.get_digits(self.repo)

    def test_apply_sets_the_format_for_the_rest_of_the_program(self):
        self.addCleanup(pn_module.configure)
        self.write_config("org: HCR\npn_base_digits: 6\npn_variant_digits: 2\n")
        self.assertEqual(config.apply(self.repo), (6, 2))
        self.assertEqual(str(PN("HCR", 42, 1)), "HCR-000042-01")

    def test_digits_can_be_chosen_in_an_empty_vault_but_not_changed_afterwards(self):
        self.addCleanup(pn_module.configure)
        config.save(self.repo, org="HCR", base_digits=6, variant_digits=2)
        self.assertEqual(config.get_digits(self.repo), (6, 2))
        config.apply(self.repo)
        self.make("HCR", 7)
        config.save(self.repo, base_digits=6)                      # unchanged: fine
        with self.assertRaises(config.ConfigError) as ctx:
            config.save(self.repo, base_digits=5)
        self.assertIn("can't be changed", str(ctx.exception))
        self.assertEqual(config.get_digits(self.repo), (6, 2))     # nothing was written
        with self.assertRaises(config.ConfigError):
            config.save(self.repo, variant_digits=9)

    def test_the_engine_learns_the_digits_whenever_it_starts_work_on_a_vault(self):
        self.addCleanup(pn_module.configure)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write_config("org: HCR\npn_base_digits: 6\npn_variant_digits: 2\n")
        eng.validate_repo(self.repo)
        self.assertEqual((pn_module.BASE_DIGITS, pn_module.VARIANT_DIGITS), (6, 2))
        self.write_config("org: HCR\n")
        eng.validate_repo(self.repo)
        self.assertEqual((pn_module.BASE_DIGITS, pn_module.VARIANT_DIGITS), (5, 3))
        self.write_config("org: HCR\npn_base_digits: 0\n")
        with self.assertRaises(LitterboxError):
            eng.validate_repo(self.repo)


if __name__ == "__main__":
    unittest.main()