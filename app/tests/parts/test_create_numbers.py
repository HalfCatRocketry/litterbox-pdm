"""Tests for New Part and New Variant: which number a part gets, and what is checked first. They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS, is_writable
from litterbox.records import record_store
from litterbox.parts import create
from litterbox.parts import number_suggestions
from litterbox.core.part_number import PN
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.git import runner
from tests.support.create_fixture import CreateFixture


@SKIP_ON_WINDOWS
class CreateNumbers(CreateFixture, unittest.TestCase):
    def test_new_part_takes_the_lowest_free_number_and_pushes_it(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "  Rear   upright\n")
            self.assertEqual(pn, PN("HCR", 2, 1))
            record = record_store.load(self.a, pn)
            self.assertEqual((record.name, record.description, record.created_by, record.status),
                             ("Rear upright", "", "Alex", "in_work"))
            self.assertEqual(record.history[0]["event"], "created")
            self.assertIn("HCR-00002-001: Created - Rear upright", self.remote_log())
            self.assertFalse(is_writable(self.a / "PN-logs/HCR-00002-001.yaml"))   # read-only until checked out
            self.assertEqual(self.status_of(self.a, pn).state, "Created, no CAD files yet")
            self.assert_clean(self.a)
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(record_store.load(self.b, pn).created_by, "Alex")

    def test_gaps_are_filled_and_manual_numbers_are_skipped(self):
        with self.user("Alex"):
            self.assertEqual(create.new_part(self.a, "Typed in by hand", base=4), PN("HCR", 4, 1))
            numbers = [create.new_part(self.a, f"Part {n}").base for n in range(3)]
            self.assertEqual(numbers, [2, 3, 5])

    def test_numbers_loop_round_to_the_bottom_after_the_highest(self):
        from litterbox.vault import config_write
        config_write.save(self.a, org="HCR", start_number=99998)       # 5 digits: the highest is 99999
        with self.user("Alex"):
            numbers = [create.new_part(self.a, f"Part {n}").base for n in range(4)]
            self.assertEqual(numbers, [99998, 99999, 2, 3])      # 1 is already in use; zero is never used
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 4)

    def test_a_vault_with_no_numbers_left_says_so_plainly(self):
        with self.user("Alex"):
            with mock.patch.object(record_store, "used_bases", return_value=set(range(1, 100000))):
                with self.assertRaises(create.CreateError) as caught:
                    create.new_part(self.a, "One too many")
                self.assertIn("no part numbers left", str(caught.exception))
                with self.assertRaises(create.CreateError):
                    number_suggestions.suggest_part_number(self.a)
            self.assertEqual(sorted(p.name for p in (self.a / "PN-logs").iterdir()), ["HCR-00001-001.yaml"])

    def test_part_number_in_use_gets_its_lowest_free_variant(self):
        with self.user("Alex"):
            self.assertEqual(create.new_part(self.a, "Right hand", base=1), PN("HCR", 1, 2))
            self.assertEqual(create.new_part(self.a, "Left hand", base=1), PN("HCR", 1, 3))
            self.assertEqual(create.new_part(self.a, "Typed variant", base=1, variant=9), PN("HCR", 1, 9))
            self.assertEqual(create.new_part(self.a, "Fresh base", base=300), PN("HCR", 300, 1))
            self.assert_clean(self.a)

    def test_variant_alone_goes_on_the_next_free_part_number(self):
        with self.user("Alex"):
            self.assertEqual(create.new_part(self.a, "Spare", variant=501), PN("HCR", 2, 501))
            self.assertEqual(create.new_part(self.a, "Next", variant=501), PN("HCR", 3, 501))
            self.assertEqual(create.new_part(self.a, "Plain"), PN("HCR", 4, 1))

    def test_suggested_numbers_for_the_empty_boxes(self):
        with self.user("Alex"):
            self.assertEqual(number_suggestions.suggest_numbers(self.a), (2, 1))
            self.assertEqual(number_suggestions.suggest_numbers(self.a, 1), (1, 2))        # in use: lowest free variant
            self.assertEqual(number_suggestions.suggest_numbers(self.a, 77), (77, 1))      # unused: 001
            create.new_part(self.a, "Right hand", base=1)
            self.assertEqual(number_suggestions.suggest_numbers(self.a, 1), (1, 3))
            from litterbox.vault import config_write
            config_write.save(self.a, start_number=10001)
            self.assertEqual(number_suggestions.suggest_numbers(self.a), (10001, 1))
            with self.assertRaises(create.CreateError):
                number_suggestions.suggest_numbers(self.a, 0)

    def test_check_numbers_says_what_would_be_created_and_whether_it_is_free(self):
        with self.user("Alex"):
            check = number_suggestions.check_numbers(self.a)
            self.assertEqual((check.pn, check.taken), (PN("HCR", 2, 1), False))
            check = number_suggestions.check_numbers(self.a, 1, 1)
            self.assertEqual((check.pn, check.taken, check.name, check.status),
                             (PN("HCR", 1, 1), True, "Front upright", "in_work"))
            check = number_suggestions.check_numbers(self.a, 1)                       # variant left empty
            self.assertEqual((check.pn, check.taken), (PN("HCR", 1, 2), False))
            check = number_suggestions.check_numbers(self.a, None, 501)               # base left empty
            self.assertEqual((check.pn, check.taken), (PN("HCR", 2, 501), False))
            self.assertFalse(number_suggestions.check_numbers(self.a, 1, 2).taken)
            for bad in ((0, None), (None, 0), (None, 1000), (100000, None)):
                with self.subTest(bad=bad), self.assertRaises(create.CreateError):
                    number_suggestions.check_numbers(self.a, *bad)

    def test_void_parts_still_count_as_in_use(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "Scrapped idea", base=50, variant=1)
            lifecycle.void(self.a, pn, "Not needed")
            check = number_suggestions.check_numbers(self.a, 50, 1)
            self.assertEqual((check.taken, check.name, check.status), (True, "Scrapped idea", "void"))
            with self.assertRaises(create.CreateError):
                create.new_part(self.a, "Reuse attempt", base=50, variant=1)

    def test_automatic_numbers_start_at_start_number_whatever_exists_below_it(self):
        from litterbox.vault import config_write
        with self.user("Alex"):
            config_write.save(self.a, start_number=10001)             # HCR-00001-001 already exists
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 10001)
            self.assertEqual(create.new_part(self.a, "First of the range"), PN("HCR", 10001, 1))
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 10002)
            self.assertEqual(create.new_part(self.a, "Typed higher", base=10004, variant=1), PN("HCR", 10004, 1))
            self.assertEqual(create.new_part(self.a, "Second"), PN("HCR", 10002, 1))
            self.assertEqual(create.new_part(self.a, "Third"), PN("HCR", 10003, 1))
            self.assertEqual(create.new_part(self.a, "Fifth"), PN("HCR", 10005, 1))
            self.assertEqual(create.new_part(self.a, "Typed below", base=2, variant=1), PN("HCR", 2, 1))
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 10006)       # a part at 00002 changes nothing

    def test_explicit_part_number_and_variant_that_are_taken_are_refused(self):
        commits = len(self.remote_log())
        with self.user("Alex"):
            with self.assertRaises(create.CreateError) as ctx:
                create.new_part(self.a, "Duplicate", base=1, variant=1)
            message = str(ctx.exception)
            self.assertIn("HCR-00001-001", message)
            self.assertIn("Front upright", message)          # says who has it
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)
        self.assertEqual(len(self.remote_log()), commits)

    def test_org_can_be_given_or_set_in_the_vault(self):
        with self.user("Alex"):
            self.assertEqual(create.new_part(self.a, "Other org", org="fsae"), PN("FSAE", 1, 1))
            config_file = self.a / ".litterbox" / "config.yaml"
            config_file.parent.mkdir()
            config_file.write_text("org: FSAE\n", encoding="utf-8")
            self.assertEqual(create.new_part(self.a, "From config"), PN("FSAE", 2, 1))

    def test_description_is_checked_before_any_git_work(self):
        with self.user("Alex"):
            with mock.patch.object(runner, "run", side_effect=AssertionError("git should not run")):
                for bad in ("", "   \n ", "x" * 201):
                    with self.subTest(bad=bad[:10]):
                        with self.assertRaises(create.CreateError):
                            create.new_part(self.a, bad)
            self.assert_clean(self.a)

    def test_void_numbers_are_never_reused(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "Never built")
            lifecycle.void(self.a, pn, "Not needed")
            self.assertEqual(create.new_part(self.a, "Next one"), PN("HCR", 3, 1))

    def test_new_variant_numbers(self):
        with self.user("Alex"):
            self.assertEqual(create.new_variant(self.a, 1, "Right hand"), PN("HCR", 1, 2))
            self.assertEqual(create.new_variant(self.a, 1, "Long", variant=5), PN("HCR", 1, 5))
            self.assertEqual(create.new_variant(self.a, 1, "Short"), PN("HCR", 1, 3))      # fills the gap
            self.assertIn("HCR-00001-005: Created - Long", self.remote_log())

    def test_name_is_required_and_description_is_optional(self):
        with self.user("Alex"):
            for bad in ("", "   "):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, bad)
                self.assertIn("name is required", str(ctx.exception))
            with self.assertRaises(create.CreateError):
                create.new_part(self.a, "x" * 101)
            with self.assertRaises(create.CreateError):
                create.new_part(self.a, "Fine", description="x" * 501)
            pn = create.new_part(self.a, "Gusset", description="  for the  rear\nframe ")
            self.assertEqual((record_store.load(self.a, pn).name, record_store.load(self.a, pn).description),
                             ("Gusset", "for the rear frame"))
            pn = create.new_variant(self.a, 1, "Gusset, mirrored")
            self.assertEqual(record_store.load(self.a, pn).description, "")
            self.assert_clean(self.a)

    def test_new_variant_needs_no_existing_base(self):
        with self.user("Alex"):
            self.assertEqual(create.new_variant(self.a, 12345, "Spare bracket", variant=501),
                             PN("HCR", 12345, 501))
            self.assertEqual(create.new_variant(self.a, 777, "Another"), PN("HCR", 777, 1))
            self.assertIn("HCR-12345-501: Created - Spare bracket", self.remote_log())
            self.assert_clean(self.a)

    def test_start_number_from_vault_config(self):
        from litterbox.vault import config_write
        with self.user("Alex"):
            config_write.save(self.a, start_number=10001)
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 10001)
            self.assertEqual(create.new_part(self.a, "First of the range"), PN("HCR", 10001, 1))
            self.assertEqual(create.new_part(self.a, "Second"), PN("HCR", 10002, 1))
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 10003)

    def test_new_variant_refuses_taken_numbers(self):
        with self.user("Alex"):
            with self.assertRaises(create.CreateError) as ctx:
                create.new_variant(self.a, 1, "Again", variant=1)
            self.assertIn("already in use", str(ctx.exception))
            self.assertIn("Front upright", str(ctx.exception))
            for bad in (0, 1000):
                with self.assertRaises(create.CreateError):
                    create.new_variant(self.a, 1, "Out of range", variant=bad)
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)

    def test_suggestions_and_listing(self):
        with self.user("Alex"):
            create.new_variant(self.a, 1, "Right hand")
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 2)
            self.assertEqual(number_suggestions.suggest_variant_number(self.a, 1), 3)
            self.assertEqual(number_suggestions.suggest_variant_number(self.a, 50), 1)
            rows = number_suggestions.list_variants(self.a, 1)
            self.assertEqual([(str(r.pn), r.name) for r in rows],
                             [("HCR-00001-001", "Front upright"), ("HCR-00001-002", "Right hand")])
            self.assertEqual(number_suggestions.list_variants(self.a, 50), [])


if __name__ == "__main__":
    unittest.main()
