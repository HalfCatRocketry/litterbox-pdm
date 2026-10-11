"""
sw_rename_test.py - can SolidWorks copy an assembly under NEW file names and fix every reference?

This is an experiment, not part of Litterbox itself. It tries SolidWorks' own "Pack and Go"
feature through its API. Pack and Go copies a model and everything it references to a new
folder, and it can give each copied file a new name while rewriting the references inside
the copies. That is exactly what the importer needs: your original files stay where they are,
and the vault gets renamed copies that point at each other.

    python sw_rename_test.py "C:\\...\\Axial TurboCat\\AxTC TPA 01.SLDASM"
        [--dest C:\\Litterbox\\rename-test]  [--report sw-rename-report.txt]

What it does
  1. Records every file in the original folder (SHA-256 for CAD files).
  2. Connects to SolidWorks and prints the exact parameter lists of the calls involved
     (so that if one of them differs from what this script assumes, the report shows it).
  3. Opens the assembly READ-ONLY and uses Pack and Go to save renamed copies into --dest
     as TST-00001-001.SLDASM, TST-00002-001.SLDPRT ... (a drawing gets the same number as
     its model). The folder --dest must not exist yet, or must be empty.
  4. Closes the original WITHOUT saving.
  5. Checks the original folder is unchanged (it must be).
  6. Opens the NEW assembly read-only and checks that every component is one of the new files,
     that each exists, and that nothing still points back at the original folder.

Your original files are never written to. Everything new goes into --dest only. When you are
done you can delete --dest yourself. Send the report file (sw-rename-report.txt) back.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import sw_probe

PREFIX = "TST"
OPEN_SILENT = 1
OPEN_READ_ONLY = 2
DOC_TYPES = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}


# ---------------------------------------------------------------------------
# Plain logic (no SolidWorks needed)
# ---------------------------------------------------------------------------

def _extension(path):
    return os.path.splitext(path)[1].lower()


def _pair_key(path):
    return os.path.dirname(path).lower(), os.path.splitext(os.path.basename(path))[0].lower()


def build_new_names(doc_paths, dest_folder, top=None, prefix=PREFIX):
    """{old full path: new full path}, one new number per model and drawings sharing their model's.

    `top` (the file the user picked) gets number 1. Drawings are paired with the model that has
    the same name in the same folder, just like the scan does; a drawing with no model gets a
    number of its own.
    """
    paths = list(dict.fromkeys(doc_paths))
    models = sorted((p for p in paths if _extension(p) != ".slddrw"), key=lambda p: p.lower())
    if top is not None and top in models:
        models.remove(top)
        models.insert(0, top)
    drawings = [p for p in paths if _extension(p) == ".slddrw"]

    result, base_of_key, number = {}, {}, 0
    for path in models:
        number += 1
        base = f"{prefix}-{number:05d}-001"
        base_of_key[_pair_key(path)] = base
        result[path] = os.path.join(dest_folder, base + os.path.splitext(path)[1])
    for path in sorted(drawings, key=lambda p: p.lower()):
        base = base_of_key.get(_pair_key(path))
        if base is None:
            number += 1
            base = f"{prefix}-{number:05d}-001"
        result[path] = os.path.join(dest_folder, base + os.path.splitext(path)[1])
    return result


def is_inside(path, folder):
    if not isinstance(path, str):
        return False
    folder = os.path.normcase(os.path.abspath(folder)).rstrip("\\/") + os.sep
    return os.path.normcase(os.path.abspath(path)).startswith(folder)


def judge(components, dependencies, source_folder, dest_folder, expected_files, prefix=PREFIX):
    """Problems found in the NEW assembly (empty list = it looks right).

    components: dicts from sw_probe.describe_components; dependencies: the flat list SolidWorks
    gave for the new assembly (name, path, name, path ...); expected_files: the new paths we asked for.
    """
    problems = []
    for entry in components:
        path, name = entry.get("path"), entry.get("name")
        if not is_inside(path, dest_folder):
            problems.append(f"component {name} points outside the new folder: {path}")
        elif not os.path.exists(path):
            problems.append(f"component {name} points at a file that does not exist: {path}")
        elif not os.path.basename(path).upper().startswith(prefix + "-"):
            problems.append(f"component {name} is not one of the renamed files: {path}")
    for entry in dependencies or []:
        if isinstance(entry, str) and os.sep in entry and is_inside(entry, source_folder):
            problems.append(f"the new assembly still depends on the ORIGINAL file {entry}")
    for path in expected_files:
        if not os.path.exists(path):
            problems.append(f"expected file was not created: {path}")
    return problems


# ---------------------------------------------------------------------------
# Talking to SolidWorks (only this part needs Windows, pywin32 and SolidWorks)
# ---------------------------------------------------------------------------

def get_member(obj, name, *args):
    """Read a property or call a method; returns COM objects as they are (they are 'callable' too)."""
    attribute = getattr(obj, name)
    if hasattr(attribute, "_oleobj_"):
        return attribute
    return attribute(*args) if callable(attribute) else attribute


_STATE = {"typelib": None}
_PARAM_FLAGS = ((1, "in"), (2, "out"), (4, "lcid"), (8, "retval"), (16, "opt"))
_INVOKE_KINDS = {1: "method", 2: "get", 4: "put", 8: "putref"}


def load_typelib(sw):
    """SolidWorks' own type library (the file that lists every call and its parameters), or None.

    Tries the application object first, then the sldworks.tlb file in SolidWorks' install folder.
    """
    problems = []
    try:
        tlib, _index = sw._oleobj_.GetTypeInfo().GetContainingTypeLib()
        _STATE["typelib"] = tlib
        return tlib
    except Exception as e:
        problems.append(f"from the application object: {e!r}")
    try:
        import pythoncom
        folders = []
        try:
            folders.append(str(sw_probe.call(sw, "GetExecutablePath")))
        except Exception as e:
            problems.append(f"install folder unknown: {e!r}")
        folders.append(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS")
        for folder in folders:
            path = os.path.join(folder, "sldworks.tlb")
            if os.path.exists(path):
                tlib = pythoncom.LoadTypeLib(path)
                _STATE["typelib"] = tlib
                return tlib
            problems.append(f"no file {path}")
    except Exception as e:
        problems.append(f"from sldworks.tlb: {e!r}")
    _STATE["typelib"] = None
    _STATE["typelib_error"] = "; ".join(problems)
    return None


def _install_folders(sw):
    folders = []
    try:
        folders.append(str(sw_probe.call(sw, "GetExecutablePath")))
    except Exception:
        pass
    folders.append(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS")
    return folders


def load_constants(sw):
    """SolidWorks' constants type library (swconst.tlb: the meaning of option and result codes), or None."""
    try:
        import pythoncom
        for folder in _install_folders(sw):
            path = os.path.join(folder, "swconst.tlb")
            if os.path.exists(path):
                return pythoncom.LoadTypeLib(path)
    except Exception:
        pass
    return None


