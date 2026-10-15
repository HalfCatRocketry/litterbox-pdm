"""
import_plan.py - working out an import: which files each item brings, what they reference, the order to
copy them in (parts before the assemblies that use them), and where each copy goes in the vault.
"""

import os
from dataclasses import dataclass, field

from litterbox.cad import file_types
from litterbox.cad.solidworks import sw_errors
from litterbox.core import filenames
from litterbox.core import part_number
from litterbox.core import revision_letters
from litterbox.importing import import_copying
from litterbox.importing import import_errors
from litterbox.importing import import_paths
from litterbox.records import record_store


@dataclass
class Plan:
    """What an import will do (built without writing anything)."""
    items: list
    specs: list
    pns: list
    copies: dict            # original path -> new path in cad\
    order: list             # original paths, in the order they must be copied
    repoints: dict          # original path -> [(stored reference, new target path)]
    external: list = field(default_factory=list)      # (original path, reference left pointing outside)
    kept: dict = field(default_factory=dict)          # original path key -> keys of stored references left as they were
    warnings: list = field(default_factory=list)


@dataclass
class Result:
    pns: list = field(default_factory=list)
    files: list = field(default_factory=list)         # relative paths of the CAD files added
    warnings: list = field(default_factory=list)
    plan: Plan = None
    dry_run: bool = False
    version: str = ""
    renumbered: list = field(default_factory=list)    # (row, old PN, new PN) automatic numbers replaced at the end


def _cad_target(repo, pn, original_path):
    return str(record_store.cad_dir(repo) / filenames.filename(pn, revision_letters.FIRST_REVISION, import_paths.ext_of(original_path)))


def item_files(item):
    return [f.path for f in item.files]


def read_references(items, backend, progress=None, cancel=None):
    """{key: (path, [(stored, found)])} for every file in the import."""
    paths = [p for item in items for p in item_files(item)]
    refs = {}
    for number, path in enumerate(paths, start=1):
        import_copying.check_cancel(cancel)
        if progress:
            progress(number, len(paths), f"Reading references: {os.path.basename(path)}")
        try:
            refs[import_paths.path_key(path)] = (path, backend.references(path))
        except (import_errors.ImportFailed, sw_errors.SolidWorksError):     # already says what went wrong
            raise
        except Exception as e:
            raise import_errors.ImportFailed(f"Could not read the references of {path}:\n{e}") from e
    return refs


def _order(items, refs):
    """The original files in copy order: models before what uses them, then the drawings."""
    in_set = {import_paths.path_key(p): p for item in items for p in item_files(item)}
    models = [p for p in in_set.values() if import_paths.ext_of(p) in file_types.MODEL_EXTENSIONS]
    drawings = [p for p in in_set.values() if import_paths.ext_of(p) == file_types.DRAWING_EXTENSION]
    others = [p for p in in_set.values() if p not in models and p not in drawings]
    order, done = [], set()

    def visit(path, trail):
        key = import_paths.path_key(path)
        if key in done:
            return
        if key in trail:
            raise import_errors.ImportFailed(f"{path} ends up referencing itself, so there is no order to copy these files in.")
        for _stored, found in refs[key][1]:
            if found and import_paths.path_key(found) in in_set and import_paths.ext_of(found) in file_types.MODEL_EXTENSIONS:
                visit(in_set[import_paths.path_key(found)], trail | {key})
        done.add(key)
        order.append(path)

    for path in sorted(models, key=lambda p: p.lower()):
        visit(path, frozenset())
    return order + sorted(others, key=lambda p: p.lower()) + sorted(drawings, key=lambda p: p.lower())


def build_plan(repo, items, specs, pns, refs, manifest, allow_external=False):
    """Work out where every file goes and which references to change. Raises ImportFailed for blockers."""
    copies = {}
    for item, pn in zip(items, pns):
        for path in item_files(item):
            copies[import_paths.path_key(path)] = _cad_target(repo, pn, path)
    new_paths = set(copies.values())
    clash = [p for p in new_paths if os.path.exists(p)]
    if clash:
        raise import_errors.ImportFailed("These files are already in the vault's cad folder, and Litterbox will not overwrite "
                           "them:\n" + "\n".join(clash[:8]))

    # Files imported earlier (their items already have a pn) are valid targets too.
    known = dict(copies)
    for item in manifest.items:
        if item.pn:
            pn = part_number.try_parse(item.pn)
            for path in item_files(item):
                target = _cad_target(repo, pn, path) if pn else None
                if target and os.path.exists(target):
                    known.setdefault(import_paths.path_key(path), target)

    order = _order(items, refs)
    repoints, external, warnings, kept = {}, [], [], {}
    for path in order:
        entries = []
        kept[import_paths.path_key(path)] = set()
        for stored, found in refs[import_paths.path_key(path)][1]:
            name = os.path.basename(path)
            if not found or not os.path.exists(found):
                warnings.append(f"{name} references {os.path.basename(stored)}, which can't be found anywhere. "
                                "That reference is left as it is.")
                kept[import_paths.path_key(path)].add(import_paths.path_key(stored))
                continue
            target = known.get(import_paths.path_key(found))
            if target is None:
                external.append((path, found))
                kept[import_paths.path_key(path)].add(import_paths.path_key(stored))
                continue
            if import_paths.path_key(stored) != import_paths.path_key(found) and os.path.exists(stored):
                warnings.append(f"{name} says it uses {stored}, but SolidWorks finds {found}. "
                                "Check that the copy uses the file you expect.")
            entries.append((stored, target))
        repoints[import_paths.path_key(path)] = entries
    if external and not allow_external:
        lines = sorted({f"{os.path.basename(p)} -> {ref}" for p, ref in external})
        more = f"\n...and {len(lines) - 8} more" if len(lines) > 8 else ""
        raise import_errors.ExternalReferences(
            f"{len(lines)} reference(s) point at files that are not part of this import:\n"
            + "\n".join(lines[:8]) + more +
            "\n\nInclude those files in the import, or go ahead anyway (the copies would still depend on "
            "the original files).", sorted({(p, ref) for p, ref in external}))
    if external:
        warnings.append(f"{len(external)} reference(s) were left pointing at files outside the import.")
    return Plan(items=items, specs=specs, pns=pns, copies={p: copies[import_paths.path_key(p)] for p in order}, order=order,
                repoints=repoints, external=external, warnings=warnings, kept=kept)
