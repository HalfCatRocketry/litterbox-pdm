"""The import fixture with the helpers the import tests share. No tests here."""

from tests.support.vault_fixture import SKIP_ON_WINDOWS, git
from litterbox.importing import import_journal
from litterbox.importing import import_prepare
from tests.support.import_fixture import ImportFixture


@SKIP_ON_WINDOWS
class ImportFlowFixture(ImportFixture):
    def prepare(self, **kwargs):
        kwargs.setdefault("gap", 0)
        kwargs.setdefault("backend", self.fake)
        kwargs.setdefault("log", lambda *_: None)
        return import_prepare.prepare(self.a, self.manifest_path, **kwargs)

    def assert_nothing_left_but_import(self, result):
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertFalse((self.a / ".git" / import_journal.JOURNAL_NAME).exists())