def enum_names(tlib, text):
    try:
        return sorted(tlib.GetDocumentation(i)[0] for i in range(tlib.GetTypeInfoCount())
                      if text.lower() in tlib.GetDocumentation(i)[0].lower())
    except Exception:
        return []


def describe_interface(tlib, interface, contains=()):
    """Lines like 'IPackAndGo.SetSaveToName(SaveToName[in], Name[in]) [method]' read from the type library."""
    lines = []
    try:
        for index in range(tlib.GetTypeInfoCount()):
            if tlib.GetDocumentation(index)[0] != interface:
                continue
            info = tlib.GetTypeInfo(index)
            for k in range(info.GetTypeAttr().cFuncs):
                try:
                    desc = info.GetFuncDesc(k)
                    names = info.GetNames(desc.memid)
                except Exception:
                    continue
                if contains and not any(c.lower() in names[0].lower() for c in contains):
                    continue
                params = []
                for name, arg in zip(names[1:], desc.args):
                    tags = [tag for bit, tag in _PARAM_FLAGS if arg[1] & bit]
                    params.append(name + (f"[{','.join(tags)}]" if tags else ""))
                lines.append(f"{interface}.{names[0]}({', '.join(params)}) [{_INVOKE_KINDS.get(desc.invkind, '?')}]")
    except Exception as e:
        lines.append(f"{interface}: could not read the type library ({e})")
    if not lines:
        lines.append(f"{interface}: nothing found in the type library")
    return lines


