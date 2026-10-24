"""Tests for configurations in a real vault: Check In names a lone "Default" configuration after the part (and again
when the Name changes), keeps what it read in the record and warns about a deleted configuration an assembly uses;
Create Variant copies a part to a new variant, checked out. A fake SolidWorks stands in (it "saves" a renamed file by
changing its bytes), so these run without it (and need Linux, macOS or WSL, as git tests do)."""

import shutil
import unittest

from tests.parts.test_configurations import FakeConfigurations
from tests.support.vault_fixture import DRW, PART, PRT
from tests.support.workflow_fixture import Fixture

from litterbox.core.part_number import PN
from litterbox.git import lfs_locks
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import configuration_naming
from litterbox.parts import create_variant
from litterbox.parts import part_details
from litterbox.records import record_configurations
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.references import reference_reader

ASM = PN("HCR", 3, 500)
SLDASM = "cad/HCR-00003-500_A.SLDASM"


class SavingSolidWorks(FakeConfigurations):
    """Renaming changes the file, as saving it in SolidWorks would; copying copies it."""

    def name_configuration(self, path, old, new):
        super().name_configuration(path, old, new)
        with open(path, "ab") as f:
            f.write(f" config={new}".encode())

    def copy(self, src, dst):
        shutil.copyfile(src, dst)

    uses_files = ()                     # what an assembly's references() gives: these files, where they are

    def references(self, path):
        return [(str(f), str(f)) for f in self.uses_files]

    def repoint(self, file, old, new):
        return True

    def material(self, path):
        return "Steel"


class CheckIn(Fixture, unittest.TestCase):
    def check_in(self, backend, change=b"version 2", pn=PART, path=PRT):
        repo = self.repo_of("Alex")
        self.do("Alex", checkout.checkout, pn)
        if change:
            (repo / path).write_bytes(change)
        return self.do("Alex", checkin.checkin, pn, "Update", references_reader=reference_reader.make_reader(backend),
                       configuration_namer=configuration_naming.make_namer(backend))

    def test_default_is_named_after_the_part_and_goes_up_with_the_check_in(self):
        backend = SavingSolidWorks()
        self.check_in(backend)
        record = record_store.load(self.a, PART)
        self.assertEqual(record_configurations.names(record), ["Front upright"])
        self.assertEqual(record_configurations.named(record), "Front upright")
        self.assertIn(b"config=Front upright", (self.a / PRT).read_bytes())
        self.assertEqual(self.status_of(self.a).kind, "ok")                     # uploaded, nothing left over

    def test_a_new_name_alone_renames_the_configuration(self):
        backend = SavingSolidWorks()
        self.check_in(backend)
        self.do("Alex", checkout.checkout, PART)
        self.do("Alex", part_details.edit_details, PART, "Front upright, left", "")
        self.do("Alex", checkin.checkin, PART, "Renamed", references_reader=reference_reader.make_reader(backend),
                configuration_namer=configuration_naming.make_namer(backend))
        record = record_store.load(self.a, PART)
        self.assertEqual(record_configurations.names(record), ["Front upright, left"])
        self.assertIn(b"config=Front upright, left", (self.a / PRT).read_bytes())
        self.assertIn("HCR-00001-001: Renamed", self.remote_log())

    def test_a_deleted_configuration_an_assembly_uses_is_a_warning(self):
        two = [{"name": "Default", "id": 0}, {"name": "Long", "id": 1}]
        self.check_in(SavingSolidWorks(own={"HCR-00001-001_A.SLDPRT": [dict(c) for c in two]}))
        (self.a / SLDASM).write_bytes(b"assembly 1")
        record_store.create_record(self.a, ASM, "Frame", "Alex")
        checkin_new_assembly(self.a)
        assembly = SavingSolidWorks(own={"HCR-00003-500_A.SLDASM": [{"name": "Frame", "id": 0}]},
                                    used={str(self.a / PRT): ["Long"]})
        assembly.uses_files = [self.a / PRT]
        self.check_in(assembly, change=b"assembly 2", pn=ASM, path=SLDASM)
        self.assertEqual(record_configurations.uses(record_store.load(self.a, ASM)), {"HCR-00001-001_A": ["Long"]})
        result = self.check_in(SavingSolidWorks(own={"HCR-00001-001_A.SLDPRT": [two[0]]}), change=b"version 3")
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("no longer has the configuration 'Long' that HCR-00003-500 Rev A uses", result.warnings[0])


def checkin_new_assembly(repo):
    """Upload an assembly made by hand (its record and file), as an import would."""
    from tests.support.vault_fixture import git
    git(repo, "add", ".")
    git(repo, "commit", "-m", "An assembly")
    git(repo, "push")


class CreateVariant(Fixture, unittest.TestCase):
    def test_a_copy_as_a_new_variant_checked_out(self):
        backend = SavingSolidWorks()
        new_pn, files = self.do("Alex", create_variant.create_variant, PART, backend=backend,
                                log=lambda text: None)
        self.assertEqual(new_pn, PN("HCR", 1, 2))
        self.assertEqual(sorted(files), ["cad/HCR-00001-002_A.SLDDRW", "cad/HCR-00001-002_A.SLDPRT"])
        self.assertEqual((self.a / "cad/HCR-00001-002_A.SLDPRT").read_bytes()[:9], b"version 1")
        record = record_store.load(self.a, new_pn)
        self.assertEqual((record.name, record.revision), ("Front upright", "A"))
        self.assertEqual(record.history[-1]["event"], record_model.EVENT_COPIED_FROM)
        self.assertEqual(record.history[-1]["source"], "HCR-00001-001 Rev A")
        with self.user("Alex"):
            locks = lfs_locks.get_locks(self.a, strict=True)
        self.assertEqual([path for path in files + ["PN-logs/HCR-00001-002.yaml"] if not lfs_locks.is_mine(locks, path)],
                         [], locks)
        with self.user("Alex"):
            self.assertEqual(self.status_of(self.a, new_pn).kind, "mine")
        self.assertIn("HCR-00001-002: Copied from HCR-00001-001 Rev A", self.remote_log())

    def test_a_new_name_names_the_copys_configuration(self):
        new_pn, _files = self.do("Alex", create_variant.create_variant, PART, name="Rear upright",
                                 variant=7, backend=SavingSolidWorks(), log=lambda text: None)
        self.assertEqual(new_pn, PN("HCR", 1, 7))
        record = record_store.load(self.a, new_pn)
        self.assertEqual((record.name, record_configurations.named(record)), ("Rear upright", "Rear upright"))
        self.assertIn(b"config=Rear upright", (self.a / "cad/HCR-00001-007_A.SLDPRT").read_bytes())


if __name__ == "__main__":
    unittest.main()
