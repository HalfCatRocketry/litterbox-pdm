"""
sw_reload.py - after a check-out: documents SolidWorks already had open read-only become writable, so the person can
save them without reloading by hand (File > Reload with Read-only unticked). It only touches documents that are
already open: it never starts SolidWorks, opens, saves or closes anything.

    open_read_only(paths)                   # [OpenDocument] of these that are open read-only; None: not running
    make_writable(paths, reload=paths2)     # (done, failed): those in reload are loaded again from disk first

A file the check-out didn't change is switched to read-write where it is (ModelDoc2.SetReadOnlyState), which keeps
anything typed into it since. A file the check-out replaced with a newer version is loaded again from disk
(ModelDoc2.ReloadOrReplace), which throws away unsaved changes: the window asks before that. Whether a call worked
is read back from SolidWorks afterwards (IsOpenedReadOnly) rather than trusted from its answer.

Each call attaches afresh, in its own COM apartment (com.com_thread), so it can run on any thread, e.g. a job.
Tried with SolidWorks 2024: a part open on its own becomes writable. Reloading a newer version, components of an
open assembly and a busy SolidWorks are still to try.
"""

from litterbox.cad import open_documents
from litterbox.cad.solidworks import com
from litterbox.cad.solidworks import sw_documents


def open_read_only(paths):
    """The OpenDocuments among these full paths that SolidWorks has open read-only, or None if SolidWorks isn't
    running. Raises whatever COM raises if SolidWorks stops answering."""
    with com.com_thread():
        sw = sw_documents.attach()
        if sw is None:
            return None
        found = sw_documents.open_documents(sw)
        wanted = list(dict.fromkeys(open_documents.key(path) for path in paths))
        return [found[key] for key in wanted if key in found and found[key].read_only]


def make_writable(paths, reload=()):
    """Make these open documents (full paths) read-write. Those also in `reload` are loaded again from disk first,
    without saving (the caller has asked about unsaved changes). Returns (done, failed): [path] and [(path, why)].
    Never raises."""
    reloads = {open_documents.key(path) for path in reload}
    wanted = {open_documents.key(path): path for path in paths}
    tried = {}
    try:
        with com.com_thread():
            sw = sw_documents.attach()
            if sw is None:
                return [], [(path, "SolidWorks isn't running") for path in wanted.values()]
            for doc, path in sw_documents.each_document(sw):
                key = open_documents.key(path)
                if key not in wanted or key in tried:
                    continue
                try:
                    if key in reloads:
                        com.call(doc, "ReloadOrReplace", False, "", True)    # read-only no, same file, don't save
                    else:
                        com.call(doc, "SetReadOnlyState", False)
                    tried[key] = ""
                except Exception as e:                  # busy, a dialog open, a call this version doesn't have...
                    tried[key] = f"SolidWorks refused: {e}"
            now = sw_documents.open_documents(sw)       # read back: a reloaded document is a new object
    except Exception as e:
        return [], [(path, f"SolidWorks stopped answering: {e}") for path in wanted.values()]
    done, failed = [], []
    for key, path in wanted.items():
        if key not in tried:
            failed.append((path, "it isn't open in SolidWorks any more"))
        elif tried[key]:
            failed.append((path, tried[key]))
        elif key not in now or now[key].read_only:
            failed.append((path, "SolidWorks kept it read-only"))
        else:
            done.append(path)
    return done, failed
