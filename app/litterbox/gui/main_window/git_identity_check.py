"""
git_identity_check.py - after a refresh, once per vault and session: if git doesn't know your name or email address
in this vault, ask for them (git can't commit without them); if it has a name other than yours on the team list,
offer the team list's. Either is set for this vault only (git/git_identity.py).
"""

from tkinter import messagebox

from litterbox.errors import LitterboxError
from litterbox.git import git_identity
from litterbox.gui.dialogs import git_identity_dialog
from litterbox.gui.logic import error_text
from litterbox.gui.logic import git_identity_text
from litterbox.team import team_identity


class GitIdentityCheck:
    """The name and email git uses in this vault. One part of the main window (App)."""

    def _check_git_identity(self):
        repo = self.repo()
        if not repo:
            return
        checked = self.__dict__.setdefault("_git_identity_checked", set())
        if repo in checked:
            return
        checked.add(repo)
        who = getattr(self, "identity", None)
        person = who.person if who is not None and who.state == team_identity.OK else None
        wanted = git_identity.wanted(git_identity.current(repo), person.name if person else "",
                                     person.email if person else "")
        if not wanted.needed:
            return
        answer = git_identity_dialog.GitIdentityDialog(self, wanted, self._org_name()).show()
        if not answer:
            if wanted.missing:
                self._say(git_identity_text.NOT_NOW, "warn")
            return
        try:
            name, email = git_identity.save(repo, *answer)
        except LitterboxError as e:
            messagebox.showerror("Litterbox", error_text.shorten(str(e)), parent=self)
            return
        self._say(f"Git now puts {name} <{email}> on your changes in this vault.")
