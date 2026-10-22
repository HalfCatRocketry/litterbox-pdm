"""Tests for parts' materials: the record's `materials` (no git), what SolidWorks gives (no SolidWorks), the words,
and reading them at check-in and with Update Material against real git repos with a fake git-lfs (skipped on
Windows unless LITTERBOX_GIT_TESTS=1)."""

import unittest
from types import SimpleNamespace

from litterbox.cad.solidworks import sw_backend
from litterbox.core.part_number import PN
from litterbox.gui.logic import list_columns
from litterbox.gui.logic import material_text
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import part_materials
from litterbox.records import record_lifecycle
from litterbox.records import record_materials
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.references import reference_reader
from tests.support.vault_fixture import PART, PRT, SKIP_ON_WINDOWS, TwoUserVault, git

FILES = ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]


def record(**fields):
    return record_model.Record(PN("HCR", 1, 1), "Bracket", "Alex", "2026-10-22T10:00:00Z", **fields)


class FakeMaterials:
    """A SolidWorks that only reads materials: `found` by file name, or raises for `broken` ones."""

    def __init__(self, name="6061-T6 (SS)", broken=False):
        self.name, self.broken, self.asked, self.closed = name, broken, [], False

    def material(self, path):
        self.asked.append(path.replace("\\", "/").rsplit("/", 1)[-1])
        if self.broken:
            raise RuntimeError("SolidWorks is not open.")
        return self.name

    def close(self):
        self.closed = True


class Record(unittest.TestCase):
    def test_kept_per_revision_and_written_back(self):
        r = record()
        self.assertTrue(record_lifecycle.material_needs_update(r, "A", FILES))
        self.assertTrue(record_materials.set_material(r, "  Chrome   Stainless Steel "))
        self.assertFalse(record_materials.set_material(r, "Chrome Stainless Steel"))
        record_materials.set_material(r, "", "B")                       # read: none assigned
        again = record_model.Record.from_dict(record_model.yaml.safe_load(record_model.dump(r)))
        self.assertEqual(again.materials, {"A": "Chrome Stainless Steel", "B": ""})
        self.assertFalse(record_lifecycle.material_needs_update(again, "A", FILES))
        self.assertFalse(record_lifecycle.material_needs_update(again, "A", ["cad/HCR-00001-001_A.SLDASM"]))
        with self.assertRaises(record_model.RegistryError):
            record_model.Record.from_dict(dict(again.to_dict(), materials={"A": ["not", "text"]}))

    def test_check_in_keeps_what_was_read_or_forgets_it(self):
        r = record()
        event = record_lifecycle.record_checkin(r, "Alex", FILES, material="Steel")
        self.assertEqual((r.materials, event["material"]), ({"A": "Steel"}, "Steel"))
        self.assertNotIn("material", record_lifecycle.record_checkin(r, "Alex", FILES, material="Steel"))
        record_lifecycle.record_checkin(r, "Alex", FILES)               # changed without SolidWorks to read it
        self.assertTrue(record_lifecycle.material_needs_update(r, "A", FILES))
        record_lifecycle.record_checkin(r, "Alex", ["cad/HCR-00001-001_A.SLDDRW"], material=None)
        noncad = record(kind=record_model.KIND_NONCAD)
        self.assertFalse(record_lifecycle.material_needs_update(noncad, "A", FILES))

    def test_what_solidworks_gives(self):
        self.assertEqual(sw_backend.material_name("Chrome Stainless Steel", ""), "Chrome Stainless Steel")
        self.assertEqual(sw_backend.material_name("", "SOLIDWORKS Materials|Chrome Stainless Steel|7"),
                         "Chrome Stainless Steel")
        self.assertEqual(sw_backend.material_name("", "Steel"), "Steel")         # parts from much older versions
        self.assertEqual(sw_backend.material_name(None, None), "")


