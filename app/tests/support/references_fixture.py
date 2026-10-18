"""A vault with an assembly that uses a part, for the reference tests. No tests here."""

from tests.support.import_fixture import FakeSolidWorks
from tests.support.vault_fixture import DRW, PART, PRT, SKIP_ON_WINDOWS, TwoUserVault, git
from litterbox.references import reference_queries
from litterbox.references import reference_reader
from litterbox.references import reference_replace
from litterbox.records import record_store
from litterbox.parts import revise
from litterbox.core.part_number import PN
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.git import lfs_locks
from litterbox.parts import lifecycle
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
            checkin.checkin(self.a, ASM, "First version", references_reader=reference_reader.make_reader(self.fake))
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
            items = reference_replace.replacements_from(reference_queries.uses(repo, pn))
            return reference_replace.replace_references(repo, items, backend=self.fake, log=self.log.append)
