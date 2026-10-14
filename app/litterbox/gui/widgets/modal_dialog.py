"""
modal_dialog.py - ModalDialog: what every Litterbox dialog has in common.

A dialog takes the focus and keeps it until it is closed (_grab, called once the window is shown), and show() waits
for it to close and returns its answer (self.result). Set FOCUS to the name of a text box to put the cursor in it.
"""

import tkinter as tk

import customtkinter as ctk


class ModalDialog(ctk.CTkToplevel):
    FOCUS = None                # e.g. "entry": the attribute holding the text box that gets the cursor

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            if self.FOCUS:
                getattr(self, self.FOCUS).focus_set()
        except tk.TclError:
            pass

    def show(self):
        """Wait for the user to answer, and return the answer (self.result)."""
        self.wait_window(self)
        return self.result
