"""Tests for uses, where-used, the release rule and the out-of-date flag (reference_queries). They need Linux, macOS or WSL."""

import unittest
from tests.support.vault_fixture import PART, PRT, git
from litterbox.vault import config
from litterbox.vault import config_write
from litterbox.references import reference_model
from litterbox.references import reference_queries
from litterbox.references import reference_reader
from litterbox.references import reference_rescan
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_revisions
from litterbox.records import record_store
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import planning
from tests.support.references_fixture import ASM, ASM_FILE, STEM_A, RefsFixture


class TestLookups(RefsFixture, unittest.TestCase):
    def test_where_used(self):
        found = reference_queries.where_used(self.a, PART)
        self.assertEqual([(u.parent, u.parent_revision, u.child_revision, u.state) for u in found],
                         [(ASM, "A", "A", reference_model.OK)])
        self.assertTrue(found[0].editable)
        self.assertEqual(reference_queries.where_used(self.a, ASM), [])

    def test_uses(self):
        found = reference_queries.uses(self.a, ASM)
        self.assertEqual([(u.child, u.child_revision, u.state) for u in found], [(PART, "A", reference_model.OK)])

    def test_a_newer_release_makes_it_stale_and_replaceable(self):
        self.release_part_rev_b()
        (use,) = reference_queries.uses(self.a, ASM)
        self.assertEqual((use.state, use.latest_released, use.replaceable), (reference_model.STALE, "B", True))
        self.assertIn("Rev B", use.state_text)
        self.assertEqual(len(reference_queries.stale_everywhere(self.a)), 1)

    def test_a_released_assembly_is_not_replaceable(self):
        self.release_part_rev_b()
        with self.user("Alex"):
            lifecycle.release(self.a, ASM)
        (use,) = reference_queries.uses(self.a, ASM)
        self.assertEqual((use.state, use.editable, use.replaceable), (reference_model.STALE, False, False))

    def test_unreleased_parts(self):
        record_states = reference_model.classify(record_store.load(self.a, ASM), "A")           # the assembly itself, unreleased
        self.assertEqual(record_states, (reference_model.UNRELEASED, ""))
        self.assertEqual(reference_model.classify(None, "A"), (reference_model.MISSING, ""))

    def test_cancelled_and_void(self):
        record = record_store.load(self.a, PART)
        record.history.append({"event": "revision_cancelled", "by": "x", "at": "t", "cancelled": "B"})
        self.assertEqual(reference_model.classify(record, "B")[0], reference_model.CANCELLED)
        record.status = record_model.STATUS_VOID
        self.assertEqual(reference_model.classify(record, "A")[0], reference_model.VOID)


class TestReleaseRule(RefsFixture, unittest.TestCase):
    def test_warns_by_default_and_still_allows_the_release(self):
        self.release_part_rev_b()
        with self.user("Alex"):
            plan = planning.release_plan(self.a, ASM)
        self.assertTrue(plan.ok, plan.problems)
        self.assertEqual(len(plan.warnings), 1)
        self.assertIn("Rev B has been released", plan.warnings[0])

    def test_block_rule_refuses(self):
        self.release_part_rev_b()
        config_write.save(self.a, org="HCR")
        data = config.load(self.a)
        data["release_rule"] = "block"
        import yaml
        (self.a / ".litterbox" / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "rule")
        git(self.a, "push")
        with self.user("Alex"):
            plan = planning.release_plan(self.a, ASM)
            self.assertFalse(plan.ok)
            with self.assertRaises(LitterboxError):
                lifecycle.release(self.a, ASM)

    def test_rule_off_and_bad_value(self):
        config_write.save(self.a, org="HCR")
        import yaml
        path = self.a / ".litterbox" / "config.yaml"
        data = config.load(self.a)
        data["release_rule"] = "off"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        self.assertEqual(config.get_release_rule(self.a), "off")
        data["release_rule"] = "maybe"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            config.get_release_rule(self.a)

    def test_a_clean_assembly_has_no_warnings(self):
        with self.user("Alex"):
            self.assertEqual(planning.release_plan(self.a, ASM).warnings, [])


