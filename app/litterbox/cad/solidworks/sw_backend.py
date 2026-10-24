"""
sw_backend.py - SolidWorks as the importer, Revise, Update references and Generate STEP/PDF use it (the backend of
cad/cad_program.py): read a file's references, list an assembly's components (to count them, to find its Toolbox
parts, and the configuration of each), read a part's material, read a model's configurations and rename one
(sw_configurations.py), copy a file with its references updated (Pack and Go), point a file at a different one, save
a STEP or PDF of it (sw_saving.py), make a new part, assembly or drawing from a template, close.

Through COM, so on one thread only (see importing/session.py and com.com_thread).
"""

import contextlib
import os
import shutil

from litterbox import diagnostics
from litterbox.core import file_types
from litterbox.cad.cad_program import COUNTED, EXCLUDED, SUPPRESSED
from litterbox.cad.solidworks import sw_configurations
from litterbox.cad.solidworks import sw_errors
from litterbox.cad.solidworks import sw_process
from litterbox.cad.solidworks import sw_saving


DOC_PART, DOC_ASSEMBLY = 1, 2       # swDocumentTypes_e
OPEN_SILENT, OPEN_READ_ONLY = 1, 2  # swOpenDocOptions_e
TOOLBOX_STANDARD_PART = 1           # swToolBoxPartType_e: 0 not a Toolbox part, 1 a Toolbox part, 2 one copied from it


def full_path(path):
    """An absolute Windows path with backslashes. SolidWorks crashed (tried with SolidWorks 2024) when given a
    relative path, and misses an open document when the slashes are mixed."""
    return os.path.abspath(os.path.normpath(str(path)))


def component_state(suppressed, excluded, envelope):
    """How a component counts in a BOM: suppressed ones and envelopes aren't there, and some are left out of
    the BOM on purpose."""
    if suppressed:
        return SUPPRESSED
    if excluded or envelope:
        return EXCLUDED
    return COUNTED