def describe_enum(tlib, enum_name):
    """Lines like 'swMoveCopyError_e: swMoveCopyError_None = 0' read from the type library."""
    try:
        for index in range(tlib.GetTypeInfoCount()):
            if tlib.GetDocumentation(index)[0] != enum_name:
                continue
            info = tlib.GetTypeInfo(index)
            lines = []
            for k in range(info.GetTypeAttr().cVars):
                desc = info.GetVarDesc(k)
                lines.append(f"{enum_name}: {info.GetNames(desc.memid)[0]} = {desc.value}")
            return lines or [f"{enum_name}: has no values listed"]
    except Exception as e:
        return [f"{enum_name}: could not read the type library ({e})"]
    return [f"{enum_name}: not found in the type library"]


def invoke(obj, name, *args, flags=None):
    """Call method `name` explicitly. Needed for objects Python has no type information for:
    there, plain attribute access would 'read' the name as a property and fail on a method."""
    import pythoncom
    import win32com.client
    found = obj._oleobj_.GetIDsOfNames(0, name)
    dispid = found[0] if isinstance(found, (tuple, list)) else found
    result = obj._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD if flags is None else flags, 1, *args)
    return win32com.client.Dispatch(result) if hasattr(result, "GetIDsOfNames") else result


def com_open(sw, path):
    """Open a model read-only and silently. Returns (model or None, error code, warning code)."""
    import pythoncom
    from win32com.client import VARIANT
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    model = sw.OpenDoc6(path, DOC_TYPES[_extension(path)], OPEN_READ_ONLY | OPEN_SILENT, "", errors, warnings)
    return model, errors.value, warnings.value


def _out_arrays(obj, method, count):
    """Call a SolidWorks method that hands arrays back through 'out' parameters.

    Tries the call with no arguments first (how 'out' values come back as a result), then with
    by-reference slots (how 'in/out' values are passed).
    """
    import pythoncom
    from win32com.client import VARIANT

    def arrays(values):
        values = list(values)[-count:]
        return [list(v) if isinstance(v, (list, tuple)) else [] for v in values]

    try:
        result = invoke(obj, method)
        if isinstance(result, tuple) and len(result) >= count:
            return arrays(result)
    except Exception:
        pass
    slots = [VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None) for _ in range(count)]
    result = invoke(obj, method, *slots)
    values = [slot.value for slot in slots]
    if all(v is None for v in values) and isinstance(result, tuple):
        values = list(result)
    return arrays(values)