class TestNeedsUpdateFlag(RefsFixture, unittest.TestCase):
    class Closed:
        """SolidWorks is not open."""
        def references(self, path):
            raise RuntimeError("SolidWorks is not open.")

        def close(self):
            pass

    def check_in_unread(self, text="assembly A, edited\n"):
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text(text, encoding="utf-8")
            checkin.checkin(self.a, ASM, "Edit", references_reader=reference_reader.make_reader(self.Closed(), self.log.append))

    def test_a_fresh_checkin_is_not_flagged(self):
        with self.user("Alex"):
            row = self.status_of(self.a, ASM)
        self.assertFalse(row.refs_outdated)
        self.assertNotIn("references need updating", row.state)

    def test_unread_assembly_change_is_flagged(self):
        self.check_in_unread()
        self.assertEqual(self.record().references_outdated, ["A"])
        with self.user("Alex"):
            row = self.status_of(self.a, ASM)
        self.assertTrue(row.refs_outdated)
        self.assertIn("(references need updating)", row.state)
        self.assertEqual(reference_queries.outdated_parts(self.a), [ASM])

    def test_other_users_see_the_flag(self):
        self.check_in_unread()
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertTrue(self.status_of(self.b, ASM).refs_outdated)

    def test_parts_and_assemblies_checked_in_normally_are_not_flagged(self):
        with self.user("Alex"):
            self.assertFalse(self.status_of(self.a, PART).refs_outdated)       # no assembly file
            checkout.checkout(self.a, ASM)
            checkin.checkin(self.a, ASM, "nothing changed", allow_unchanged=True)   # no file change: no flag
        self.assertEqual(self.record().references_outdated, [])

    def test_a_later_checkin_that_reads_clears_the_flag(self):
        self.check_in_unread()
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text(f"assembly A\nref: {self.a / PRT}\n", encoding="utf-8")
            checkin.checkin(self.a, ASM, "Again", references_reader=reference_reader.make_reader(self.fake))
        self.assertEqual(self.record().references_outdated, [])
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_an_assembly_with_no_stored_list_is_flagged_and_an_empty_list_is_not(self):
        record = record_store.load(self.a, ASM)
        record.references = {}
        self.assertTrue(record_lifecycle.references_need_update(record, "A", [ASM_FILE]))
        record.references = {"A": []}                              # read, and it uses no Litterbox parts
        self.assertFalse(record_lifecycle.references_need_update(record, "A", [ASM_FILE]))
        self.assertFalse(record_lifecycle.references_need_update(record, "A", [PRT]))
        record.cots = True
        record.references = {}
        self.assertFalse(record_lifecycle.references_need_update(record, "A", [ASM_FILE]))

    def test_update_reads_the_files_and_clears_the_flag(self):
        self.check_in_unread(f"assembly A v2\nref: {self.a / PRT}\n")
        with self.user("Alex"):
            result = reference_rescan.rescan(self.a, [ASM], backend=self.fake, log=self.log.append)
            self.assertEqual(result, {ASM: "updated"})
            self.assertFalse(self.status_of(self.a, ASM).refs_outdated)
        self.assertEqual(self.record().references_outdated, [])
        self.assertEqual(self.record().history[-1]["event"], "references_updated")

    def test_update_skips_a_checked_out_assembly(self):
        self.check_in_unread()
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            checkout.checkout(self.b, ASM)
        with self.user("Alex"):
            result = reference_rescan.rescan(self.a, [ASM], backend=self.fake, log=self.log.append)
        self.assertIn("checked out by Bea", result[ASM])
        self.assertEqual(self.record().references_outdated, ["A"])

    def test_update_reports_a_failure_instead_of_stopping(self):
        self.check_in_unread()
        with self.user("Alex"):
            result = reference_rescan.rescan(self.a, [ASM], backend=self.Closed(), log=self.log.append)
        self.assertTrue(result[ASM].startswith("skipped"))
        self.assertEqual(self.record().references_outdated, ["A"])

    def test_release_warns_that_the_list_is_out_of_date(self):
        self.check_in_unread()
        with self.user("Alex"):
            plan = planning.release_plan(self.a, ASM)
        self.assertTrue(plan.ok, plan.problems)
        self.assertTrue(any("out of date" in w for w in plan.warnings), plan.warnings)

    def test_revise_keeps_the_flag(self):
        self.check_in_unread()
        record = record_store.load(self.a, ASM)
        record.status = record_model.STATUS_RELEASED
        record.released_revision = "A"
        record_revisions.mark_revised(record, "Alex", "Rework", [])
        self.assertEqual(record.references_outdated, ["A", "B"])
        record_revisions.mark_revision_cancelled(record, "Alex", "Oops", [])
        self.assertEqual(record.references_outdated, ["A"])


if __name__ == "__main__":
    unittest.main()