def material_name(property_name, id_name):
    """A part's material: what GetMaterialPropertyName2 gives, or else the older MaterialIdName ('SOLIDWORKS
    Materials|Chrome Stainless Steel|7', or just 'Steel' in parts from much older versions), or '' for none.
    (Both seen with SolidWorks 2024.)"""
    if property_name and str(property_name).strip():
        return str(property_name).strip()
    text = str(id_name or "").strip()
    if "|" in text:
        fields = text.split("|")
        return fields[1].strip() if len(fields) > 1 else ""
    return text


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
    """The things the importer and check-in need from SolidWorks. None of them writes to an original file.

    references(path)         [(stored, found)] for the file's direct references
    components(path)         [(file, COUNTED / SUPPRESSED / EXCLUDED)] for an assembly's top-level components
    library_components(path) the files of an assembly's top-level components that are Toolbox parts
    component_configurations(path)  {file: [configuration]} the configuration of a part each top-level component uses
    configurations(path)     a model's configurations (sw_configurations.read)
    name_configuration(path, old, new)  rename a configuration of a model that may be changed, and save it
    material(path)           a part's material in its active configuration ('' for none)
    copy(src, dst)           copy a file on disk (nothing needs to be open)
    repoint(file, old, new)  change one reference inside the NEW file
    save_step(path, out)     save a part or assembly as an AP214 STEP file
    save_pdf(path, out)      save every sheet of a drawing as a PDF
    new_from_template(template, out)  a new part, assembly or drawing (an empty sheet) from a template, saved
    version()                the SolidWorks version, for the log
    """

    def __init__(self, attach_only=False):
        self._sw = None
        self._started_by_us = False
        self._pid = None                    # the process of a SolidWorks we started, learned while it is alive
        self.attach_only = attach_only      # True: use a SolidWorks that is already running, never start one
        self._components = {}               # full path: (its modification time, _read_components)

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
                    raise sw_errors.SolidWorksError("SolidWorks is not open.") from None
                raise sw_errors.SolidWorksError("Litterbox could not connect to SolidWorks. Is it installed on this computer?\n\n"
                                   f"{e}") from None
        return self._sw

    def _dependencies(self, path, search):
        from litterbox.cad.solidworks import com
        deps = com.call(self._app(), "GetDocumentDependencies2", full_path(path), False, search, False) or []
        return [p for p in list(deps)[1::2] if isinstance(p, str)]

    def references(self, path):
        return pair_references(self._dependencies(path, False), self._dependencies(path, True))

    @contextlib.contextmanager
    def _opened(self, path, doc_type):
        """The document at `path`: one the person has open is used as it is in SolidWorks and left open; any other
        is opened read-only, out of sight, and closed again afterwards."""
        import pythoncom
        from litterbox.cad.solidworks import com
        from win32com.client import VARIANT
        sw, path = self._app(), full_path(path)
        model = sw.GetOpenDocumentByName(path)
        opened = model is None
        if opened:
            errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            sw.DocumentVisible(False, doc_type)                       # don't show it in the person's SolidWorks
            try:
                model = sw.OpenDoc6(path, doc_type, OPEN_SILENT | OPEN_READ_ONLY, "", errors, warnings)
            finally:
                sw.DocumentVisible(True, doc_type)
            if model is None:
                raise sw_errors.SolidWorksError(f"SolidWorks could not open {os.path.basename(path)} "
                                                f"(error {errors.value}).")
        try:
            yield model
        finally:
            if opened:
                try:
                    sw.CloseDoc(com.call(model, "GetTitle"))
                except Exception as e:
                    diagnostics.LOG(f"Could not close {os.path.basename(path)} in SolidWorks: {e}")

    def components(self, path):
        """One (file, state) per component at the top of an assembly, one entry for each copy (see _opened). A
        component whose file can't be found is reported as suppressed."""
        return [(file, state) for file, state, _toolbox, _config in self._read_components(path)]

    def library_components(self, path):
        """The files of an assembly's top-level components that are Toolbox parts (see _opened): those whose model
        says it is a Toolbox part (ModelDocExtension.ToolboxPartType 1; a part copied from Toolbox, 2, is a part of
        its own). A component with no model loaded (suppressed, or its file missing) can't say, and is left out.
        Tried with SolidWorks 2024: a socket head cap screw from Toolbox gives 1, an ordinary part 0. The file is
        where SolidWorks loaded it, which for a Toolbox part is always the Toolbox folder this computer's SolidWorks
        is set to use (Toolbox Data Location), whatever folder the assembly was saved with."""
        return [file for file, _state, toolbox, _config in self._read_components(path) if toolbox]

    def component_configurations(self, path):
        """{file: [configuration names]}: which configuration of each file the assembly's top-level components use
        (see _opened). A component with no configuration to say (its file missing) is left out."""
        found = {}
        for file, _state, _toolbox, config in self._read_components(path):
            if file and config:
                found.setdefault(file, set()).add(config)
        return {file: sorted(names) for file, names in found.items()}

    def _read_components(self, path):
        """[(file, state, is a Toolbox part, configuration)] for an assembly's top-level components, read with one
        opening of the assembly and kept while the file is unchanged (check-in asks for the counts, the Toolbox parts
        and the configurations)."""
        from litterbox.cad.solidworks import com
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            stamp = None
        kept = self._components.get(full_path(path))
        if kept is not None and stamp is not None and kept[0] == stamp:
            return kept[1]
        with self._opened(path, DOC_ASSEMBLY) as model:
            found = []
            for component in com.call(model, "GetComponents", True) or []:
                try:
                    doc = com.call(component, "GetModelDoc2")
                    kind = com.call(com.call(doc, "Extension"), "ToolboxPartType") if doc is not None else 0
                except Exception:
                    kind = 0
                try:
                    config = str(com.call(component, "ReferencedConfiguration") or "")
                except Exception:
                    config = ""
                found.append((str(com.call(component, "GetPathName") or ""),
                              component_state(com.call(component, "IsSuppressed"),
                                              com.call(component, "ExcludeFromBOM"),
                                              com.call(component, "IsEnvelope")),
                              kind == TOOLBOX_STANDARD_PART, config))
        if stamp is not None:
            self._components[full_path(path)] = (stamp, found)
        return found

    def material(self, path):
        """A part's material in its active configuration, as SolidWorks shows it ('Chrome Stainless Steel'), or ''
        if none is assigned (see _opened). Each configuration can have its own; the active one is what the person
        last saved it with."""
        import pythoncom
        from litterbox.cad.solidworks import com
        from win32com.client import VARIANT
        with self._opened(path, DOC_PART) as model:
            try:
                config = com.call(com.call(com.call(model, "ConfigurationManager"), "ActiveConfiguration"), "Name")
            except Exception:
                config = ""
            database = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")      # an out value: the material library
            name = model.GetMaterialPropertyName2(config or "", database)
            try:
                old = com.call(model, "MaterialIdName") if not name else ""
            except Exception:
                old = ""
            return material_name(name, old)

    def configurations(self, path):
        """A part's or assembly's configurations (sw_configurations.read), see _opened."""
        part = file_types.is_part(path)
        with self._opened(path, DOC_PART if part else DOC_ASSEMBLY) as model:
            return sw_configurations.read(model, part)

    def name_configuration(self, path, old, new):
        """Rename configuration `old` of a part or assembly to `new` and save the file. A file the person has open is
        changed in their SolidWorks, unless it has unsaved changes (they are theirs to save): then, or if the file
        is read-only, it raises SolidWorksError and nothing changes. Any other is opened out of sight and closed."""
        import pythoncom
        from litterbox.cad.solidworks import com
        from win32com.client import VARIANT
        sw, path = self._app(), full_path(path)
        doc_type = DOC_PART if file_types.is_part(path) else DOC_ASSEMBLY
        name = os.path.basename(path)
        model = sw.GetOpenDocumentByName(path)
        opened = model is None
        if not opened and com.call(model, "GetSaveFlag"):
            raise sw_errors.SolidWorksError(f"{name} has unsaved changes in SolidWorks")
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        if opened:
            sw.DocumentVisible(False, doc_type)
            try:
                model = sw.OpenDoc6(path, doc_type, OPEN_SILENT, "", errors, warnings)
            finally:
                sw.DocumentVisible(True, doc_type)
            if model is None:
                raise sw_errors.SolidWorksError(f"SolidWorks could not open {name} (error {errors.value}).")
        try:
            if com.call(model, "IsOpenedReadOnly"):
                raise sw_errors.SolidWorksError(f"{name} is read-only")
            try:
                sw_configurations.rename(model, old, new)
            except ValueError as e:
                raise sw_errors.SolidWorksError(f"{name}: {e}") from None
            if not model.Save3(1, errors, warnings):
                raise sw_errors.SolidWorksError(f"SolidWorks could not save {name} (error {errors.value}).")
        finally:
            if opened:
                try:
                    sw.CloseDoc(com.call(model, "GetTitle"))
                except Exception as e:
                    diagnostics.LOG(f"Could not close {name} in SolidWorks: {e}")

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
        raise sw_errors.SolidWorksError(f"SolidWorks could not copy {src} (it returned {result!r}).\n\nIf the file is open in "
                           "SolidWorks, close it and try again. Check that you can open it, and that it is not "
                           "in a folder SolidWorks can't read.")

    def repoint(self, file, old, new):
        return bool(self._app().ReplaceReferencedDocument(file, old, new))

    def save_step(self, path, out):
        sw_saving.save_step(self._app(), full_path(path), full_path(out))

    def save_pdf(self, path, out):
        sw_saving.save_pdf(self._app(), full_path(path), full_path(out))

    def new_from_template(self, template, out):
        """Make a new file at `out` (a full path that isn't there yet) from a template, save it and close it: a part
        or assembly as the template has it, or a drawing as an empty sheet of the template's size and sheet format
        (no views). Made out of sight; opening it afterwards is the caller's. Tried with SolidWorks 2024: NewDocument
        keeps a drawing template's own size and sheet format when given paper size 0, and the sheet format is kept
        inside the template (a drawing made after its .slddrt file was deleted still has its title block). A template
        it can't use (missing, damaged, or saved in a newer SolidWorks) gives no document."""
        import pythoncom
        from litterbox.cad.solidworks import com
        from win32com.client import VARIANT
        sw, template, out = self._app(), full_path(template), full_path(out)
        name, wanted = os.path.basename(out), sw_saving.DOC_TYPES.get(os.path.splitext(out)[1].lower())
        if wanted is None:
            raise sw_errors.SolidWorksError(f"{name} isn't a SolidWorks part, assembly or drawing.")
        if os.path.exists(out):
            raise sw_errors.SolidWorksError(f"{name} is there already, so it wasn't made again.")
        if not os.path.isfile(template):
            raise sw_errors.SolidWorksError(f"The template {os.path.basename(template)} isn't on this computer.")
        sw.DocumentVisible(False, wanted)
        try:
            model = sw.NewDocument(template, 0, 0, 0)
        finally:
            sw.DocumentVisible(True, wanted)
        if model is None:
            raise sw_errors.SolidWorksError(
                f"SolidWorks {self.version() or ''} couldn't make a new file from {os.path.basename(template)}. A "
                "template saved in a newer SolidWorks can't be used in an older one, nor can a damaged one.")
        try:
            made = com.call(model, "GetType")
            if made != wanted:
                raise sw_errors.SolidWorksError(f"{os.path.basename(template)} made the wrong kind of file for "
                                                f"{name}.")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            ok = model.Extension.SaveAs(out, sw_saving.CURRENT_VERSION, sw_saving.SAVE_SILENT,
                                        VARIANT(pythoncom.VT_DISPATCH, None), errors, warnings)
            if not ok or not os.path.isfile(out):
                raise sw_errors.SolidWorksError(f"SolidWorks could not save {name} (error {errors.value}).")
        finally:
            try:
                sw.CloseDoc(com.call(model, "GetTitle"))
            except Exception as e:
                diagnostics.LOG(f"Could not close the new {name} in SolidWorks: {e}")

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