def com_pack_and_go(model, dest_folder, make_names, log):
    """Save renamed copies of `model` and everything it references into `dest_folder`.

    make_names(list of original paths) -> {original: new}; called once SolidWorks has listed what it will copy.
    Returns SolidWorks' status codes, one per file. Every step is logged so a failure shows where it happened.
    """
    import pythoncom
    from win32com.client import VARIANT

    def step(label, func):
        log(f"  step: {label}")
        try:
            value = func()
        except Exception as e:
            log(f"    FAILED: {e!r}")
            raise
        text = repr(value)
        log(f"    ok: {text if len(text) < 120 else text[:117] + '...'}")
        return value

    tlib = _STATE["typelib"]
    if tlib is not None:
        log("  what SolidWorks' type library says about the calls used here:")
        for line in describe_interface(tlib, "IModelDocExtension", ("PackAndGo",)):
            log(f"    {line}")
        for line in describe_interface(tlib, "IPackAndGo"):
            log(f"    {line}")
    else:
        log(f"  (no type library available: {_STATE.get('typelib_error', 'not loaded')})")

    extension = step("model.Extension", lambda: get_member(model, "Extension"))
    def get_pack():
        import pythoncom
        failures = []
        for label, flags in (("as a method", pythoncom.DISPATCH_METHOD),
                             ("as a property read", pythoncom.DISPATCH_PROPERTYGET),
                             ("as either", pythoncom.DISPATCH_METHOD | pythoncom.DISPATCH_PROPERTYGET)):
            try:
                return invoke(extension, "GetPackAndGo", flags=flags)
            except Exception as e:
                failures.append(f"{label}: {e!r}")
                log(f"    GetPackAndGo {label} failed: {e!r}")
        raise RuntimeError("GetPackAndGo failed every way: " + "; ".join(failures))

    pack = step("Extension.GetPackAndGo()", get_pack)
    for prop, value in (("IncludeDrawings", True), ("FlattenToSingleFolder", True), ("IncludeSuppressed", True)):
        try:
            setattr(pack, prop, value)
            log(f"  set {prop} = {value}")
        except Exception as e:
            log(f"  could not set {prop}: {e}")
    step("PackAndGo.SetSaveToName(True, folder)", lambda: invoke(pack, "SetSaveToName", True, dest_folder))
    originals, current = step("PackAndGo.GetDocumentSaveToNames()", lambda: _out_arrays(pack, "GetDocumentSaveToNames", 2))
    log(f"  SolidWorks will copy {len(originals)} file(s):")
    for old, default in zip(originals, current):
        log(f"    {old}  ->  (default) {default}")
    mapping = make_names(originals)
    wanted = [mapping[old] for old in originals]
    step("PackAndGo.SetDocumentSaveToNames(new names)",
         lambda: invoke(pack, "SetDocumentSaveToNames", VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, wanted)))
    statuses = step("Extension.SavePackAndGo(pack)", lambda: invoke(extension, "SavePackAndGo", pack._oleobj_))
    return list(statuses) if isinstance(statuses, (list, tuple)) else [statuses]


def copy_order(top, children_of):
    """Documents in the order they must be copied: every file after the files it references."""
    order, done = [], set()

    def visit(path, trail):
        key = path.lower()
        if key in done:
            return
        if key in trail:
            raise ValueError(f"{path} references itself")
        for child in children_of(path):
            visit(child, trail | {key})
        done.add(key)
        order.append(path)

    visit(top, frozenset())
    return order


def sibling_drawing(path):
    """The .SLDDRW with the same name in the same folder as `path`, or None (how the scan pairs drawings)."""
    folder, stem = os.path.split(os.path.splitext(path)[0])
    try:
        for name in os.listdir(folder):
            if os.path.splitext(name)[1].lower() == ".slddrw" and os.path.splitext(name)[0].lower() == stem.lower():
                return os.path.join(folder, name)
    except OSError:
        pass
    return None


def new_name_for(reference, mapping):
    """The new path for a reference stored in a file, or None.

    An exact path match wins. Otherwise the file NAME is matched, because files that were copied
    or moved often still store the folder they used to live in. A name that matches more than one
    file is not guessed at.
    """
    if reference in mapping:
        return mapping[reference]
    name = os.path.basename(reference).lower()
    matches = [old for old in mapping if os.path.basename(old).lower() == name]
    return mapping[matches[0]] if len(matches) == 1 else None


