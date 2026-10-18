"""The two-user vault with the helpers the part-action tests share. No tests here."""

from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault, git
from litterbox.records import record_store
from litterbox.git import read_only


@SKIP_ON_WINDOWS
class EngineFixture(TwoUserVault):
    def put_revisions(self, base, working, released, revisions=("A", "B")):
        """Alex's copy: a part with files for several revisions, the record saying which is working/released."""
        pn = self.add_created_part(base)
        with self.user("Alex"):
            for rev in revisions:
                (self.a / f"cad/HCR-{base:05d}-001_{rev}.SLDPRT").write_bytes(f"rev {rev}".encode())
            record = record_store.load(self.a, pn)
            record.revision, record.released_revision = working, released
            if released == working:
                record.status = "released"
            path = self.a / f"PN-logs/HCR-{base:05d}-001.yaml"
            path.chmod(0o644)
            record_store.save(self.a, record)
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Set up revisions")
            git(self.a, "push")
            read_only.enforce_read_only(self.a)
        return pn
