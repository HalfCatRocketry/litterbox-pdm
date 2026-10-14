"""
team_draft.py - team edits that are collected first and saved all at once.

Saving a change to the team goes through Git (lock, pull, commit, push, unlock) and takes several seconds. When
you are making several changes that is a lot of waiting, so the Team window works on a DRAFT instead:

    draft = TeamDraft(directory, templates, my_person_id)
    draft.stage_people("Add Bea", lambda d, who: people.add_person(d, who, "bea", "Bea Jones"))
    draft.stage_people("Roles", lambda d, who: people.set_roles(d, who, [...], scrub=True))
    draft.stage_workflow("Release workflow", lambda t, d: workflow.set_template(t, "release", [...]))
    draft.directory / draft.templates      what the window shows (the vault's state plus your staged changes)
    draft.save(repo)                       one commit for the team file, one for the workflow file

Each staged change is a function. It is tried on a copy straight away (so a mistake is reported at once, where
you are typing it) and kept. At save time the same functions are run again on the vault's newest files, so
changes other people saved meanwhile are kept, not overwritten.

A change function must capture ids and plain values, never the people objects of the draft's own copy.
"""

import copy

from litterbox.team import people
from litterbox.workflows import workflow
from litterbox.errors import LitterboxError, NothingToSaveError


class TeamDraft:
    def __init__(self, directory, templates, actor_id):
        self.directory = copy.deepcopy(directory)
        self.templates = copy.deepcopy(templates or {})
        self.actor_id = actor_id
        self.people_ops = []                # (label, change(directory, actor))
        self.workflow_ops = []              # (label, change(templates, directory))
        self.needs_owner = False            # a staged change only the Owner may make (handing over ownership)

    # -- what is waiting ------------------------------------------------------
    @property
    def dirty(self):
        return bool(self.people_ops or self.workflow_ops)

    @property
    def labels(self):
        return [label for label, _ in self.people_ops + self.workflow_ops]

    def summary(self):
        """'3 unsaved changes: Add Bea; Roles; Release workflow', or '' when there are none."""
        labels = self.labels
        if not labels:
            return ""
        return f"{len(labels)} unsaved change{'s' if len(labels) != 1 else ''}: " + "; ".join(labels)

    # -- staging --------------------------------------------------------------
    def stage_people(self, label, change, needs_owner=False):
        """Try `change(directory, actor)` on a copy of the draft; keep it if it works. Raises PeopleError (or
        WorkflowError, when it would leave the release workflow using a role that no longer exists)."""
        trial = copy.deepcopy(self.directory)
        actor = trial.get(self.actor_id)
        if actor is None:
            raise people.PeopleError("You are not on the team list any more. Close this window and press "
                                     "Get Latest.")
        change(trial, actor)
        people.validate(trial)
        if self.templates:
            workflow.validate(copy.deepcopy(self.templates), trial)
        self.directory = trial
        self.people_ops.append((label, change))
        self.needs_owner = self.needs_owner or needs_owner

    def stage_workflow(self, label, change):
        """Try `change(templates, directory)` on a copy of the draft's workflows; keep it if it works."""
        trial = copy.deepcopy(self.templates)
        change(trial, self.directory)
        workflow.validate(trial, self.directory)
        self.templates = trial
        self.workflow_ops.append((label, change))

    # -- saving ---------------------------------------------------------------
    def save(self, repo):
        """Upload everything staged: one commit for the team file, then one for the workflow file. Returns the
        labels that were saved. If it fails nothing from the failed step is lost (it stays staged); a step that
        already succeeded is not repeated."""
        saved, changed = [], False
        if self.people_ops:
            ops = list(self.people_ops)

            def change(directory, actor):
                for _label, func in ops:
                    func(directory, actor)

            try:
                people.edit_directory(repo, change, "Team: " + _short("; ".join(label for label, _ in ops)),
                                      action="transfer_owner" if self.needs_owner else "manage_people")
                changed = True
            except NothingToSaveError:              # the changes cancelled each other out
                pass
            saved += [label for label, _ in ops]
            self.people_ops, self.needs_owner = [], False
            self.directory = people.load(repo)          # the vault's file as it is now
        if self.workflow_ops:
            ops = list(self.workflow_ops)

            def change_templates(templates, directory):
                for _label, func in ops:
                    func(templates, directory)

            try:
                workflow.edit_templates(repo, change_templates, "Workflow: " + _short("; ".join(
                    label for label, _ in ops)))
                changed = True
            except NothingToSaveError:
                pass
            except LitterboxError as e:
                if saved:
                    raise LitterboxError(f"The team changes were saved, but the workflow change was not:\n\n{e}")
                raise
            saved += [label for label, _ in ops]
            self.workflow_ops = []
        self.templates = workflow.load(repo)
        if not changed:
            raise NothingToSaveError("Nothing was different from what is already saved in the vault, so "
                                         "there was nothing to save.")
        return saved


def _short(text, limit=100):
    return text if len(text) <= limit else text[:limit - 3] + "..."
