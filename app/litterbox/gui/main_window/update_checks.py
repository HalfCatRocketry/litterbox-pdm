"""
update_checks.py - looking for a newer Litterbox at start-up, and installing it (see user/updater.py).
"""

import threading
from tkinter import messagebox

from litterbox import version
from litterbox.errors import LitterboxError
from litterbox.user import settings
from litterbox.user import updater


class UpdateChecks:
    """looking for a newer Litterbox at start-up, and installing it (see user/updater.py). (a part of the main window, App)."""

    def _start_update_check(self):
        """On start-up, quietly look for a newer release. Only the installed program does; never blocks the window."""
        if not (version.is_installed_build() and updater.configured() and settings.update_check_enabled(self.settings)):
            return

        def work():
            try:
                self.queue.put(("update", updater.find_update()))
            except updater.UpdateError as e:                  # offline, or nothing to offer: stay quiet
                self.queue.put(("log", f"Update check: {e}"))

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

        def work():
            try:
                return updater.find_update()
            except updater.UpdateError as e:
                raise LitterboxError(str(e))

        def show(update):
            if update is None:
                messagebox.showinfo("Litterbox", f"You have the newest version ({version.VERSION}).")
            else:
                self._offer_update(update)

        self.run_task(work, "Checked for updates", on_success=show, refresh=False)

    def _offer_update(self, update):
        if update is None:
            return
        notes = f"\n\n{update.notes}" if update.notes else ""
        if messagebox.askyesno("Litterbox update", f"Litterbox {update.version} is available. You have "
                               f"{version.VERSION}.{notes}\n\nUpdate now? Litterbox will close, update and "
                               "start again. Your settings and vault are not touched."):
            self.install_update(update)

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
