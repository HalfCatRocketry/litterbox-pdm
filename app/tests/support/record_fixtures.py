"""Old records to test record upgrades on (tests/records/fixtures/), and two made-up upgrade steps. No tests here.

The fixtures are records as older Litterbox versions wrote them, laid out as in a vault (PN-logs/, DOC-logs/):
HCR-00001-001 from before records had a format number or parts had a name, a released-then-revised part with
purchasing, exports, materials and a field no Litterbox knows (HCR-00002-001), a released assembly with references,
quantities and a workflow with an ECO (HCR-00003-500), a kit with BOM lines and a linked document (HCR-00004-500), a
part with a rejected request (HCR-00005-001), and a document (PROP-0001). Add a record here whenever a release writes
a shape none of these has.

pretend_steps(test) gives Litterbox two upgrade steps for one test, so the upgrade can be tested before it has real
ones: format 1 to 2 renames `custom_note` to `notes`, and 2 to 3 marks every record `checked: true`.
"""

import shutil
from pathlib import Path

import yaml

from litterbox.core import part_number
from litterbox.records import record_migrations

FIXTURES = Path(__file__).resolve().parents[1] / "records" / "fixtures"


def fixture_paths():
    return sorted(FIXTURES.rglob("*.yaml"))


def fixture_data():
    """{file name: the record as YAML gives it}."""
    return {path.name: yaml.safe_load(path.read_text(encoding="utf-8")) for path in fixture_paths()}


def copy_into(repo):
    """Put every fixture in a vault folder (PN-logs/, DOC-logs/)."""
    shutil.copytree(FIXTURES, repo, dirs_exist_ok=True)


def use_five_digits(test):
    """The fixtures' part numbers have 5-digit bases, as a vault with no digit setting does."""
    saved = (part_number.BASE_DIGITS, part_number.VARIANT_DIGITS)
    part_number.configure(5, 3)
    test.addCleanup(part_number.configure, *saved)


def _rename_note(data):
    if "custom_note" in data:
        data["notes"] = data.pop("custom_note")
    return data


def _mark_checked(data):
    data["checked"] = True
    return data


STEP_1 = record_migrations.Step("0.4.0", "Notes get their own name", _rename_note)
STEP_2 = record_migrations.Step("0.5.0", "Every record is marked checked", _mark_checked)


def pretend_steps(test, steps=None):
    """Give record_migrations these steps (STEP_1 and STEP_2 if none) until the test ends; the vault's minimum starts
    empty, so records can't be written until a test says otherwise (vault_requires)."""
    saved_steps = dict(record_migrations.STEPS)
    saved_readers = (record_migrations.READ_MINIMUM, record_migrations.READ_LATEST_MINIMUM)
    record_migrations.STEPS.clear()
    record_migrations.STEPS.update(steps if steps is not None else {1: STEP_1, 2: STEP_2})
    vault_requires("")

    def restore():
        record_migrations.STEPS.clear()
        record_migrations.STEPS.update(saved_steps)
        record_migrations.configure(*saved_readers)
    test.addCleanup(restore)


def vault_requires(minimum):
    """As if the vault's min_litterbox_version were `minimum`, on disk and on its server (without a vault: see
    vault/config.apply)."""
    record_migrations.configure(lambda: minimum, lambda: minimum)
