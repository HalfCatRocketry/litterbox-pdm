"""
Tests for references.py: the parts an assembly uses, where a part is used, stale references, the release
rule, and pointing assemblies at newer revisions. A pretend SolidWorks is used (a document is text; each
'ref: <path>' line is one reference). They need Linux, macOS or WSL.

Run from the app folder with:  python -m unittest discover -s tests -t . -v
"""

import unittest

from tests.support.import_fixture import FakeSolidWorks
from tests.support.vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, TwoUserVault, git

from litterbox.vault import config
from litterbox.references import references as refs
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_revisions
from litterbox.records import record_store
from litterbox.parts import revise
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.git import lfs_locks
from litterbox.parts import lifecycle
from litterbox.parts import planning
from litterbox.git import read_only

ASM = PN("HCR", 2, 1)
ASM_FILE = "cad/HCR-00002-001_A.SLDASM"
PRT_B = PRT.replace("_A.", "_B.")
STEM_A, STEM_B = "HCR-00001-001_A", "HCR-00001-001_B"


@SKIP_ON_WINDOWS
class RefsFixture(TwoUserVault):
    """Part 1 is released at Rev A. Assembly 2 (Rev A, in work, checked in) uses part 1 Rev A."""

    def setUp(self):
        super().setUp()
        self.fake = FakeSolidWorks(self.root)
        self.log = []
        with self.user("Alex"):
            for rel in (PRT, DRW):
                (self.a / rel).chmod(0o644)
            (self.a / PRT).write_text("model A\n", encoding="utf-8")
            (self.a / DRW).write_text(f"drawing A\nref: {self.a / PRT}\n", encoding="utf-8")
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Make the files text")
            git(self.a, "push")
            read_only.enforce_read_only(self.a)
            lifecycle.release(self.a, PART)
            self.add_created_part(2, "Frame")
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text(f"assembly A\nref: {self.a / PRT}\n", encoding="utf-8")
            checkin.checkin(self.a, ASM, "First version", references_reader=refs.make_reader(self.fake))
        with self.user("Bea"):
            get_latest.get_latest(self.b)

    def locks(self, repo):
        with self.user("Alex" if repo == self.a else "Bea"):
            return lfs_locks.get_locks(repo, strict=True)

    def record(self, repo=None, pn=ASM):
        return record_store.load(repo or self.a, pn)

    def release_part_rev_b(self):
        """Part 1 gets a Rev B, which is released."""
        with self.user("Alex"):
            revise.revise(self.a, PART, "Bigger hole", backend=self.fake, log=lambda *_: None)
            (self.a / PRT_B).write_text("model B\n", encoding="utf-8")
            checkin.checkin(self.a, PART, "Changed")
            lifecycle.release(self.a, PART)

    def replace(self, repo=None, user="Alex", pn=ASM):
        repo = repo or self.a
        with self.user(user):
            items = refs.replacements_from(refs.uses(repo, pn))
            return refs.replace_references(repo, items, backend=self.fake, log=self.log.append)


class TestRecordingReferences(RefsFixture, unittest.TestCase):
    def test_checkin_stores_what_the_assembly_uses(self):
        record = self.record()
        self.assertEqual(record.references, {"A": [STEM_A]})
        event = [e for e in record.history if e["event"] == "checked_in"][-1]
        self.assertEqual(event["references"], [STEM_A])
        text = (self.a / REC.replace("00001", "00002")).read_text()
        self.assertIn("references:", text)

    def test_other_users_see_them_after_get_latest(self):
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(self.record(self.b).references, {"A": [STEM_A]})

    def test_a_part_with_no_assembly_file_has_no_references(self):
        self.assertEqual(self.record(pn=PART).references, {})

    def test_unreadable_solidworks_does_not_block_the_checkin(self):
        class Broken:
            def references(self, path):
                raise RuntimeError("SolidWorks is not available")

            def close(self):
                pass

        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text("assembly A, edited\n", encoding="utf-8")
            checkin.checkin(self.a, ASM, "Edit", references_reader=refs.make_reader(Broken(), self.log.append))
        self.assertEqual(self.record().references, {"A": [STEM_A]})            # unchanged
        self.assertTrue(any("could not read" in line for line in self.log))
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")

    def test_check_in_never_starts_solidworks(self):
        from unittest import mock
        made = []

        def fake_new_backend(attach_only=False):
            made.append(attach_only)
            raise RuntimeError("SolidWorks is not open.")

        with self.user("Alex"), mock.patch.object(refs, "_new_backend", fake_new_backend):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text("assembly A, edited\n", encoding="utf-8")
            checkin.checkin(self.a, ASM, "Edit", references_reader=refs.make_reader(log=self.log.append))
        self.assertEqual(made, [True])                                 # asked to attach only
        self.assertEqual(self.record().references, {"A": [STEM_A]})
        self.assertTrue(any("SolidWorks is not open" in line for line in self.log))

    def test_files_that_are_not_litterbox_files_are_ignored(self):
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text(f"assembly\nref: {self.a / PRT}\nref: /lib/screw.SLDPRT\n", encoding="utf-8")
            checkin.checkin(self.a, ASM, "Add a screw", references_reader=refs.make_reader(self.fake))
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_the_reader_does_not_touch_solidworks_when_no_assembly_changed(self):
        class Spy:
            calls = 0

            def references(self, path):
                Spy.calls += 1
                return []

        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            checkin.checkin(self.a, ASM, "No file change", allow_unchanged=True,
                        references_reader=refs.make_reader(Spy()))
        self.assertEqual(Spy.calls, 0)
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_revise_copies_references_to_the_new_revision(self):
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            checkin.checkin(self.a, ASM, "x", allow_unchanged=True)
            lifecycle.release(self.a, ASM)
            revise.revise(self.a, ASM, "Rework", backend=self.fake, log=lambda *_: None)
        self.assertEqual(self.record().references, {"A": [STEM_A], "B": [STEM_A]})


