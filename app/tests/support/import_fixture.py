"""A pretend SolidWorks and an import fixture (a vault plus an old CAD folder), shared by the import, revise,
references and window tests."""

import os
import tempfile
from pathlib import Path

from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault, git

from litterbox.importing import import_finish
from litterbox.importing import import_journal
from litterbox.importing import manifest
from litterbox.importing import scan


class FakeSolidWorks:
    """Stands in for SolidWorks. A 'document' is text; each line 'ref: <path>' is one reference, and one copy of
    that component (a line 'suppressed: <path>' is a suppressed copy). `closed` makes it act as if SolidWorks
    isn't open."""

    def __init__(self, search_folder):
        self.search_folder = Path(search_folder)
        self.copied = []
        self.fail_on = None            # file name that makes copy() raise
        self.refuse_repoint = False
        self.closed = False

    @staticmethod
    def refs_in(path):
        with open(path, encoding="utf-8") as f:
            return [line[5:].strip() for line in f.read().splitlines() if line.startswith("ref: ")]

    def find(self, stored):
        if os.path.exists(stored):
            return stored
        hits = [p for p in self.search_folder.rglob("*") if p.is_file() and p.name.lower() == os.path.basename(stored).lower()]
        return str(hits[0]) if len(hits) == 1 else ""

    def references(self, path):
        if self.closed:
            raise RuntimeError("SolidWorks is not open.")
        stored = self.refs_in(path)
        return list(zip(stored, [self.find(s) for s in stored]))

    def components(self, path):
        if self.closed:
            raise RuntimeError("SolidWorks is not open.")
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        return [(self.find(line.split(": ", 1)[1].strip()), "counted" if line.startswith("ref: ") else "suppressed")
                for line in lines if line.startswith(("ref: ", "suppressed: "))]

    def copy(self, src, dst):
        if self.fail_on and os.path.basename(src) == self.fail_on:
            raise RuntimeError("simulated SolidWorks failure")
        with open(src, "rb") as f:
            data = f.read()
        with open(dst, "wb") as f:
            f.write(data)
        self.copied.append(dst)

    def repoint(self, file, old, new):
        if self.refuse_repoint:
            return False
        with open(file, encoding="utf-8") as f:
            text = f.read()
        if f"ref: {old}" not in text:
            return False
        with open(file, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.replace(f"ref: {old}", f"ref: {new}"))
        return True

    def version(self):
        return "32.1"

    def close(self):
        pass


@SKIP_ON_WINDOWS
class ImportFixture(TwoUserVault):
    """A vault, a pretend SolidWorks and an old CAD folder (top.SLDASM + drawing, sub.SLDASM, p1, p3). No tests here."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = self.tmp / "old cad"
        (self.src / "parts").mkdir(parents=True)
        self.write("parts/p1.SLDPRT", [])
        self.write("parts/p3.SLDPRT", [])
        self.write("sub.SLDASM", ["p3.SLDPRT", "p1.SLDPRT"])
        self.write("top.SLDASM", ["sub.SLDASM", "p1.SLDPRT"], stale={"sub.SLDASM": "/gone/folder/sub.SLDASM"})
        self.write("top.SLDDRW", ["top.SLDASM"])
        self.fake = FakeSolidWorks(self.src)
        self.manifest_path = self.tmp / "manifest.yaml"

    # -- helpers -----------------------------------------------------------
    def write(self, relative, refs, stale=None):
        path = self.src / relative
        lines = [f"model {relative}"]
        for ref in refs:
            target = (stale or {}).get(ref) or str(next(self.src.rglob(ref), self.src / ref))
            lines.append(f"ref: {target}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def make_manifest(self, repo=None):
        manifest.save(scan.scan([self.src], repo=repo or self.a), self.manifest_path)

    def originals(self):
        return {str(p): p.read_bytes() for p in self.src.rglob("*") if p.is_file()}

    def run_import(self, **kwargs):
        kwargs.setdefault("gap", 0)                    # numbers right at the lowest free one, to keep these tests simple
        kwargs.setdefault("backend", self.fake)
        kwargs.setdefault("log", lambda *_: None)
        return import_finish.run(self.a, self.manifest_path, **kwargs)

    def assert_clean(self, repo):
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-list", "--count", "@{u}..HEAD"), "0")

    def cad_names(self, repo=None):
        return sorted(p.name for p in ((repo or self.a) / "cad").iterdir())

    def assert_nothing_left(self):
        self.assertEqual(self.cad_names(), ["HCR-00001-001_A.SLDDRW", "HCR-00001-001_A.SLDPRT"])
        self.assertEqual(sorted(p.name for p in (self.a / "PN-logs").iterdir()), ["HCR-00001-001.yaml"])
        self.assert_clean(self.a)
        self.assertFalse((self.a / ".git" / import_journal.JOURNAL_NAME).exists())
