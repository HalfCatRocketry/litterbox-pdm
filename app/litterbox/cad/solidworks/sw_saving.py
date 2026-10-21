"""
sw_saving.py - saving a STEP of a part or assembly, and a PDF of a drawing, through SolidWorks.

The file is opened read-only, saved as a copy in the new format, and closed again; it is never saved itself
(opening a drawing can rebuild it). It is opened as a visible document: hidden, SolidWorks 2024 crashed while
saving a STEP (tried 2026-10-21). A SolidWorks Litterbox started runs out of sight anyway; in one the person has
open, the file shows for a moment. A file the person already has open is used as it is and left
open, but only if it has no unsaved changes: the copy must match the file on disk. STEP files are always AP214;
the person's own STEP setting is put back afterwards. A PDF has every sheet of the drawing.

Through COM, so on one thread only (see com.com_thread). `sw` is the SolidWorks application (sw_backend).
"""

import contextlib
import os

from litterbox import diagnostics
from litterbox.cad.solidworks import com
from litterbox.cad.solidworks import sw_errors


DOC_PART, DOC_ASSEMBLY, DOC_DRAWING = 1, 2, 3       # swDocumentTypes_e
OPEN_SILENT, OPEN_READ_ONLY = 1, 2                  # swOpenDocOptions_e
SAVE_SILENT, SAVE_COPY = 1, 2                       # swSaveAsOptions_e
CURRENT_VERSION = 0                                 # swSaveAsVersion_e
STEP_AP_SETTING, AP214 = 75, 214                    # swUserPreferenceIntegerValue_e.swStepAP
EXPORT_PDF = 1                                      # swExportDataFileType_e.swExportPdfData
ALL_SHEETS = 1                                      # swExportDataSheetsToExport_e.swExportData_ExportAllSheets

DOC_TYPES = {".sldprt": DOC_PART, ".sldasm": DOC_ASSEMBLY, ".slddrw": DOC_DRAWING}


def _by_ref():
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def _nothing():
    import pythoncom
    from win32com.client import VARIANT
    return VARIANT(pythoncom.VT_DISPATCH, None)


@contextlib.contextmanager
def opened(sw, path):
    """The SolidWorks document of `path` (a full path): the one already open, or opened read-only and closed again
    afterwards."""
    name = os.path.basename(path)
    doc_type = DOC_TYPES.get(os.path.splitext(path)[1].lower())
    if doc_type is None:
        raise sw_errors.SolidWorksError(f"{name} is not a SolidWorks part, assembly or drawing.")
    model = sw.GetOpenDocumentByName(path)
    if model is not None:
        if com.call(model, "GetSaveFlag"):
            raise sw_errors.SolidWorksError(f"{name} is open in SolidWorks with changes that are not saved. "
                                            "Save or close it, then try again.")
        yield model
        return
    errors, warnings = _by_ref(), _by_ref()
    model = sw.OpenDoc6(path, doc_type, OPEN_SILENT | OPEN_READ_ONLY, "", errors, warnings)
    if model is None:
        raise sw_errors.SolidWorksError(f"SolidWorks could not open {name} (error {errors.value}).")
    try:
        yield model
    finally:
        try:
            sw.CloseDoc(com.call(model, "GetTitle"))
        except Exception as e:
            diagnostics.LOG(f"Could not close {name} in SolidWorks: {e}")


def _save_copy(model, out, export_data):
    errors, warnings = _by_ref(), _by_ref()
    ok = model.Extension.SaveAs(out, CURRENT_VERSION, SAVE_SILENT | SAVE_COPY, export_data, errors, warnings)
    if not ok or not os.path.isfile(out):
        raise sw_errors.SolidWorksError(f"SolidWorks could not save {os.path.basename(out)} (error {errors.value}).")


def save_step(sw, path, out):
    """Save the part or assembly at `path` as an AP214 STEP file at `out` (both full paths)."""
    before = sw.GetUserPreferenceIntegerValue(STEP_AP_SETTING)
    sw.SetUserPreferenceIntegerValue(STEP_AP_SETTING, AP214)
    try:
        with opened(sw, path) as model:
            _save_copy(model, out, _nothing())
    finally:
        if before != AP214:
            sw.SetUserPreferenceIntegerValue(STEP_AP_SETTING, before)


def save_pdf(sw, path, out):
    """Save every sheet of the drawing at `path` as one PDF at `out` (both full paths)."""
    with opened(sw, path) as model:
        data = sw.GetExportFileData(EXPORT_PDF)
        data.SetSheets(ALL_SHEETS, _nothing())
        _save_copy(model, out, data)