class Reading(unittest.TestCase):
    def test_check_in_reads_a_changed_part_and_leaves_drawings_alone(self):
        backend = FakeMaterials()
        reader = reference_reader.make_reader(backend)
        found = reader("C:/vault", PART, "A", FILES)
        self.assertEqual((found.material, found.references, backend.asked), ("6061-T6 (SS)", None,
                                                                             ["HCR-00001-001_A.SLDPRT"]))
        self.assertIsNone(reader("C:/vault", PART, "A", ["cad/HCR-00001-001_A.SLDDRW"]))
        logged = []
        self.assertIsNone(reference_reader.make_reader(FakeMaterials(broken=True), logged.append)(
            "C:/vault", PART, "A", FILES))
        self.assertIn("Update Material", logged[0])


class Words(unittest.TestCase):
    def test_column_details_and_summary(self):
        row = SimpleNamespace(material="Steel", material_outdated=False)
        column = next(c for c in list_columns.COLUMNS if c.key == "material")
        self.assertEqual((column.text(row), column.shown), ("Steel", False))            # in View > Columns, off
        self.assertEqual(material_text.column_text(SimpleNamespace(material="", material_outdated=True)),
                         material_text.NOT_READ)
        r = record()
        self.assertIn("Update Material", material_text.details_text(r, "A", FILES))
        self.assertIsNone(material_text.details_text(r, "A", ["cad/HCR-00001-001_A.SLDASM"]))
        record_materials.set_material(r, "")
        self.assertEqual(material_text.details_text(r, "A", FILES), "None assigned in SolidWorks")
        text, problems = material_text.summary({PART: part_materials.UPDATED, PN("HCR", 2, 1): part_materials.LOCAL,
                                                PN("HCR", 3, 1): "skipped: checked out by Bea"})
        self.assertIn("Updated the material of 2 parts", text)
        self.assertEqual(problems, ["HCR-00003-001: checked out by Bea"])


@SKIP_ON_WINDOWS
class Flow(TwoUserVault, unittest.TestCase):
    def test_check_in_with_solidworks_open_keeps_the_material(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_text("a new model\n")
            checkin.checkin(self.a, PART, "Thicker", references_reader=reference_reader.make_reader(FakeMaterials()))
            self.assertEqual(record_store.load(self.a, PART).materials, {"A": "6061-T6 (SS)"})
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_text("again, with SolidWorks closed\n")
            checkin.checkin(self.a, PART, "Thinner",
                            references_reader=reference_reader.make_reader(FakeMaterials(broken=True)))
            self.assertTrue(record_lifecycle.material_needs_update(record_store.load(self.a, PART), "A", FILES))

    def test_update_material_uploads_skips_others_checkouts_and_keeps_yours_local(self):
        with self.user("Alex"):
            backend = FakeMaterials("Steel")
            self.assertEqual(part_materials.update_materials(self.a, [PART], backend, log=lambda line: None),
                             {PART: part_materials.UPDATED})
            self.assertIn("HCR-00001-001: Material updated", git(self.a, "log", "--format=%s", "origin/main"))
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(part_materials.update_materials(self.a, [PART], backend, log=lambda line: None),
                             {PART: part_materials.UNCHANGED})
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(record_store.load(self.b, PART).materials, {"A": "Steel"})
            checkout.checkout(self.b, PART)
            result = part_materials.update_materials(self.b, [PART], FakeMaterials("Brass"), log=lambda line: None)
            self.assertEqual(result, {PART: part_materials.LOCAL})                  # hers: in her copy
            self.assertEqual(record_store.load(self.b, PART).materials, {"A": "Brass"})
        with self.user("Alex"):
            get_latest.get_latest(self.a)
            result = part_materials.update_materials(self.a, [PART], FakeMaterials("Brass"), log=lambda line: None)
            self.assertIn("checked out by", result[PART])

    def locks(self, repo):
        from litterbox.git import lfs_locks
        return lfs_locks.get_locks(repo, strict=True)


if __name__ == "__main__":
    unittest.main()
