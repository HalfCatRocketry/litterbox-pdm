"""Tests for gui/logic/solidworks_text.py: which files are open or unsaved in SolidWorks, and what is said about it."""

import unittest

from litterbox.cad import open_documents
from litterbox.cad.open_documents import OpenDocument
from litterbox.gui.logic import solidworks_text

REPO = "C:/vault"
PRT, DRW, ASM = "cad/HCR-00001-001_A.SLDPRT", "cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00002-001_A.SLDASM"


def snapshot(*docs):
    return {open_documents.key(f"{REPO}/{rel}"): OpenDocument(f"{REPO}/{rel}", unsaved, False, True)
            for rel, unsaved in docs}


class Text(unittest.TestCase):
    def test_which_files_are_open_and_unsaved(self):
        snap = snapshot((PRT, True), (ASM, False))
        self.assertEqual(solidworks_text.open_among(snap, REPO, [PRT, DRW, ASM]), sorted([PRT, ASM]))
        self.assertEqual(solidworks_text.unsaved_among(snap, REPO, [PRT, DRW, ASM]), [PRT])
        self.assertEqual(solidworks_text.unsaved_among({}, REPO, [PRT]), [])

    def test_the_questions_name_the_files(self):
        self.assertIn("HCR-00001-001_A.SLDPRT", solidworks_text.save_first_question([PRT]))
        self.assertIn("Check in anyway", solidworks_text.save_first_question([PRT]))
        self.assertIn("Save progress anyway", solidworks_text.save_first_question([PRT], "save progress"))
        self.assertIn("Get the latest anyway", solidworks_text.may_be_replaced_question([ASM]))
        self.assertIn("close and reopen", solidworks_text.reopen_note([ASM]).lower())
        many = [f"cad/HCR-{n:05d}-001_A.SLDPRT" for n in range(20)]
        self.assertIn("...and 8 more", solidworks_text.save_first_question(many))

    def test_a_queued_part_opened_or_saved_is_warned_about(self):
        snap = snapshot((PRT, False))
        opened = open_documents.differences({}, snap)
        saved = open_documents.differences(snapshot((PRT, True)), snap)
        busy = {"HCR-00001-001": "Checking in 1 part"}
        files = {"HCR-00001-001": [PRT, DRW]}.get
        notes = solidworks_text.queued_part_notes(opened, REPO, busy, lambda pn: files(pn, []))
        self.assertEqual(len(notes), 1)
        self.assertIn("was opened in SolidWorks while Litterbox is still working on HCR-00001-001", notes[0])
        self.assertIn("was saved", solidworks_text.queued_part_notes(saved, REPO, busy, lambda pn: files(pn, []))[0])

    def test_other_parts_and_other_changes_are_not_warned_about(self):
        opened_other = open_documents.differences({}, snapshot((ASM, False)))
        busy = {"HCR-00001-001": "Checking in 1 part"}
        self.assertEqual(solidworks_text.queued_part_notes(opened_other, REPO, busy, lambda pn: [PRT]), [])
        closed = open_documents.differences(snapshot((PRT, False)), {})
        self.assertEqual(solidworks_text.queued_part_notes(closed, REPO, busy, lambda pn: [PRT]), [])


if __name__ == "__main__":
    unittest.main()