class TestLookups(RefsFixture, unittest.TestCase):
    def test_where_used(self):
        found = refs.where_used(self.a, PART)
        self.assertEqual([(u.parent, u.parent_revision, u.child_revision, u.state) for u in found],
                         [(ASM, "A", "A", refs.OK)])
        self.assertTrue(found[0].editable)
        self.assertEqual(refs.where_used(self.a, ASM), [])

    def test_uses(self):
        found = refs.uses(self.a, ASM)
        self.assertEqual([(u.child, u.child_revision, u.state) for u in found], [(PART, "A", refs.OK)])

    def test_a_newer_release_makes_it_stale_and_replaceable(self):
        self.release_part_rev_b()
        (use,) = refs.uses(self.a, ASM)
        self.assertEqual((use.state, use.latest_released, use.replaceable), (refs.STALE, "B", True))
        self.assertIn("Rev B", use.state_text)
        self.assertEqual(len(refs.stale_everywhere(self.a)), 1)

    def test_a_released_assembly_is_not_replaceable(self):
        self.release_part_rev_b()
        with self.user("Alex"):
            lifecycle.release(self.a, ASM)
        (use,) = refs.uses(self.a, ASM)
        self.assertEqual((use.state, use.editable, use.replaceable), (refs.STALE, False, False))

    def test_unreleased_parts(self):
        record_states = refs.classify(record_store.load(self.a, ASM), "A")           # the assembly itself, unreleased
        self.assertEqual(record_states, (refs.UNRELEASED, ""))
        self.assertEqual(refs.classify(None, "A"), (refs.MISSING, ""))

    def test_cancelled_and_void(self):
        record = record_store.load(self.a, PART)
        record.history.append({"event": "revision_cancelled", "by": "x", "at": "t", "cancelled": "B"})
        self.assertEqual(refs.classify(record, "B")[0], refs.CANCELLED)
        record.status = record_model.STATUS_VOID
        self.assertEqual(refs.classify(record, "A")[0], refs.VOID)


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
        config.save(self.a, org="HCR")
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
        config.save(self.a, org="HCR")
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


