"""
tasks_window.py - My Tasks: the sign-off requests waiting on you.
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import task_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.workflows import workflow_tasks


class TasksWindow(ctk.CTkToplevel):
    """My Tasks: workflow requests waiting for sign-off, and what you can do about each."""

    def __init__(self, app):
        super().__init__(app)
        window_chrome.set_window_icon(self)
        self.app = app
        self.tasks = {}
        self.title("My Tasks")
        self.geometry("1060x480")
        self.minsize(780, 340)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.summary = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=1000)
        self.summary.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in task_text.TASK_COLUMNS], show="headings",
                                 selectmode="browse")
        for name, _title, width in task_text.TASK_COLUMNS:
            self.tree.column(name, width=width, anchor="w")
        table_sorting.TableSorter(self.tree, [(c[0], c[1]) for c in task_text.TASK_COLUMNS])
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._update_buttons())
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 4))
        self.action_buttons = {}
        for column, (key, text, color, hover, width) in enumerate((
                ("sign", "Approve", theme.GREEN, theme.GREEN_HOVER, 110), ("reject", "Reject...", theme.RED, theme.RED_HOVER, 110),
                ("complete", "Complete", theme.PURPLE, theme.PURPLE_HOVER, 110), ("reassign", "Change signer...", theme.GRAY,
                                                                      theme.GRAY_HOVER, 140),
                ("withdraw", "Withdraw", theme.GRAY, theme.GRAY_HOVER, 100),
                ("override", "Admin override...", theme.GRAY, theme.GRAY_HOVER, 150), ("close", "Close", theme.GRAY, theme.GRAY_HOVER, 80))):
            command = self.destroy if key == "close" else (lambda k=key: self._act(k))
            button = release_button.ReleaseButton(row, text=text, width=width, fg_color=color, hover_color=hover, command=command)
            button.grid(row=0, column=column, padx=(0, 6))
            self.action_buttons[key] = button
        self.detail = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=1000)
        self.detail.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.why = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=1000)
        self.why.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.reload()
        self.after(100, self.lift)

    def reload(self):
        """Redraw from the part list the main window last loaded."""
        keep = self.tree.selection()
        tasks = workflow_tasks.tasks_from_rows(self.app.rows, self.app.identity)
        self.tasks = {t.id: t for t in tasks}
        self.tree.delete(*self.tree.get_children())
        for iid, values in task_text.tasks_table(tasks):
            self.tree.insert("", "end", iid=iid, values=values)
        mine = workflow_tasks.count_for_me(tasks)
        if not tasks:
            self.summary.configure(text="Nothing is waiting for sign-off. Press Get Latest in the main window to "
                                        "check for new requests.")
        else:
            self.summary.configure(text=f"{len(tasks)} request{'s' if len(tasks) != 1 else ''} waiting; "
                                        f"{mine} need{'s' if mine == 1 else ''} you. Press Get Latest in the main "
                                        "window to see new ones.")
        for iid in keep:
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
        self._update_buttons()

    def _task(self):
        chosen = self.tree.selection()
        return self.tasks.get(chosen[0]) if chosen else None

    def _update_buttons(self):
        task = self._task()
        flags = {"sign": task and task.can_sign, "reject": task and task.can_reject,
                 "complete": task and task.can_complete, "withdraw": task and task.can_withdraw,
                 "override": task and task.can_override, "reassign": task and task.can_reassign}
        for key, value in flags.items():
            self.action_buttons[key].configure(state="normal" if value else "disabled")
        self.detail.configure(text=task_text.task_detail(task) if task else "")
        self.why.configure(text=(task.why_not_sign if task and not task.can_sign and not task.ready else ""))

    def _act(self, key):
        task = self._task()
        if task is None:
            return
        {"sign": self.app.task_sign, "reject": self.app.task_reject, "complete": self.app.task_complete,
         "withdraw": self.app.task_withdraw, "override": self.app.task_override,
         "reassign": self.app.task_reassign}[key](task)
