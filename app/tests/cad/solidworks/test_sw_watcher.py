"""
Tests for cad/solidworks/sw_documents.py and sw_watcher.py with a pretend SolidWorks. (The real one can only be
tried on Windows with SolidWorks installed.)
"""

import threading
import time
import unittest
from unittest import mock

from litterbox import diagnostics
from litterbox.cad.solidworks import sw_documents
from litterbox.cad.solidworks import sw_watcher
from litterbox.cad.solidworks.sw_documents import OpenDocument


class FakeDoc:
    """A SolidWorks document (ModelDoc2): some members are methods, Visible is a property, as through COM."""

    def __init__(self, path, unsaved=False, read_only=False, visible=True):
        self.path, self.unsaved, self.read_only, self.Visible = path, unsaved, read_only, visible
        self.next = None

    def GetPathName(self):
        return self.path

    def GetSaveFlag(self):
        return self.unsaved

    def IsOpenedReadOnly(self):
        return self.read_only

    def GetNext(self):
        return self.next


class FakeSolidWorks:
    def __init__(self, *docs):
        self.docs = list(docs)
        for a, b in zip(self.docs, self.docs[1:]):
            a.next = b

    def GetFirstDocument(self):
        return self.docs[0] if self.docs else None


def doc(path, **kw):
    return OpenDocument(path, kw.get("unsaved", False), kw.get("read_only", False), kw.get("visible", True))


class Documents(unittest.TestCase):
    def test_every_open_document_with_its_state(self):
        sw = FakeSolidWorks(FakeDoc("C:/vault/cad/A.SLDPRT", unsaved=True),
                            FakeDoc("C:/vault/cad/B.SLDASM", read_only=True, visible=False),
                            FakeDoc(""))                                        # new, never saved: left out
        found = sw_documents.open_documents(sw)
        self.assertEqual(sorted(d.path for d in found.values()), ["C:/vault/cad/A.SLDPRT", "C:/vault/cad/B.SLDASM"])
        a = found[sw_documents.key("C:/vault/cad/A.SLDPRT")]
        b = found[sw_documents.key("C:/vault/cad/B.SLDASM")]
        self.assertEqual((a.unsaved, a.read_only, a.visible), (True, False, True))
        self.assertEqual((b.unsaved, b.read_only, b.visible), (False, True, False))

    def test_nothing_open(self):
        self.assertEqual(sw_documents.open_documents(FakeSolidWorks()), {})

    def test_paths_compare_the_way_windows_does(self):
        self.assertEqual(sw_documents.key("C:/vault/cad/../cad/A.SLDPRT"), sw_documents.key("C:/vault/cad/A.SLDPRT"))


class Differences(unittest.TestCase):
    def test_opened_closed_modified_saved(self):
        a, b, c = "C:/v/a.SLDPRT", "C:/v/b.SLDPRT", "C:/v/c.SLDPRT"
        old = {sw_documents.key(a): doc(a), sw_documents.key(b): doc(b), sw_documents.key(c): doc(c, unsaved=True)}
        new = {sw_documents.key(b): doc(b, unsaved=True), sw_documents.key(c): doc(c),
               sw_documents.key("C:/v/d.SLDPRT"): doc("C:/v/d.SLDPRT")}
        found = {(ch.what, ch.document.path) for ch in sw_watcher.differences(old, new)}
        self.assertEqual(found, {("closed", a), ("has unsaved changes", b), ("saved", c), ("opened", "C:/v/d.SLDPRT")})

    def test_no_change(self):
        snapshot = {sw_documents.key("C:/v/a"): doc("C:/v/a")}
        self.assertEqual(sw_watcher.differences(snapshot, dict(snapshot)), [])


class Watcher(unittest.TestCase):
    def setUp(self):
        self.lines = []
        patcher = mock.patch.object(diagnostics, "LOG", self.lines.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sw = FakeSolidWorks(FakeDoc("C:/vault/cad/A.SLDPRT"))
        self.changes = []

    def watcher(self, attach=None):
        return sw_watcher.SolidWorksWatcher(on_change=self.changes.append, attach=attach or (lambda: self.sw))

    def test_it_keeps_the_latest_answer_and_reports_changes(self):
        w = self.watcher()
        self.assertEqual([c.what for c in w.poll_once()], ["opened"])
        self.assertTrue(w.is_open("C:/vault/cad/A.SLDPRT"))
        self.assertEqual(w.poll_once(), [])                                     # nothing new
        self.sw.docs[0].unsaved = True
        self.assertEqual([c.what for c in w.poll_once()], ["has unsaved changes"])
        self.assertEqual(len(self.changes), 2)

    def test_solidworks_not_running_is_an_empty_answer(self):
        w = self.watcher(attach=lambda: None)
        self.assertEqual(w.poll_once(), [])
        self.assertEqual(w.snapshot(), {})
        self.assertEqual(self.lines, [])

    def test_solidworks_going_away_is_logged_once_and_tried_again(self):
        w = self.watcher()
        w.poll_once()
        broken = mock.Mock(side_effect=RuntimeError("RPC server unavailable"))
        w._read = broken
        self.assertEqual([c.what for c in w.poll_once()], ["closed"])          # it counts as everything closed
        w.poll_once()
        self.assertEqual(len([l for l in self.lines if "could not ask SolidWorks" in l]), 1)
        w._read = sw_documents.open_documents
        self.assertEqual([c.what for c in w.poll_once()], ["opened"])          # back again

    def test_debug_mode_logs_every_change(self):
        with mock.patch.object(diagnostics, "DEBUG", True):
            self.watcher().poll_once()
        self.assertIn("SolidWorks: opened: C:/vault/cad/A.SLDPRT", self.lines)

    def test_quiet_unless_debug_mode(self):
        self.watcher().poll_once()
        self.assertEqual(self.lines, [])

    def test_the_thread_starts_and_stops(self):
        seen = threading.Event()
        w = sw_watcher.SolidWorksWatcher(on_change=lambda changes: seen.set(), attach=lambda: self.sw, interval=0.01)
        w.start()
        self.assertTrue(seen.wait(5))
        w.stop()
        self.assertIsNone(w._thread)
        time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