def com_copy_documents(sw, top, dest_folder, make_names, log, option=0):
    """Copy `top` and everything below it under new names, then repoint each copy's references.

    Two SolidWorks calls do the work, and the originals are never written:
      1. CopyDocument copies a file on disk under its new name (nothing needs to be open).
      2. ReplaceReferencedDocument, run on the NEW file, changes each reference from the old
         child to the child's new name.
    Children are copied before the files that use them. A drawing next to a model (same name,
    same folder) is copied after the models and pointed at its model's new name.
    """
    import pythoncom
    from win32com.client import VARIANT

    def children_of(path, search=True):
        """Direct children as SolidWorks finds them (search=True also looks where references no longer point)."""
        deps = sw_probe.call(sw, "GetDocumentDependencies2", path, False, search, False) or []
        return [p for p in list(deps)[1::2] if isinstance(p, str)]

    models = copy_order(top, children_of)
    drawings = [d for d in (sibling_drawing(m) for m in models) if d]
    order = models + drawings
    mapping = make_names(order)
    os.makedirs(dest_folder, exist_ok=True)           # CopyDocument does not create the destination folder
    log(f"  {len(models)} model file(s) and {len(drawings)} drawing(s) to copy, children first:")
    stored_top, found_top = children_of(top, False), children_of(top, True)
    for label, items in (("stored in the file", stored_top), ("where SolidWorks finds them", found_top)):
        sample = items[0] if items else "(none)"
        log(f"    {os.path.basename(top)} references, {label}: {len(items)}; first: {sample}"
            + (f" [{'exists' if os.path.exists(sample) else 'NOT on disk'}]" if items else ""))
    for path in models[:6]:
        stored, found = children_of(path, False), children_of(path, True)
        log(f"    {os.path.basename(path)}: {len(stored)} reference(s) at their stored paths, {len(found)} when SolidWorks searches")
    empty = lambda: VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [])
    statuses, unresolved = [], []
    for path in order:
        new_path = mapping[path]
        log(f"  step: CopyDocument {os.path.basename(path)} -> {os.path.basename(new_path)}")
        try:
            result = sw.CopyDocument(path, new_path, empty(), empty(), option)
        except Exception as e:
            log(f"    FAILED: {e!r}")
            raise
        exists = os.path.exists(new_path)
        log(f"    returned {result!r}; new file {'exists' if exists else 'DOES NOT EXIST'}")
        statuses.append(result)
        if not exists:
            stored, found = children_of(path, False), children_of(path, True)
            log(f"    {os.path.basename(path)} references: {len(stored)} at stored paths, {len(found)} when searching")
            for item in found[:8]:
                log(f"      {item}")
            raise RuntimeError(f"CopyDocument returned {result!r} but did not create {new_path}")
        for kid in children_of(new_path):
            if is_inside(kid, dest_folder):
                continue
            target = new_name_for(kid, mapping)
            if target is None:
                log(f"    reference to {kid} cannot be repointed: no single file with that name is part of this copy")
                unresolved.append(f"{os.path.basename(new_path)} -> {kid}")
                continue
            try:
                replaced = sw.ReplaceReferencedDocument(new_path, kid, target)
            except Exception as e:
                replaced = f"FAILED {e!r}"
            log(f"    ReplaceReferencedDocument {os.path.basename(kid)} -> {os.path.basename(target)}: {replaced!r}")
        left = [k for k in children_of(new_path) if not is_inside(k, dest_folder) and new_name_for(k, mapping)]
        if left:
            unresolved += [f"{os.path.basename(new_path)} -> {k}" for k in left]
            log(f"    STILL pointing at the originals: {len(left)}")
    if unresolved:
        raise RuntimeError("references left pointing outside the new folder: " + "; ".join(unresolved[:5]))
    return statuses


# ---------------------------------------------------------------------------
# The experiment
# ---------------------------------------------------------------------------

