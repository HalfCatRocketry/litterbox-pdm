"""Tests for importing into a project (import_numbering with Proposal.project), and for opening a saved scan whose
items were imported before. No git: the vault is a folder with a settings file and records."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from litterbox.core import part_number
from litterbox.core.part_number import PN
from litterbox.gui.logic import import_table
from litterbox.importing import import_errors
from litterbox.importing import import_numbering
from litterbox.importing import import_prepare
from litterbox.importing import manifest as manifest_module
from litterbox.importing import scan
from litterbox.records import record_store
from litterbox.vault import config

SETTINGS = """org: HCR
pn_base_digits: 5
pn_variant_digits: 3
start_number: 10001
projects:
- name: Rover
  prefix: '12'
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name)
        config.config_path(self.repo).parent.mkdir(parents=True)
        config.config_path(self.repo).write_text(SETTINGS, encoding="utf-8")
        self.addCleanup(part_number.configure, part_number.BASE_DIGITS, part_number.VARIANT_DIGITS)
        config.apply(self.repo)
        for base in (12000 + 1, 12000 + 2, 10001):                # 12001 and 12002 are taken in Rover
            record_store.create_record(self.repo, PN("HCR", base, 1), f"Part {base}", "Alex")
        self.rover = config.get_projects(self.repo)[0]

    def proposal(self, count=3, project=None):
        items = [SimpleNamespace(kind="part", id=n) for n in range(count)]
        block = import_numbering.pick_block(self.repo, count, "HCR", gap=0, jitter=0, project=project)
        return import_numbering.Proposal([import_numbering.Entry(item, pn, f"Item {n}")
                                          for n, (item, pn) in enumerate(zip(items, block))], "HCR", project=project)


class Numbers(Fixture):
    def test_in_a_project_the_lowest_unused_numbers_of_its_block_are_proposed(self):
        self.assertEqual([pn.base for pn in self.proposal(project=self.rover).pns()], [12000, 12003, 12004])

    def test_with_no_project_numbers_stay_outside_every_block(self):
        self.assertTrue(all(not self.rover.contains(pn.base) for pn in self.proposal().pns()))

    def test_choosing_a_project_renumbers_the_automatic_rows_but_not_typed_ones(self):
        proposal = self.proposal()
        proposal.set_pn(0, "HCR-10500-001")
        import_numbering.set_project(self.repo, proposal, self.rover, sync=False)
        self.assertEqual([pn.base for pn in proposal.pns()], [10500, 12000, 12003])
        conflicts = import_numbering.check_proposal(self.repo, proposal)
        self.assertEqual([c.index for c in conflicts], [0])                     # the typed one isn't in Rover
        self.assertIn("isn't in project Rover (12000 to 12999)", conflicts[0].reason)
        import_numbering.set_project(self.repo, proposal, None, sync=False)
        self.assertTrue(all(not self.rover.contains(pn.base) for pn in proposal.pns()[1:]))
        self.assertEqual(import_numbering.check_proposal(self.repo, proposal), [])

    def test_a_family_must_be_in_the_project_and_one_outside_it_is_dropped(self):
        proposal = self.proposal(2)
        import_numbering.set_family(self.repo, proposal, 10600, sync=False)
        import_numbering.set_project(self.repo, proposal, self.rover, sync=False)
        self.assertIsNone(proposal.family)
        self.assertEqual([pn.base for pn in proposal.pns()], [12000, 12003])
        with self.assertRaisesRegex(import_errors.ImportFailed, "isn't in project Rover"):
            import_numbering.set_family(self.repo, proposal, 10600, sync=False)
        import_numbering.set_family(self.repo, proposal, 12001, sync=False)     # in use: the next free variants
        self.assertEqual([str(pn) for pn in proposal.pns()], ["HCR-12001-002", "HCR-12001-003"])

    def test_a_full_project_is_refused_and_nothing_changes(self):
        proposal = self.proposal(3)
        before = proposal.pns()
        tiny = SimpleNamespace(name="Tiny", block=lambda: (12000, 12003), contains=lambda b: 12000 <= b <= 12003,
                               describe=lambda: "Tiny (12000 to 12003)")
        with self.assertRaisesRegex(import_errors.ImportFailed, "doesn't have 3 unused part numbers"):
            import_numbering.set_project(self.repo, proposal, tiny, sync=False)
        self.assertEqual((proposal.pns(), proposal.project), (before, None))

    def test_a_row_ticked_later_also_gets_a_number_in_the_project(self):
        proposal = self.proposal(1, self.rover)
        pn = import_prepare.free_pn(self.repo, proposal, SimpleNamespace(kind="part"))
        self.assertEqual(pn.base, 12003)
        proposal.entries.clear()
        self.assertEqual(import_prepare.free_pn(self.repo, proposal, SimpleNamespace(kind="part")).base, 12000)

    def test_the_status_line_says_where_numbers_come_from(self):
        self.assertIn("Importing into project Rover (12000 to 12999)",
                      import_prepare.number_note(self.repo, self.proposal(project=self.rover)))
        self.assertIn("This vault's start number is 10001", import_prepare.number_note(self.repo, self.proposal()))

    def test_the_project_box_lists_no_project_then_each_project(self):
        self.assertEqual(import_table.project_choices([self.rover]),
                         {"No project": None, "Rover (12000 to 12999)": "Rover"})


class SavedScanImportedBefore(unittest.TestCase):
    def manifest(self):
        items = [manifest_module.Item(id=1, name="Bracket", files=[manifest_module.FileEntry("C:/old/bracket.SLDPRT")], pn="HCR-10001-001"),
                 manifest_module.Item(id=2, name="Plate", files=[manifest_module.FileEntry("C:/old/plate.SLDPRT")]),
                 manifest_module.Item(id=3, name="Bolt", files=[manifest_module.FileEntry("C:/old/bolt.SLDPRT")], include=False,
                                      already_imported_as="HCR-10009-001")]
        return SimpleNamespace(items=items)

    def test_items_numbered_by_an_earlier_import_are_marked_and_can_be_imported_again(self):
        found = self.manifest()
        marked = scan.mark_imported_items(found)
        self.assertEqual([item.id for item in marked], [1, 3])
        self.assertEqual(found.items[0].already_imported_as, "HCR-10001-001")
        again = scan.include_already_imported(found)
        self.assertEqual([(item.id, item.include, item.pn) for item in again], [(1, True, ""), (3, True, "")])
        self.assertEqual(len(manifest_module.pending_items(found)), 3)           # nothing is refused now

    def test_a_scan_nobody_imported_from_has_nothing_marked(self):
        found = self.manifest()
        found.items = found.items[1:2]
        self.assertEqual(scan.mark_imported_items(found), [])


if __name__ == "__main__":
    unittest.main()
