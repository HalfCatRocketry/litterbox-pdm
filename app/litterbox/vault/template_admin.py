"""
template_admin.py - changing the vault's SolidWorks templates (Team > Templates...): adding a template to the org or
a project (a copy of the file goes in the vault's templates/ folder: the org's at its top, a project's in the
project's folder), removing one, and choosing the default. Each change is one commit, uploaded at once; if it can't
be uploaded it is taken back, so nothing is left half done.

    template = template_admin.add(repo, r"C:\\Templates\\Rover A3.drwdot", project="Rover")
    template_admin.make_default(repo, template.key)                 # "Rover/Rover A3.drwdot"
    template_admin.remove(repo, template.key)
    template_admin.download(repo, templates)            # before a template is used: Git LFS may have only a pointer

Who may is vault/template_access.py (and team/guarded_push.templates_allowed refuses anyone else's upload). What the
templates are is core/template_rules.py; where they are kept, vault/template_store.py.
"""

import shutil
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.core import projects as project_rules
from litterbox.core import template_rules
from litterbox.errors import LitterboxError
from litterbox.git import committing
from litterbox.git import lfs_download
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.records.error_conversion import converts_errors
from litterbox.team import guarded_push
from litterbox.team import team_identity
from litterbox.vault import config
from litterbox.vault import template_access
from litterbox.vault import template_store


def check_may(repo, project=template_rules.ORG):
    """Raise LitterboxError if you may not change the org's templates (ORG) or this project's. Returns the
    project's name as the vault spells it (ORG for the org)."""
    identity = team_identity.current(repo, probe=False)
    if identity.state == team_identity.UNVERIFIED:             # not known on this computer yet: ask the host once
        identity = team_identity.current(repo)
    found = None
    if project:
        try:
            found = project_rules.find(project, config.get_projects(repo))
        except project_rules.ProjectError:
            raise LitterboxError(f"There is no project called {project} in this vault any more.") from None
    allowed, why = template_access.may_change(identity, found)
    if not allowed:
        raise LitterboxError(why)
    return found.name if found else template_rules.ORG


@converts_errors
def add(repo, source, project=template_rules.ORG):
    """Copy the template file `source` into the vault for the org (ORG) or a project, and upload it. It becomes the
    default if it is the first of its kind there. Returns its Template."""
    source = Path(source)
    project = check_may(repo, project)
    file = template_rules.check_file_name(source.name)
    if not source.is_file():
        raise LitterboxError(f"{source} isn't there any more.")
    remote.pull(repo)
    templates = template_rules.added(template_store.load(repo), file, project)
    template = template_rules.find(templates, template_rules.Template(file, "", project).key)
    target = template_store.path(repo, template)
    if target.exists():
        raise LitterboxError(f"The vault's templates folder already has a file {template.key} that isn't one of its "
                             "templates. Rename yours and add it again.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    rel = template_store.rel_path(template)
    try:
        template_store.save(repo, templates)
        _commit(repo, [rel], f"Templates: {template.name} added for {template_rules.owner_text(project)}", new=[rel])
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return template


def _existing(repo, key):
    """(every template, the one with this key) after getting the latest; LitterboxError if it is gone."""
    remote.pull(repo)
    templates = template_store.load(repo)
    template = template_rules.find(templates, key)
    if template is None:
        raise LitterboxError(f"{key} isn't one of the vault's templates any more. Someone may have just removed it.")
    return templates, template


@converts_errors
def remove(repo, key):
    """Take a template out of the vault (and upload that). Files already made from it are not touched."""
    templates, template = _existing(repo, key)
    check_may(repo, template.project)
    rel = template_store.rel_path(template)
    remaining = template_rules.removed(templates, template.key)
    tracked = repository.in_index(repo, rel)
    if tracked:
        runner.run(["git", "rm", "-q", "--", rel], repo)       # a commit of a path takes what the folder has
    try:
        template_store.save(repo, remaining)
        _commit(repo, [rel] if tracked else [], f"Templates: {template.name} removed from "
                                                f"{template_rules.owner_text(template.project)}")
    except BaseException:
        if tracked:
            _put_back(repo, [rel])
        raise


@converts_errors
def make_default(repo, key):
    """Make a template the default of its kind for its owner (the org or its project), and upload that."""
    templates, template = _existing(repo, key)
    check_may(repo, template.project)
    if template.default:
        return
    template_store.save(repo, template_rules.made_default(templates, template.key))
    _commit(repo, [], f"Templates: {template.name} is the default for {template_rules.owner_text(template.project)}")


def rename_project(repo, old, new):
    """A renamed project keeps its templates: one upload that moves its folder and its entries to its new name (if
    it had any)."""
    templates = template_store.load(repo)
    if not any(t.project and t.project.lower() == old.lower() for t in templates):
        return
    before, after = template_store.project_folder(old), template_store.project_folder(new)
    moved = before != after and (Path(repo) / before).is_dir()
    if moved:
        if before.lower() == after.lower():                     # only capitals: Windows needs a step between
            runner.run(["git", "mv", "--", before, before + "-renaming"], repo)
            runner.run(["git", "mv", "--", before + "-renaming", after], repo)
        else:
            runner.run(["git", "mv", "--", before, after], repo)
    try:
        template_store.save(repo, template_rules.renamed_project(templates, old, new))
        _commit(repo, [before, after] if moved else [], f"Templates: project {old} renamed to {new}")
    except BaseException:
        if moved:
            try:
                runner.run(["git", "reset", "-q", "--", before, after], repo)
                shutil.rmtree(Path(repo) / after, ignore_errors=True)
                runner.run(["git", "checkout", "--", before], repo)
            except LitterboxError as e:
                diagnostics.LOG(f"WARNING: {before} couldn't be put back: {e}")
        raise


def _put_back(repo, paths):
    try:
        runner.run(["git", "reset", "-q", "--", *paths], repo)
        runner.run(["git", "checkout", "--", *paths], repo)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: {', '.join(paths)} couldn't be put back: {e}")


def _commit(repo, paths, message, new=()):
    """Commit the index file and these paths in one commit and upload it. If anything fails before the upload is
    done, the commit and the index file are put back (and `new` files unstaged), and the error raised."""
    index = layout.TEMPLATES_INDEX
    paths = [index] + list(paths)
    committed = False
    try:
        runner.run(["git", "add", "--", *[p for p in paths if p == index or p in new]], repo)
        committing.commit_paths(repo, message, "", paths)
        committed = True
        guarded_push.push(repo)
    except BaseException:
        try:
            if committed and runner.run(["git", "log", "-1", "--format=%s"], repo, quiet=True) == message:
                runner.run(["git", "reset", "-q", "--soft", "HEAD~1"], repo)
            runner.run(["git", "reset", "-q", "--", *paths], repo)
            if repository.in_head(repo, index):
                runner.run(["git", "checkout", "--", index], repo)
            else:
                (Path(repo) / index).unlink(missing_ok=True)
        except LitterboxError as e:
            diagnostics.LOG(f"WARNING: a template change couldn't be fully taken back: {e}")
        raise


@converts_errors
def download(repo, templates):
    """Download these templates' files where this computer has only Git LFS pointers. Returns how many."""
    return len(lfs_download.download(repo, [template_store.rel_path(t) for t in templates], "templates"))
