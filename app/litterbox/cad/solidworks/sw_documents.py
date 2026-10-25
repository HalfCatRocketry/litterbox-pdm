"""
sw_documents.py - which documents a running SolidWorks has open, and whether each has unsaved changes or was opened
read-only. It only looks: it never starts SolidWorks, opens, saves or closes anything (sw_reload.py makes
open documents writable after a check-out).

    sw = sw_documents.attach()                  # None if SolidWorks isn't running
    found = sw_documents.open_documents(sw)     # {open_documents.key(path): OpenDocument}

Documents SolidWorks loaded only as parts of an open assembly count as open too: SolidWorks holds them as well.
Tried with SolidWorks 2024 (the reload at check-out, 2026-10-22); the watcher's use of it not yet.
"""

from litterbox.cad import open_documents as docs
from litterbox.cad.open_documents import OpenDocument
from litterbox.cad.solidworks import com


def attach():
    """The running SolidWorks, or None if it isn't running (or this isn't Windows). Never starts one."""
    try:
        import win32com.client
        return win32com.client.GetActiveObject("SldWorks.Application")
    except Exception:
        return None


def _flag(doc, name, default=False):
    try:
        return bool(com.call(doc, name))
    except Exception:
        return default


def each_document(sw):
    """(document, path) for every document SolidWorks has open that has a file (new, never saved ones are left
    out). The documents are SolidWorks' own COM objects: for cad/solidworks/ only. Raises whatever COM raises if
    SolidWorks stops answering."""
    doc = com.call(sw, "GetFirstDocument")
    seen = 0
    while doc is not None and seen < 10000:             # a safety stop: SolidWorks never has this many open
        seen += 1
        path = com.call(doc, "GetPathName") or ""
        if path:
            yield doc, path
        doc = com.call(doc, "GetNext")


def open_documents(sw):
    """{open_documents.key(path): OpenDocument} for every document SolidWorks has open (see each_document)."""
    return {docs.key(path): OpenDocument(path, _flag(doc, "GetSaveFlag"), _flag(doc, "IsOpenedReadOnly"),
                                    _flag(doc, "Visible", default=True))
            for doc, path in each_document(sw)}
