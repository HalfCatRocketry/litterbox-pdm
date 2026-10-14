"""
sw_backend.py - SolidWorks as the importer, Revise and Update references use it: read a file's
references, copy a file with its references updated (Pack and Go), point a file at a different one, close.

Through COM, so on one thread only (see importing/session.py and com.com_thread).
"""

import os
import shutil

from litterbox import diagnostics
from litterbox.cad.solidworks import sw_process
from litterbox.importing import import_errors


def pair_references(stored, found):
    """[(stored path, found path)] for one file's references.

    `stored` is what the file says (it may be an old folder that no longer exists) and `found`
    is where SolidWorks finds each file when it searches. Normally the two lists line up. If they
    don't, they are matched by file name, and a stored reference with no unique match gets ''.
    """
    stored, found = list(stored), list(found)
    if len(stored) == len(found) and all(
            os.path.basename(a).lower() == os.path.basename(b).lower() for a, b in zip(stored, found)):
        return list(zip(stored, found))
    pairs = []
    for ref in stored:
        name = os.path.basename(ref).lower()
        matches = [f for f in found if os.path.basename(f).lower() == name]
        pairs.append((ref, matches[0] if len(matches) == 1 else ""))
    return pairs


class SolidWorksBackend:
    """The four things the importer needs from SolidWorks. None of them writes to an original file.

    references(path)         [(stored, found)] for the file's direct references
    copy(src, dst)           copy a file on disk (nothing needs to be open)
    repoint(file, old, new)  change one reference inside the NEW file
    version()                the SolidWorks version, for the log
    """

    def __init__(self, attach_only=False):
        self._sw = None
        self._started_by_us = False
        self._pid = None                    # the process of a SolidWorks we started, learned while it is alive
        self.attach_only = attach_only      # True: use a SolidWorks that is already running, never start one

    def _app(self):
        if self._sw is None:
            from litterbox.cad.solidworks import com
            try:
                if self.attach_only:
                    import win32com.client
                    self._sw, self._started_by_us = win32com.client.GetActiveObject("SldWorks.Application"), False
                else:
                    before = sw_process.solidworks_pids()
                    self._sw, self._started_by_us = com.connect()
                    if self._started_by_us:
                        self._pid = sw_process.own_process_id(self._sw, before)
            except Exception as e:
                if self.attach_only:
                    raise import_errors.ImportFailed("SolidWorks is not open.") from None
                raise import_errors.ImportFailed("Litterbox could not connect to SolidWorks. Is it installed on this computer?\n\n"
                                   f"{e}") from None
        return self._sw

    def _dependencies(self, path, search):
        from litterbox.cad.solidworks import com
        deps = com.call(self._app(), "GetDocumentDependencies2", path, False, search, False) or []
        return [p for p in list(deps)[1::2] if isinstance(p, str)]

    def references(self, path):
        return pair_references(self._dependencies(path, False), self._dependencies(path, True))

    def copy(self, src, dst):
        import pythoncom
        from win32com.client import VARIANT
        os.makedirs(os.path.dirname(dst), exist_ok=True)         # CopyDocument will not create the folder
        empty = lambda: VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [])
        result = self._app().CopyDocument(src, dst, empty(), empty(), 0)
        if os.path.exists(dst):
            return
        # SolidWorks refused. A single part that uses no other files (a purchased washer, say) has nothing for
        # SolidWorks to update inside the copy, so an ordinary file copy gives exactly the same result.
        if src.lower().endswith(".sldprt"):
            try:
                alone = not self._dependencies(src, False)
            except Exception:
                alone = False
            if alone:
                shutil.copyfile(src, dst)
                return
        raise import_errors.ImportFailed(f"SolidWorks could not copy {src} (it returned {result!r}).\n\nIf the file is open in "
                           "SolidWorks, close it and try again. Check that you can open it, and that it is not "
                           "in a folder SolidWorks can't read.")

    def repoint(self, file, old, new):
        return bool(self._app().ReplaceReferencedDocument(file, old, new))

    def version(self):
        app = self._app()                       # a failure to connect should be reported, not hidden
        try:
            return str(app.RevisionNumber)
        except Exception:
            return ""

    def close(self):
        """Shut down the SolidWorks we started (never one that was already running), and make sure it is gone.

        A SolidWorks started by a program runs hidden. If it lingers, Windows later hands "Open" to that
        hidden copy, and the part opens in a window nobody can see. So after ExitApp we let go of our hold
        on it, wait for its process to end, and end it ourselves if it will not."""
        sw, self._sw = self._sw, None
        if sw is None or not self._started_by_us:
            return
        pid = self._pid
        if not pid:
            try:
                pid = int(sw.GetProcessID())
            except Exception:
                pass
        try:
            sw.ExitApp()
        except Exception:
            pass
        del sw
        import gc
        gc.collect()                                      # let go of any COM objects still pointing at it
        if pid:
            sw_process.wait_for_exit(pid, log=lambda message: diagnostics.LOG(message))
        else:
            diagnostics.LOG("Could not tell which SolidWorks process Litterbox started, so could not check it had exited.")
