"""
template_store.py - where the vault keeps its SolidWorks templates (core/template_rules.py): the files in its
templates/ folder (layout.TEMPLATES_DIR_NAME, stored with Git LFS by their extensions: vault/git_attributes.py), and
templates/templates.yaml (layout.TEMPLATES_INDEX) saying which is which:

    version: 1
    templates:
    - {file: HCR drawing.drwdot, kind: drawing, default: true}
    - {file: Rover A3.drwdot, kind: drawing, project: Rover, default: true}

Changing them (Team > Templates...) is vault/template_admin.py; who may is vault/template_access.py. An older
Litterbox doesn't know the folder and leaves it alone, so it needs no newer minimum version.

    templates = template_store.load(repo)                      # [Template]
    template_store.path(repo, template)                        # its file on this computer
"""

from pathlib import Path

import yaml

from litterbox import diagnostics
from litterbox import layout
from litterbox.core import file_types
from litterbox.core import template_rules
from litterbox.util import fast_yaml

VERSION = 1


def folder(repo):
    return Path(repo) / layout.TEMPLATES_DIR_NAME


def rel_path(template):
    """A template's file relative to the vault: "templates/HCR drawing.drwdot"."""
    return f"{layout.TEMPLATES_DIR_NAME}/{template.file}"


def path(repo, template):
    return Path(repo) / rel_path(template)


def parse(text):
    """[Template] from the index file's text. What can't be read is left out (and logged), never fatal."""
    try:
        data = fast_yaml.safe_load(text) if text and text.strip() else {}
    except yaml.YAMLError as e:
        diagnostics.LOG(f"WARNING: the vault's list of templates can't be read: {e}")
        return []
    found = []
    entries = data.get("templates") if isinstance(data, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        file = str(entry.get("file") or "").strip()
        kind = file_types.template_kind(file)
        if not file or kind is None or template_rules.find(found, file) is not None:
            continue
        found.append(template_rules.Template(file, kind, str(entry.get("project") or ""), bool(entry.get("default"))))
    return template_rules.normalized(found)


def load(repo):
    """The vault's templates as this computer has them ([] for none)."""
    try:
        text = (Path(repo) / layout.TEMPLATES_INDEX).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        diagnostics.LOG(f"WARNING: the vault's list of templates can't be read: {e}")
        return []
    return parse(text)


def dump(templates):
    """The index file's text for these templates."""
    entries = []
    for t in sorted(templates, key=lambda t: (t.project.lower(), template_rules.KINDS.index(t.kind), t.file.lower())):
        entry = {"file": t.file, "kind": t.kind}
        if t.project:
            entry["project"] = t.project
        entry["default"] = t.default
        entries.append(entry)
    return yaml.safe_dump({"version": VERSION, "templates": entries}, sort_keys=False, allow_unicode=True)


def save(repo, templates):
    target = Path(repo) / layout.TEMPLATES_INDEX
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.write(dump(templates))


def changed_owners(before, after, changed_paths):
    """Whose templates a change touches: {project name, or template_rules.ORG for the org's}. `before` and `after`
    are the templates either side of it, `changed_paths` the paths it changes (relative to the vault). A template
    added, removed, made the default or moved counts for its owner both before and after; a changed file for the
    owner of its template (the org's, if no template is that file)."""
    old = {t.file.lower(): t for t in before}
    new = {t.file.lower(): t for t in after}
    owners = set()
    for name in set(old) | set(new):
        if old.get(name) != new.get(name):
            owners |= {t.project for t in (old.get(name), new.get(name)) if t is not None}
    prefix = layout.TEMPLATES_DIR_NAME.lower() + "/"
    for rel in changed_paths:
        rel = rel.replace("\\", "/")
        if not rel.lower().startswith(prefix) or rel.lower() == layout.TEMPLATES_INDEX.lower():
            continue
        name = rel[len(prefix):].lower()
        template = new.get(name) or old.get(name)
        owners.add(template.project if template is not None else template_rules.ORG)
    return owners