def experiment(top, dest, sw, started_by_us=False, wrap=lambda x: x, open_func=com_open,
               pack_func=com_pack_and_go, signatures=True, open_original=True, log=print):
    """Run everything and return the report lines. Never writes into the original folder."""
    lines = []

    def say(text=""):
        lines.append(text)
        log(text)

    top = os.path.abspath(top)
    dest = os.path.abspath(dest)
    source = os.path.dirname(top)
    say(f"Original: {top}")
    say(f"Renamed copies go to: {dest}")

    if is_inside(dest, source) or is_inside(source, dest):
        say("STOPPED: the destination and the original folder overlap. Choose a destination outside it.")
        return lines
    if os.path.isdir(dest) and os.listdir(dest):
        say("STOPPED: the destination folder is not empty. Choose a new folder (or delete the old test yourself).")
        return lines

    before = sw_probe.snapshot(source)
    say(f"Recorded {len(before)} files in the original folder")
    try:
        sw.Visible = True
    except Exception:
        pass
    try:
        version = sw_probe.call(sw, "RevisionNumber")
        say(f"SolidWorks version: {version}  (that is SolidWorks {1992 + int(str(version).split('.')[0])})"
            + ("   [started by this script]" if started_by_us else "   [was already running]"))
    except Exception as e:
        say(f"Could not read the SolidWorks version: {e}")
    if signatures:
        say()
        tlib = load_typelib(sw)
        if tlib is None:
            say(f"Could not open SolidWorks' type library: {_STATE.get('typelib_error')}")
        else:
            say("Parameter lists of the calls the importer might use (from SolidWorks' own type library):")
            for line in describe_interface(tlib, "ISldWorks", ("MoveDocument", "CopyDocument", "ReplaceReferencedDocument")):
                say(f"  {line}")
            say("Meaning of the option and result codes:")
            constants = load_constants(sw) or tlib
            for enum in ("swMoveCopyOption_e", "swMoveCopyError_e"):
                lines_ = describe_enum(constants, enum)
                if "not found" in lines_[0]:
                    lines_ += [f"  (enums with 'MoveCopy' or 'Copy' in the name: {enum_names(constants, 'MoveCopy') + enum_names(constants, 'CopyDoc')})"]
                for line in lines_:
                    say(f"  {line}")

    mapping, statuses, problems = {}, [], []

    def make_names(originals):
        mapping.update(build_new_names(originals, dest, top=top))
        return mapping

    say()
    say("Making renamed copies:")
    model = None
    try:
        if open_original:
            model, error_code, warning_code = open_func(sw, top)
            say(f"  opened the original read-only: {'yes' if model else 'NO'} (error {error_code}, warning {warning_code})")
        if model or not open_original:
            statuses = pack_func(model, dest, make_names, say)
            say(f"  status codes: {statuses}")
    except Exception as e:
        problems.append(f"Pack and Go failed: {e!r}")
        say(f"  FAILED: {e!r}")
    finally:
        if model is not None:
            try:
                title = sw_probe.call(model, "GetTitle")
                sw.CloseDoc(title)
                say(f"  closed '{title}' without saving.")
            except Exception as e:
                say(f"  could not close the original ({e!r}). Close it in SolidWorks WITHOUT saving.")

    time.sleep(1)
    added, removed, modified = sw_probe.compare(before, sw_probe.snapshot(source))
    say()
    if added or removed or modified:
        problems.append("the ORIGINAL folder changed")
        say("ORIGINAL FOLDER CHECK FAILED:")
        for label, names in (("added", added), ("removed", removed), ("modified", modified)):
            for name in names:
                say(f"  {label}: {name}")
    else:
        say(f"Original folder check passed: all {len(before)} files unchanged.")

    created = sorted(os.listdir(dest)) if os.path.isdir(dest) else []
    say()
    say(f"New folder contains {len(created)} file(s):")
    for name in created:
        say(f"  {name}")
    for old, new in mapping.items():
        say(f"  {os.path.basename(old)}  ->  {os.path.basename(new)}")

    new_top = mapping.get(top)
    if new_top and os.path.exists(new_top):
        say()
        say("Opening the NEW assembly read-only to check its references:")
        dest_before = sw_probe.snapshot(dest)
        new_model = None
        try:
            dependencies = []
            try:
                dependencies = list(sw_probe.call(sw, "GetDocumentDependencies2", new_top, True, False, False) or [])
            except Exception as e:
                say(f"  could not list its dependencies: {e}")
            new_model, error_code, warning_code = open_func(sw, new_top)
            say(f"  opened: {'yes' if new_model else 'NO'} (error {error_code}, warning {warning_code})")
            components = sw_probe.describe_components(new_model, wrap) if new_model else []
            say(f"  components (all levels): {len(components)}")
            distinct = sorted({c['path'] for c in components if isinstance(c['path'], str)}, key=str.lower)
            say(f"  distinct files they point at: {len(distinct)}")
            for path in distinct:
                say(f"    {path}")
            problems += judge(components, dependencies, source, dest, mapping.values())
            if not new_model:
                problems.append("the new assembly would not open")
        except Exception as e:
            problems.append(f"checking the new assembly failed: {e!r}")
            say(f"  FAILED: {e!r}")
        finally:
            if new_model is not None:
                try:
                    title = sw_probe.call(new_model, "GetTitle")
                    sw.CloseDoc(title)
                    say(f"  closed '{title}' without saving.")
                except Exception as e:
                    say(f"  could not close it ({e!r}). Close it in SolidWorks WITHOUT saving.")
        time.sleep(1)
        a, r, m = sw_probe.compare(dest_before, sw_probe.snapshot(dest))
        if a or r or m:
            problems.append("opening the new assembly changed files in the new folder")
            say(f"  new folder changed while opening: added {a}, removed {r}, modified {m}")
    else:
        problems.append("the renamed assembly was not created, so its references could not be checked")

    say()
    if problems:
        say("RESULT: PROBLEMS FOUND")
        for p in problems:
            say(f"  - {p}")
    else:
        say("RESULT: PASSED. The renamed copies' references all point at each other, "
            "and the original folder is unchanged.")
    return lines


