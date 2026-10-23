"""
review_dialog.py - My Tasks' Review window: a request as it was asked (its parts with what changed and the Dispo,
the workflow, who signs, the ECO), read-only, with Open buttons for each part's drawing and PDF (the new revision
and the one before), a Reassign button beside each of your own sign-offs, an optional comment, and Approve, Reject
and Reassign. The rules for those buttons are gui/logic/review_text.py's.
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs.workflow import reassign_dialog
from litterbox.gui.logic import review_text
from litterbox.gui.widgets import change_table
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.workflows import workflow_templates

SIGNOFF_WIDTH = 600


class ReviewDialog(modal_dialog.ModalDialog):
    """Review a request (workflows/workflow_tasks.Task). show() gives None (closed) or {"answer": "approve",
    "reject" or "reassign", "handed": {slot index: person id}, "comment": text}. `eco` is its ECO
    (change_orders/eco_model.Eco) or None; on_open(PN, revision, "drawing" or "pdf") opens a part's file."""

    def __init__(self, parent, task, directory, my_id, eco=None, on_open=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.task, self.directory, self.my_id = None, task, directory, my_id
        self.on_open = on_open
        self.handed, self.handed_names = {}, {}
        label = workflow_templates.label_of(task.action)
        width, height = 1060, 800
        self.title(f"{label} workflow")
        window_chrome.place_over(self, parent, width, height, down=4)
        self.minsize(900, 620)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=f"{label}: review", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        self._parts_box(row=1)
        self._summary(row=2)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=3, column=0, sticky="nsew", padx=20, pady=(8, 0))
        self.rowconfigure(3, weight=1)
        body.rowconfigure(0, weight=1)
        self.holder = ctk.CTkScrollableFrame(body, fg_color=theme.BG_PANEL, corner_radius=10, width=SIGNOFF_WIDTH)
        self.holder.grid(row=0, column=0, sticky="nsew")
        self.holder.columnconfigure(1, weight=1)
        if eco is not None:
            self._eco_panel(body, eco)
            body.columnconfigure(1, weight=1)
        else:
            body.columnconfigure(0, weight=1)
        comment = ctk.CTkFrame(self, fg_color="transparent")
        comment.grid(row=4, column=0, sticky="ew", padx=20, pady=(10, 0))
        comment.columnconfigure(1, weight=1)
        ctk.CTkLabel(comment, text="Comment:").grid(row=0, column=0, padx=(0, 8))
        self.comment_var = tk.StringVar(value="")
        ctk.CTkEntry(comment, textvariable=self.comment_var, height=32,
                     placeholder_text="Optional when you approve; required to reject (the person who asked sees it)").grid(
            row=0, column=1, sticky="ew")
        self.problem = ctk.CTkLabel(self, text=review_text.why_not(task, task.my_slots), text_color=theme.MUTED,
                                    anchor="w", justify="left", wraplength=width - 40)
        self.problem.grid(row=5, column=0, sticky="ew", padx=20, pady=(4, 0))
        self._buttons(row=6)
        self._draw_slots()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    # -- the parts -------------------------------------------------------------
    def _parts_box(self, row):
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=row, column=0, sticky="ew", padx=20)
        frame.columnconfigure(0, weight=1)
        parts = [(pn, name, rev, self.task.earlier.get(str(pn), "")) for pn, name, rev in self.task.parts]
        self.table = change_table.ChangeTable(frame, self.task.action, parts, self.task.changes, read_only=True)
        self.table.ask_changes(bool(self.task.eco))            # Form, Fit, Function and Dispo come with an ECO
        self.parts_tree = self.table.tree
        self.parts_tree.grid(row=0, column=0, sticky="ew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.parts_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.parts_tree.configure(yscrollcommand=scroll.set)
        side = ctk.CTkFrame(frame, fg_color="transparent")
        side.grid(row=0, column=2, sticky="n", padx=(4, 8), pady=8)
        for number, (text, earlier, kind) in enumerate((("Open Drawing", False, "drawing"), ("Open PDF", False, "pdf"),
                                                        ("Previous Drawing", True, "drawing"),
                                                        ("Previous PDF", True, "pdf"))):
            release_button.ReleaseButton(side, text=text, width=140, height=28, fg_color=theme.GRAY,
                                         hover_color=theme.GRAY_HOVER,
                                         command=lambda e=earlier, k=kind: self._open(e, k)).grid(
                row=number, column=0, pady=(0, 4))
        if parts:
            self.parts_tree.selection_set(str(parts[0][0]))

    def _open(self, earlier, kind):
        """Open the selected part's drawing or PDF: the revision it goes through, or the one released before."""
        chosen = self.table.selection()
        part = next((p for p in self.table.parts if str(p[0]) == (chosen[0] if chosen else None)), None)
        if part is None:
            self.problem.configure(text="Select a part in the list first.", text_color=theme.ERROR)
            return
        revision = part[3] if earlier else part[2]
        if not revision:
            self.problem.configure(text=f"{part[0]} has no earlier released revision.", text_color=theme.ERROR)
            return
        if self.on_open:
            self.on_open(part[0], revision, kind)

    # -- the request -----------------------------------------------------------
    def _summary(self, row):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=20, pady=(10, 0))
        frame.columnconfigure(1, weight=1)
        for number, (label, text) in enumerate(review_text.summary_lines(self.task)):
            ctk.CTkLabel(frame, text=label + ":", text_color=theme.MUTED, anchor="w").grid(
                row=number, column=0, sticky="nw", padx=(0, 10))
            ctk.CTkLabel(frame, text=text, anchor="w", justify="left", wraplength=900).grid(
                row=number, column=1, sticky="w")

    def _eco_panel(self, parent, eco):
        frame = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        ctk.CTkLabel(frame, text=f"Engineering change order ({eco.number})", font=ctk.CTkFont(weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(frame, text="Title:", text_color=theme.MUTED, anchor="w").grid(row=1, column=0, sticky="w",
                                                                                   padx=10, pady=(4, 0))
        ctk.CTkLabel(frame, text=eco.name, anchor="w", justify="left", wraplength=380).grid(row=2, column=0,
                                                                                           sticky="w", padx=10)
        ctk.CTkLabel(frame, text="Description:", text_color=theme.MUTED, anchor="w").grid(row=3, column=0, sticky="nw",
                                                                                         padx=10, pady=(6, 0))
        description = ctk.CTkTextbox(frame, height=70, wrap="word")
        description.grid(row=4, column=0, sticky="nsew", padx=10, pady=(0, 10))
        description.insert("1.0", eco.description or "(no description)")
        description.configure(state="disabled")

    def _draw_slots(self):
        for child in self.holder.winfo_children():
            child.destroy()
        for number, slot in enumerate(self.task.slots):
            pady = (8 if number == 0 else 3, 0)
            ctk.CTkLabel(self.holder, text=slot["text"], anchor="w", width=190).grid(
                row=number, column=0, sticky="w", padx=(8, 8), pady=pady)
            ctk.CTkLabel(self.holder, text=review_text.slot_status(slot, number, self.task.my_slots, self.handed_names),
                         anchor="w", justify="left").grid(row=number, column=1, sticky="w", pady=pady)
            if number in self.task.my_slots:
                undo = number in self.handed
                release_button.ReleaseButton(self.holder, text="Undo" if undo else "Reassign", width=90, height=28,
                                             fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                             command=lambda n=number: self._hand(n)).grid(
                    row=number, column=2, padx=(8, 8), pady=pady)
        self._update_buttons()

    def _hand(self, index):
        """Reassign one of your sign-offs (or undo that), kept here until a button at the bottom is pressed."""
        if index in self.handed:
            del self.handed[index], self.handed_names[index]
        else:
            chosen = reassign_dialog.ReassignDialog(self, self.task, self.directory, only=index,
                                                    exclude={self.my_id}).show()
            if chosen is None:
                return
            _slot, person_id = chosen
            self.handed[index] = person_id
            person = self.directory.get(person_id)
            self.handed_names[index] = person.name if person is not None else person_id
        self._draw_slots()

    # -- the answer ------------------------------------------------------------
    def _buttons(self, row):
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=row, column=0, sticky="ew", padx=20, pady=(8, 18))
        buttons.columnconfigure((0, 1, 2, 3), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Close", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        self.answer_buttons = {}
        for column, (key, text, color, hover) in enumerate(
                (("reject", "Reject", theme.RED, theme.RED_HOVER),
                 ("reassign", "Reassign", theme.GRAY, theme.GRAY_HOVER),
                 ("approve", "Approve", theme.GREEN, theme.GREEN_HOVER)), 1):
            button = release_button.ReleaseButton(buttons, text=text, height=38, fg_color=color, hover_color=hover,
                                                  command=lambda k=key: self._answer(k))
            button.grid(row=0, column=column, sticky="ew", padx=(6, 0 if column == 3 else 6))
            self.answer_buttons[key] = button

    def _update_buttons(self):
        for key, usable in review_text.buttons(self.task.my_slots, self.handed).items():
            self.answer_buttons[key].configure(state="normal" if usable else "disabled")

    def _answer(self, key):
        if not review_text.buttons(self.task.my_slots, self.handed)[key]:
            return
        comment = " ".join(self.comment_var.get().split())
        if key == "reject":
            problem = review_text.reject_problem(comment)
            if problem:
                self.problem.configure(text=problem, text_color=theme.ERROR)
                return
            if not messagebox.askyesno("Reject", f"Reject {self.task.label}? It goes back to "
                                                 f"{self.task.requested_by} to change and resubmit.", parent=self):
                return
        elif key == "approve":
            left = review_text.kept(self.task.my_slots, self.handed)
            if not messagebox.askokcancel("Approve", review_text.approve_question(self.task, len(left),
                                                                                  self.handed_names), parent=self):
                return
        elif not messagebox.askokcancel("Reassign", review_text.reassign_question(self.handed_names), parent=self):
            return
        self.result = {"answer": key, "handed": {} if key == "reject" else dict(self.handed), "comment": comment}
        self.destroy()
