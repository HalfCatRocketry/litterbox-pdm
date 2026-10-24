"""Tests for configurations without git or SolidWorks: naming the only configuration after the part
(core/configuration_names.py, parts/configuration_naming.py), the record's `configurations`
(records/record_configurations.py), reading them (references/reference_reader.py), the check-in warnings
(parts/configuration_check.py), and the Details tab's line. tests/parts/test_configuration_flow.py tries them in a
real vault."""

import unittest

from litterbox.core import configuration_names
from litterbox.core.part_number import PN
from litterbox.gui.logic import part_details_text
from litterbox.parts import configuration_check
from litterbox.parts import configuration_naming
from litterbox.records import record_configurations
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_revisions
from litterbox.records import record_store
from litterbox.references import reference_reader
from tests.support.registry_case import RegistryTestCase

PART_PN, ASM_PN = PN("HCR", 1, 1), PN("HCR", 3, 500)
PART_FILES = ["cad/HCR-00001-001_A.SLDPRT", "cad/HCR-00001-001_A.SLDDRW"]
ASM_FILES = ["cad/HCR-00003-500_A.SLDASM"]
TWO = [{"name": "Default", "id": 0}, {"name": "Long", "id": 1}]


class FakeConfigurations:
    """A SolidWorks that reads and renames configurations: `own` by file name, components' configurations for an
    assembly, and every rename asked for."""

    def __init__(self, own=None, used=None, materials=None, linked=(), refuse=None):
        self.own = own or {}
        self.used, self.materials, self.linked, self.refuse = used or {}, materials or {}, list(linked), refuse
        self.renamed, self.read = [], []

    @staticmethod
    def name(path):
        return str(path).replace("\\", "/").rsplit("/", 1)[-1]

    def configurations(self, path):
        own = self.own.get(self.name(path), [{"name": "Default", "id": 0}])
        self.read.append(self.name(path))
        return {"own": own, "active": own[0]["name"], "linked": self.linked,
                "materials": {c["name"]: self.materials.get(c["name"], "Steel") for c in own}}

    def component_configurations(self, path):
        return dict(self.used)

    def name_configuration(self, path, old, new):
        if self.refuse:
            raise RuntimeError(self.refuse)
        self.renamed.append((self.name(path), old, new))
        own = self.own.setdefault(self.name(path), [{"name": old, "id": 0}])
        for c in own:
            if c["name"] == old:
                c["name"] = new

    def close(self):
        pass


def record(pn=PART_PN, name="Bracket", **fields):
    return record_model.Record(pn, name, "Alex", "2026-10-24T10:00:00Z", **fields)


