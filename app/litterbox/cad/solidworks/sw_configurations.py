"""
sw_configurations.py - a SolidWorks model's configurations (for sw_backend.py): reading them, with SolidWorks' ID
for each, the active one, each one's material and any outside file a design table or the equations are linked to;
and renaming one after the part (core/configuration_names.py).

Seen with SolidWorks 2024 (tools: scratch copies of vault parts):
- Configuration.GetID is 0 for the first configuration, then 1, 2 ... and stays with it when it is renamed.
- An assembly follows a renamed configuration (it keeps the ID): closed while the part was renamed, it opens with
  the new name (and SolidWorks then counts it as changed); open, it changes with the part.
- An assembly whose configuration was deleted quietly shows the part's active configuration instead.
- Setting Configuration.Name to a name with "/" or "@", or with spaces at either end, does nothing.
- BOMPartNoSource was 1 (the configuration's name is the part number in a SolidWorks BOM) in the vault's parts. A
  configuration named after the part would put its Name in the BOM, so renaming sets it to 2 (the document's name,
  which is the part number).
- GetDesignTable gives an object even for a part with none (its title is "" and LinkToFile False).
"""

from litterbox.cad.solidworks import com

BOM_FROM_CONFIGURATION_NAME, BOM_FROM_DOCUMENT_NAME = 1, 2      # swBOMPartNumberSource_e


def _material(model, name):
    import pythoncom
    from win32com.client import VARIANT
    database = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    try:
        return str(model.GetMaterialPropertyName2(name, database) or "").strip()
    except Exception:
        return ""


def _linked_files(model):
    """Outside files the model's design table or equations are linked to."""
    found = []
    try:
        table = com.call(model, "GetDesignTable")
        if table is not None and com.call(table, "GetTitle") and com.call(table, "LinkToFile"):
            path = ""
            for member in ("FileName", "GetFileName"):
                try:
                    path = str(com.call(table, member) or "")
                    break
                except Exception:
                    continue
            found.append(path or "a linked Excel design table")
    except Exception:
        pass
    try:
        equations = com.call(model, "GetEquationMgr")
        if equations is not None and com.call(equations, "LinkToFile"):
            found.append(str(com.call(equations, "FilePath") or "") or "a linked equations file")
    except Exception:
        pass
    return found


def read(model, part):
    """{"own": [{name, id}], "active": name, "materials": {name: material} (parts only), "linked": [file]}."""
    own = []
    for name in list(com.call(model, "GetConfigurationNames") or []):
        try:
            number = int(com.call(model.GetConfigurationByName(name), "GetID"))
        except Exception:
            number = None
        own.append({"name": str(name), "id": number})
    try:
        active = str(com.call(com.call(com.call(model, "ConfigurationManager"), "ActiveConfiguration"), "Name"))
    except Exception:
        active = ""
    materials = {c["name"]: _material(model, c["name"]) for c in own} if part else {}
    return {"own": own, "active": active, "materials": materials, "linked": _linked_files(model)}


def rename(model, old, new):
    """Rename configuration `old` to `new` in an open, writable model (not saved here). Its BOM part number becomes
    the document's name if it was the configuration's name. Raises ValueError if SolidWorks refuses the name."""
    config = model.GetConfigurationByName(old)
    if config is None:
        raise ValueError(f"it has no configuration called {old}")
    try:
        if int(com.call(config, "BOMPartNoSource")) == BOM_FROM_CONFIGURATION_NAME:
            config.BOMPartNoSource = BOM_FROM_DOCUMENT_NAME
    except Exception:
        pass
    config.Name = new
    if str(com.call(config, "Name")) != new:
        raise ValueError(f"SolidWorks wouldn't call a configuration {new!r}")