class TestReplace(RefsFixture, unittest.TestCase):
    def test_replace_checks_out_edits_checks_in_and_updates_the_record(self):
        self.release_part_rev_b()
        (result,) = self.replace()
        self.assertEqual((result.parent, result.status), (ASM, "done"), result.message)
        text = (self.a / ASM_FILE).read_text()
        self.assertIn(f"ref: {self.a / PRT_B}", text)
        self.assertNotIn(f"ref: {self.a / PRT}\n", text)
        self.assertEqual(self.record().references, {"A": [STEM_B]})
        self.assertEqual(self.locks(self.a), {})
        self.assertIn("HCR-00002-001: Updated to the latest released parts", self.remote_log())
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertEqual(refs.stale_everywhere(self.a), [])
        self.assertEqual(refs.where_used(self.a, PART)[0].child_revision, "B")

    def test_assembly_checked_out_by_someone_else_is_skipped(self):
        self.release_part_rev_b()
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            checkout.checkout(self.b, ASM)
        (result,) = self.replace()
        self.assertEqual(result.status, "skipped")
        self.assertIn("Bea", result.message)
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_assembly_you_have_checked_out_is_changed_but_left_for_you_to_check_in(self):
        self.release_part_rev_b()
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
        (result,) = self.replace()
        self.assertEqual(result.status, "left_checked_out")
        self.assertIn(f"ref: {self.a / PRT_B}", (self.a / ASM_FILE).read_text())
        self.assertEqual(self.record().references, {"A": [STEM_A]})             # not yet
        with self.user("Alex"):
            checkin.checkin(self.a, ASM, "Take new part", references_reader=refs.make_reader(self.fake))
        self.assertEqual(self.record().references, {"A": [STEM_B]})

    def test_a_failure_undoes_the_checkout_and_leaves_the_assembly_alone(self):
        self.release_part_rev_b()
        self.fake.refuse_repoint = True
        (result,) = self.replace()
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.locks(self.a), {})
        self.assertIn(f"ref: {self.a / PRT}", (self.a / ASM_FILE).read_text())
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_released_assemblies_and_up_to_date_references_are_never_in_the_list(self):
        self.assertEqual(refs.replacements_from(refs.uses(self.a, ASM)), [])
        self.release_part_rev_b()
        with self.user("Alex"):
            lifecycle.release(self.a, ASM)
        self.assertEqual(refs.stale_everywhere(self.a), [])

    def test_replace_refuses_a_part_whose_new_file_is_not_downloaded(self):
        self.release_part_rev_b()
        items = [refs.Replacement(ASM, PART, "A")]
        pointer = self.a / PRT_B
        pointer.chmod(0o644)                                  # a part that isn't checked out is read-only on disk
        pointer.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 1\n")
        (result,) = refs.replace_references(self.a, items, backend=self.fake, log=self.log.append)
        self.assertEqual(result.status, "failed")


class TestRescan(RefsFixture, unittest.TestCase):
    def test_rescan_fills_in_records_that_have_no_references(self):
        record_path = self.a / "PN-logs" / "HCR-00002-001.yaml"
        with self.user("Alex"):
            lfs_locks.lock(self.a, "PN-logs/HCR-00002-001.yaml", ASM)
            record = record_store.load(self.a, ASM)
            record.references = {}
            record_store.save(self.a, record)
            git(self.a, "commit", "-am", "forget the references")
            git(self.a, "push")
            lfs_locks.unlock_mine(self.a, ["PN-logs/HCR-00002-001.yaml"])
            read_only.enforce_read_only(self.a)
            result = refs.rescan(self.a, backend=self.fake, log=self.log.append)
        self.assertEqual(result, {ASM: "updated"})
        self.assertEqual(self.record().references, {"A": [STEM_A]})
        with self.user("Alex"):
            self.assertEqual(refs.rescan(self.a, backend=self.fake, log=self.log.append), {ASM: "unchanged"})
        self.assertTrue(record_path.exists())


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
            checkin.checkin(self.a, ASM, "Edit", references_reader=refs.make_reader(self.Closed(), self.log.append))

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
        self.assertEqual(refs.outdated_parts(self.a), [ASM])

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
            checkin.checkin(self.a, ASM, "Again", references_reader=refs.make_reader(self.fake))
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
            result = refs.rescan(self.a, [ASM], backend=self.fake, log=self.log.append)
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
            result = refs.rescan(self.a, [ASM], backend=self.fake, log=self.log.append)
        self.assertIn("checked out by Bea", result[ASM])
        self.assertEqual(self.record().references_outdated, ["A"])

    def test_update_reports_a_failure_instead_of_stopping(self):
        self.check_in_unread()
        with self.user("Alex"):
            result = refs.rescan(self.a, [ASM], backend=self.Closed(), log=self.log.append)
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


class TestRecordFormat(unittest.TestCase):
    def test_round_trip_and_validation(self):
        record = record_model.Record(pn=PN("HCR", 2, 1), name="x", created_by="a", created_at="t")
        record.references = {"B": ["HCR-00001-001_A"], "A": ["HCR-00001-001_A", "HCR-00003-001_C"]}
        again = record_model.Record.from_dict(__import__("yaml").safe_load(record_model.dump(record)))
        self.assertEqual(again.references, record.references)
        data = record.to_dict()
        self.assertEqual(list(data["references"]), ["A", "B"])
        record.references_outdated = ["B", "A"]
        self.assertEqual(record_model.Record.from_dict(__import__("yaml").safe_load(record_model.dump(record))).references_outdated,
                         ["A", "B"])
        data["references"] = ["nope"]
        with self.assertRaises(record_model.RegistryError):
            record_model.Record.from_dict(data)
        self.assertNotIn("references", record_model.Record(pn=PN("HCR", 3, 1), name="y", created_by="a",
                                                       created_at="t").to_dict())


if __name__ == "__main__":
    unittest.main()