class Names(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(configuration_names.clean("  Bracket, 2in / long  "), "Bracket, 2in - long")
        self.assertEqual(configuration_names.clean("Nut @ M6"), "Nut - M6")
        self.assertEqual(configuration_names.clean("x" * 300), "x" * configuration_names.MAX_LENGTH)
        self.assertEqual(configuration_names.clean(" / "), "-")
        self.assertEqual(configuration_names.clean(""), "")

    def test_only_a_lone_default_or_the_name_litterbox_gave(self):
        rename = configuration_names.rename
        self.assertEqual(rename(["Default"], "", "Bracket"), ("Default", "Bracket"))
        self.assertIsNone(rename(["Default", "Long"], "", "Bracket"))          # configurations of their own
        self.assertIsNone(rename(["Short"], "", "Bracket"))                    # named by someone else
        self.assertEqual(rename(["Bracket"], "Bracket", "Bracket, left"), ("Bracket", "Bracket, left"))
        self.assertIsNone(rename(["Bracket"], "Bracket", "Bracket"))           # already right
        self.assertIsNone(rename(["Default"], "", "  "))                       # nothing to call it
        self.assertIsNone(rename([], "", "Bracket"))


class Record(unittest.TestCase):
    def test_written_and_read_back(self):
        r = record()
        record_configurations.set_configurations(r, TWO, {"HCR-00002-001_A": ["Short", "Long", "Short"]})
        record_configurations.set_named(r, "Default")
        again = record_model.Record.from_dict(record_model.yaml.safe_load(record_model.dump(r)))
        self.assertEqual(record_configurations.names(again), ["Default", "Long"])
        self.assertEqual(record_configurations.uses(again), {"HCR-00002-001_A": ["Long", "Short"]})
        self.assertEqual(record_configurations.named(again), "Default")
        for bad in ({"A": "lots"}, {"A": {"own": [{"id": 3}]}}, {"A": {"uses": ["x"]}}, ["A"]):
            with self.assertRaises(record_model.RegistryError):
                record_model.Record.from_dict(dict(r.to_dict(), configurations=bad))

    def test_the_name_given_is_kept_while_that_configuration_is_there(self):
        r = record()
        record_configurations.set_configurations(r, [{"name": "Bracket", "id": 0}])
        record_configurations.set_named(r, "Bracket")
        self.assertFalse(record_configurations.set_configurations(r, [{"name": "Bracket", "id": 0}]))
        record_configurations.set_configurations(r, [{"name": "Other", "id": 0}])
        self.assertEqual(record_configurations.named(r), "")

    def test_check_in_keeps_or_forgets_and_forgetting_keeps_the_name_given(self):
        r = record()
        record_lifecycle.record_checkin(r, "Alex", PART_FILES, configurations=([{"name": "Bracket", "id": 0}], {}))
        record_configurations.set_named(r, "Bracket")
        record_lifecycle.record_checkin(r, "Alex", PART_FILES)                  # no SolidWorks to read it
        self.assertEqual((record_configurations.names(r), record_configurations.named(r)), ([], "Bracket"))
        record_lifecycle.record_checkin(r, "Alex", ["cad/HCR-00001-001_A.SLDDRW"])   # a drawing: nothing to forget
        self.assertEqual(record_configurations.named(r), "Bracket")

    def test_revise_carries_them_on_and_cancel_drops_them(self):
        r = record(status=record_model.STATUS_RELEASED, released_revision="A")
        record_configurations.set_configurations(r, TWO)
        record_revisions.mark_revised(r, "Alex", "Longer", [])
        self.assertEqual(record_configurations.names(r, "B"), ["Default", "Long"])
        record_revisions.mark_revision_cancelled(r, "Alex", "No", [])
        self.assertNotIn("B", r.configurations)

    def test_the_details_line_only_for_several(self):
        r = record()
        self.assertEqual(part_details_text.configurations_text(r, "A"), "")
        record_configurations.set_configurations(r, [{"name": "Bracket", "id": 0}])
        self.assertEqual(part_details_text.configurations_text(r, "A"), "")
        record_configurations.set_configurations(r, TWO)
        self.assertEqual(part_details_text.configurations_text(r, "A"),
                         "2: Default, Long. They are all released together")


class Reading(unittest.TestCase):
    def test_a_part_and_an_assemblys_configurations(self):
        backend = FakeConfigurations(own={"HCR-00003-500_A.SLDASM": [{"name": "Default", "id": 0}]},
                                     used={"C:/v/cad/HCR-00001-001_A.SLDPRT": ["Long"],
                                           "C:/SOLIDWORKS Data/screw.sldprt": ["M6"],
                                           "C:/v/cad/HCR-00003-500_A.SLDASM": ["Default"]})
        (own, used), details = reference_reader.read_configurations("C:/v", ASM_PN, "A", backend, ASM_FILES)
        self.assertEqual((own, used), ([{"name": "Default", "id": 0}], {"HCR-00001-001_A": ["Long"]}))
        self.assertEqual(details["active"], "Default")
        self.assertIsNone(reference_reader.read_configurations("C:/v", ASM_PN, "A", backend, []))
        self.assertIsNone(reference_reader.read_configurations("C:/v", ASM_PN, "A", object(), ASM_FILES))
        found = reference_reader.make_reader(backend)("C:/v", PART_PN, "A", PART_FILES)
        self.assertEqual(found.configurations, ([{"name": "Default", "id": 0}], {}))

    def test_the_model_file(self):
        self.assertEqual(reference_reader.model_file("C:/v", ASM_PN, "A", ASM_FILES + PART_FILES), ASM_FILES[0])
        self.assertEqual(reference_reader.model_file("C:/v", PART_PN, "A", PART_FILES), PART_FILES[0])
        self.assertIsNone(reference_reader.model_file("C:/v", PART_PN, "A", ["cad/HCR-00001-001_A.SLDDRW"]))


class Naming(RegistryTestCase):
    def setUp(self):
        super().setUp()
        (self.repo / "cad").mkdir()
        (self.repo / PART_FILES[0]).write_bytes(b"part")

    def test_a_lone_default_is_named_after_the_part(self):
        backend = FakeConfigurations()
        r = self.make(1, name="Bracket")
        self.assertEqual(configuration_naming.make_namer(backend)(self.repo, r, PART_FILES), "Bracket")
        self.assertEqual(backend.renamed, [("HCR-00001-001_A.SLDPRT", "Default", "Bracket")])

    def test_a_new_name_renames_what_litterbox_named(self):
        backend = FakeConfigurations(own={"HCR-00001-001_A.SLDPRT": [{"name": "Bracket", "id": 0}]})
        r = self.make(1, name="Bracket, left")
        record_configurations.set_configurations(r, [{"name": "Bracket", "id": 0}])
        record_configurations.set_named(r, "Bracket")
        self.assertEqual(configuration_naming.make_namer(backend)(self.repo, r, PART_FILES), "Bracket, left")

    def test_nothing_to_do_means_the_file_isnt_opened(self):
        backend = FakeConfigurations()
        r = self.make(1, name="Bracket")
        record_configurations.set_configurations(r, TWO)
        self.assertIsNone(configuration_naming.make_namer(backend)(self.repo, r, PART_FILES))
        self.assertEqual(backend.read, [])
        cots = self.make(2, cots=True)
        self.assertIsNone(configuration_naming.make_namer(backend)(self.repo, cots, PART_FILES))

    def test_a_refusal_is_logged_and_the_check_in_goes_on(self):
        logged = []
        namer = configuration_naming.make_namer(FakeConfigurations(refuse="it has unsaved changes"), logged.append)
        self.assertIsNone(namer(self.repo, self.make(1), PART_FILES))
        self.assertIn("unsaved changes", logged[0])


class Warnings(RegistryTestCase):
    def setUp(self):
        super().setUp()
        self.part = self.make(1, name="Bracket")
        self.asm = self.make(3, variant=500, name="Frame")
        self.asm.references["A"] = ["HCR-00001-001_A"]
        record_configurations.set_configurations(self.asm, [{"name": "Default", "id": 0}],
                                                 {"HCR-00001-001_A": ["Long"]})
        record_store.save(self.repo, self.asm)

    def read(self, own, **details):
        return reference_reader.AssemblyRead(configurations=(own, {}), configuration_details=details)

    def test_a_deleted_configuration_an_assembly_uses(self):
        self.assertEqual(configuration_check.deleted_names(TWO, [TWO[0]]), ["Long"])
        self.assertEqual(configuration_check.deleted_names(TWO, [{"name": "Longer", "id": 1}, TWO[0]]), [])
        found = configuration_check.warnings(self.repo, PART_PN, "A", TWO, self.read([TWO[0]]))
        self.assertEqual(len(found), 1)
        self.assertIn("no longer has the configuration 'Long' that HCR-00003-500 Rev A uses", found[0])
        renamed = [TWO[0], {"name": "Longer", "id": 1}]
        self.assertEqual(configuration_check.warnings(self.repo, PART_PN, "A", TWO, self.read(renamed)), [])
        self.assertEqual(configuration_check.warnings(self.repo, PART_PN, "A", TWO, None), [])

    def test_materials_and_linked_files(self):
        found = configuration_check.warnings(self.repo, PART_PN, "A", TWO, self.read(
            TWO, active="Default", materials={"Default": "Steel", "Long": "1060 Alloy"}, linked=["C:/t/sizes.xlsx"]))
        self.assertIn("different materials (Default: Steel; Long: 1060 Alloy)", found[0])
        self.assertIn("(Default: Steel)", found[0])
        self.assertIn("linked to C:/t/sizes.xlsx", found[1])
        same = self.read(TWO, materials={"Default": "Steel", "Long": "Steel"})
        self.assertEqual(configuration_check.warnings(self.repo, PART_PN, "A", TWO, same), [])

    def test_update_references_to_a_revision_without_the_configuration(self):
        record_configurations.set_configurations(self.part, TWO, revision="A")
        record_configurations.set_configurations(self.part, [TWO[0]], revision="B")
        self.assertEqual(configuration_check.missing_after_update(self.part, "A", "B", ["Long"]), ["Long"])
        record_configurations.set_configurations(self.part, [TWO[0], {"name": "Longer", "id": 1}], revision="B")
        self.assertEqual(configuration_check.missing_after_update(self.part, "A", "B", ["Long"]), [])
        self.assertEqual(configuration_check.missing_after_update(self.part, "A", "C", ["Long"]), [])


if __name__ == "__main__":
    unittest.main()
