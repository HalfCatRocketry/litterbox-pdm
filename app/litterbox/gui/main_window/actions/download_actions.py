"""
download_actions.py - Download All and Repair Files (Vault menu): getting the vault's CAD files onto this computer,
and putting back the vault's copy of files that went wrong here (parts/downloads.py, parts/file_repair.py).
"""

from tkinter import messagebox

from litterbox.gui.logic import download_text
from litterbox.parts import downloads
from litterbox.parts import file_repair


class DownloadActions:
    """Download All and Repair Files. One part of the main window (App)."""

    def download_all(self):
        """Download every CAD file of the vault, not just the ones you use. Get Latest then keeps them all current."""
        if not messagebox.askyesno("Download All", download_text.DOWNLOAD_ALL_QUESTION, parent=self):
            return
        repo = self.repo()
        self.run_task(lambda: downloads.download_all(repo), "Downloaded every CAD file", label="Downloading everything")

    def repair_files(self):
        """Repair Files (Vault menu): find the files that don't match the vault's copy and that you don't have checked
        out, ask, then put back the vault's copy of each and download it again (parts/file_repair.py)."""
        repo = self.repo()
        parent = self._popup_parent()

        def found(files):
            if not files:
                messagebox.showinfo("Repair Files", download_text.REPAIR_NOTHING, parent=parent)
                return
            if not messagebox.askyesno("Repair Files", download_text.repair_question(files), icon="warning",
                                       parent=parent):
                return
            self.run_task(lambda: file_repair.repair(repo, files), "", on_success=repaired, label="Repairing files")

        def repaired(result):
            title, text, problem = download_text.repair_summary(result)
            (messagebox.showwarning if problem else messagebox.showinfo)(title, text, parent=parent)

        self.run_task(lambda: file_repair.find(repo), "", on_success=found, refresh=False,
                      label="Looking for damaged files")