# ---------------------------------------------------------------------------
# Audit of an existing result (read-only)
# ---------------------------------------------------------------------------

def audit(top, sw, wrap=lambda x: x, open_func=com_open, log=print):
    """Read-only check of a folder of renamed copies: does ANY file still refer to something outside it?

    Looks at every file two ways: the references each file stores itself (without searching), and
    what SolidWorks loads when the top assembly is opened, all levels deep.
    """
    lines = []

    def say(text=""):
        lines.append(text)
        log(text)

    top = os.path.abspath(top)
    folder = os.path.dirname(top)
    before = sw_probe.snapshot(folder)
    cad = sorted(n for n in os.listdir(folder) if os.path.splitext(n)[1].lower() in DOC_TYPES)
    say(f"Auditing {len(cad)} CAD file(s) in {folder}")

    def stored(path, traverse):
        deps = sw_probe.call(sw, "GetDocumentDependencies2", path, traverse, False, False) or []
        return [p for p in list(deps)[1::2] if isinstance(p, str)]

    say()
    say("1. References each file stores itself (SolidWorks not allowed to search):")
    bad = 0
    for name in cad:
        try:
            outside = [p for p in stored(os.path.join(folder, name), False) if not is_inside(p, folder)]
        except Exception as e:
            say(f"  {name}: could not read ({e!r})")
            continue
        if outside:
            bad += 1
            say(f"  {name}: {len(outside)} stored reference(s) outside the folder, for example {outside[0]}")
    say(f"  => {bad} file(s) store references outside the folder." if bad
        else "  => no file stores a reference outside the folder.")

    say()
    say("2. Everything below the top assembly, all levels, as stored:")
    try:
        everything = stored(top, True)
        outside = sorted({p for p in everything if not is_inside(p, folder)})
        say(f"  {len(set(everything))} distinct file(s) listed; {len(outside)} outside the folder")
        for p in outside[:15]:
            say(f"    {p}")
    except Exception as e:
        say(f"  could not read ({e!r})")

    say()
    say("3. What SolidWorks loads when the top assembly is opened (read-only):")
    model = None
    try:
        model, error_code, warning_code = open_func(sw, top)
        say(f"  opened: {'yes' if model else 'NO'} (error {error_code}, warning {warning_code})")
        components = sw_probe.describe_components(model, wrap) if model else []
        outside = [c for c in components if not is_inside(c.get("path"), folder)]
        say(f"  {len(components)} component(s), all levels; {len(outside)} resolve to a file outside the folder")
        for c in outside[:15]:
            say(f"    {c['name']}: {c['path']}")
        renamed = sum(1 for c in components if os.path.basename(str(c.get("path"))).upper().startswith(PREFIX + "-"))
        say(f"  {renamed} of them load a renamed file ({PREFIX}-nnnnn-nnn)")
        names_old = sum(1 for c in components if not str(c.get("name", "")).upper().startswith(PREFIX + "-"))
        say(f"  {names_old} of them still show their OLD instance name in the feature tree. That name is stored in "
            "the assembly and is not the file name, so it does not by itself mean the file is wrong.")
    except Exception as e:
        say(f"  FAILED: {e!r}")
    finally:
        if model is not None:
            try:
                sw.CloseDoc(sw_probe.call(model, "GetTitle"))
                say("  closed without saving.")
            except Exception as e:
                say(f"  could not close ({e!r}). Close it in SolidWorks WITHOUT saving.")
    time.sleep(1)
    added, removed, modified = sw_probe.compare(before, sw_probe.snapshot(folder))
    say()
    say("Nothing in the folder changed." if not (added or removed or modified)
        else f"WARNING: the folder changed while auditing: added {added}, removed {removed}, modified {modified}")
    return lines


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _copy_runner(sw, top, option, model, dest, make_names, log):
    return com_copy_documents(sw, top, dest, make_names, log, option=option)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Litterbox: try renamed copies of an assembly through SolidWorks")
    parser.add_argument("assembly", help="the .SLDASM (or .SLDPRT) to copy under new names")
    parser.add_argument("--dest", default=r"C:\Litterbox\rename-test", help="a NEW folder for the renamed copies")
    parser.add_argument("--method", choices=("auto", "copydoc", "packandgo"), default="auto",
                        help="which SolidWorks feature to try (auto tries copydoc, then packandgo)")
    parser.add_argument("--audit", action="store_true",
                        help="only audit an existing result: give the NEW top assembly (e.g. TST-00001-001.SLDASM)")
    parser.add_argument("--option", type=int, default=0, help="the Option value passed to CopyDocument")
    parser.add_argument("--report", default="sw-rename-report.txt", help="where to save the report")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.assembly) or _extension(args.assembly) not in (".sldasm", ".sldprt"):
        print(f"ERROR: {args.assembly} is not an existing .SLDASM or .SLDPRT file.")
        return 1
    try:
        import win32com.client                            # noqa: F401
    except ImportError:
        print("ERROR: pywin32 is not installed. Run:  pip install pywin32")
        return 1
    try:
        sw, started = sw_probe.connect()
    except Exception as e:
        print(f"ERROR: could not connect to SolidWorks: {e}")
        return 1

    import win32com.client
    if args.audit:
        lines = audit(args.assembly, sw, wrap=win32com.client.Dispatch)
        Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nReport saved to {Path(args.report).resolve()}")
        return 0

    import functools
    methods = {
        "copydoc": ("CopyDocument + ReplaceReferencedDocument, children first", functools.partial(_copy_runner, sw, os.path.abspath(args.assembly), args.option)),
        "packandgo": ("Pack and Go", com_pack_and_go),
    }
    chosen = ["copydoc", "packandgo"] if args.method == "auto" else [args.method]
    lines = []
    for key in chosen:
        label, func = methods[key]
        lines += ([""] if lines else []) + [f"=== Method: {label} ==="]
        run = experiment(args.assembly, args.dest, sw, started, wrap=win32com.client.Dispatch, pack_func=func,
                         open_original=(key != "copydoc"))
        lines += run
        if any(line.startswith("RESULT: PASSED") for line in run):
            break
        if os.path.isdir(args.dest) and os.listdir(args.dest):
            lines.append("The destination folder now has files in it, so no other method was tried.")
            break
    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport saved to {Path(args.report).resolve()}")
    print("SolidWorks was left open. Close it when you like (do not save anything).")
    return 0


if __name__ == "__main__":
    sys.exit(main())