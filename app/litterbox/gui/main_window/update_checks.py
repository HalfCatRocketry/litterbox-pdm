"""
update_checks.py - looking for a newer Litterbox at start-up, and installing it (see user/updater.py). Also keeps what
a check learns from the signed notices (keys withdrawn, releases moved) in the settings, and Help > Get beta versions.
"""

import threading
from tkinter import messagebox

from litterbox import version
from litterbox.errors import LitterboxError
from litterbox.gui.logic import update_text
from litterbox.user import settings
from litterbox.user import updater


class UpdateChecks:
    """Looking for a newer Litterbox at start-up, and installing it (see user/updater.py). One part of the main window
    (App)."""

    def _look_for_update(self):
        """updater.check with this computer's settings: where releases are, the channel, the keys withdrawn."""
        return updater.check(repo=settings.update_repo(self.settings), channel=settings.update_channel(self.settings),
                             revoked=settings.revoked_update_keys(self.settings))

    def _start_update_check(self):
        """On start-up, quietly look for a newer release. Only the installed program does; never blocks the window."""
        if not (version.is_installed_build() and updater.configured() and settings.update_check_enabled(self.settings)):
            return

        def work():
            found = self._look_for_update()
            self.queue.put(("call", lambda: self._update_found(found, quiet=True)))

        threading.Thread(target=work, daemon=True).start()

    def check_for_updates(self):
        """The 'check for updates' button: same check, but says what it found."""
        if not version.is_installed_build():
            messagebox.showinfo("Litterbox", "This copy is running from the source files, so it doesn't update "
                                "itself. The installed program checks GitHub for new releases.")
            return
        if not updater.configured():
            messagebox.showinfo("Litterbox", "This build isn't set up to check for updates.")
            return
        self.run_task(self._look_for_update, "Checked for updates", on_success=self._update_found, refresh=False)

    def _update_found(self, found, quiet=False):
        """Keep what the notices said, then offer the update (or, when asked, say why there is none)."""
        if settings.remember_update_notices(self.settings, found.revoked, found.moved_to):
            settings.save(self.settings)
        if found.moved_to:
            self._log(update_text.moved(found.moved_to))
            if not quiet:
                messagebox.showinfo("Litterbox", update_text.moved(found.moved_to))
        if found.revoked:
            self._log(update_text.REVOKED)
        if found.problem:
            if quiet:                                   # offline, or nothing to offer: stay quiet
                self._log(f"Update check: {found.problem}")
                return
            messagebox.showwarning("Litterbox", found.problem)
            return
        if found.update is None:
            if not quiet:
                messagebox.showinfo("Litterbox", update_text.newest(version.VERSION))
            return
        self._offer_update(found.update)

    def _offer_update(self, update):
        if update is None:
            return
        if messagebox.askyesno("Litterbox update", update_text.offer(update.version, version.VERSION, update.notes,
                                                                     version.is_beta(update.version))):
            self.install_update(update)

    def toggle_beta_versions(self):
        """Help > Get beta versions: switch between being offered releases only and releases and betas."""
        if settings.update_channel(self.settings) == updater.BETA:
            self.settings.pop("update_channel", None)
            text = update_text.BETA_OFF
        else:
            if not messagebox.askyesno("Get beta versions", update_text.BETA_QUESTION, parent=self):
                return
            self.settings["update_channel"] = updater.BETA
            text = update_text.BETA_ON
        settings.save(self.settings)
        messagebox.showinfo("Litterbox", text, parent=self)

    def install_update(self, update):
        def work():
            try:
                return updater.download(update)
            except updater.UpdateError as e:
                raise LitterboxError(str(e))

        self.run_task(work, "Downloaded the update", on_success=self._run_installer, refresh=False)

    def _run_installer(self, path):
        try:
            updater.launch_installer(path)
        except updater.UpdateError as e:
            messagebox.showerror("Litterbox", str(e))
            return
        self._say("Updating... Litterbox will start again by itself.")
        self.after(500, self.destroy)               # the installer replaces the program's files once we've closed
