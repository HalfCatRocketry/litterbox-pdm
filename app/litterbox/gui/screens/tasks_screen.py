"""
tasks_screen.py - Workflows: the sign-off requests waiting (a screen of the main window, chosen in the sidebar).
My Tasks lists the requests you are named to sign or asked for. Admins and superusers also get All Workflows: every
request, where an Admin can Override Approve or Override Reject, and a superuser can sign for anyone.
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui.logic import task_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.workflows import workflow_tasks

MY_TASKS, ALL_WORKFLOWS = "My Tasks", "All Workflows"


# (key, text, colour, hover colour, width) of each list's buttons
MINE_BUTTONS = (("sign", "Approve", theme.GREEN, theme.GREEN_HOVER, 110),
                ("reject", "Reject...", theme.RED, theme.RED_HOVER, 110),
                ("complete", "Complete", theme.PURPLE, theme.PURPLE_HOVER, 110),
                ("reassign", "Change signer...", theme.GRAY, theme.GRAY_HOVER, 140),
                ("withdraw", "Withdraw", theme.GRAY, theme.GRAY_HOVER, 100))


ALL_BUTTONS = (("superuser", "Approve as superuser...", theme.GREEN, theme.GREEN_HOVER, 190),
               ("override", "Override Approve...", theme.GRAY, theme.GRAY_HOVER, 160),
               ("override_reject", "Override Reject...", theme.RED, theme.RED_HOVER, 150),
               ("complete", "Complete", theme.PURPLE, theme.PURPLE_HOVER, 110),
               ("reassign", "Change signer...", theme.GRAY, theme.GRAY_HOVER, 140),
               ("withdraw", "Withdraw", theme.GRAY, theme.GRAY_HOVER, 100))


class TasksScreen(ctk.CTkFrame):
    """Workflows: My Tasks, and All Workflows for Admins and superusers."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Workflows", font=ctk.CTkFont(size=18, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        self.tabs = ctk.CTkTabview(self, fg_color="transparent")
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=8)
        self.tabs.add(MY_TASKS)
        self.mine = self._list(MY_TASKS, False)
        self.everything = None              # the All Workflows list, while this person may see it
        self.reload()

    def _list(self, name, everything):
        tab = self.tabs.tab(name)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        task_list = TaskList(tab, self.app, everything)
        task_list.grid(row=0, column=0, sticky="nsew")
        return task_list

    def reload(self):
        """Redraw from the part list the main window last loaded. All Workflows comes and goes with who you are."""
        wanted = workflow_tasks.can_see_all(self.app.identity)
        if wanted and self.everything is None:
            self.tabs.add(ALL_WORKFLOWS)
            self.everything = self._list(ALL_WORKFLOWS, True)
        elif not wanted and self.everything is not None:
            self.tabs.set(MY_TASKS)
            self.tabs.delete(ALL_WORKFLOWS)
            self.everything = None
        self.mine.reload()
        if self.everything is not None:
            self.everything.reload()


class TaskList(ctk.CTkFrame):
    """One tab's table of requests, the buttons for the one selected, and its details."""

    def __init__(self, master, app, everything):
        super().__init__(master, fg_color="transparent")
        self.app, self.everything = app, everything
        self.tasks = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.summary = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=900)
        self.summary.grid(row=0, column=0, sticky="ew", padx=8, pady=(2, 6))
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=8)
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
        row.grid(row=2, column=0, sticky="ew", padx=8, pady=(14, 4))
        self.action_buttons = {}
        for column, (key, text, color, hover, width) in enumerate(ALL_BUTTONS if everything else MINE_BUTTONS):
            button = release_button.ReleaseButton(row, text=text, width=width, fg_color=color, hover_color=hover,
                                                  command=lambda k=key: self._act(k))
            button.grid(row=0, column=column, padx=(0, 6))
            self.action_buttons[key] = button
        self.detail = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=900)
        self.detail.grid(row=3, column=0, sticky="ew", padx=8, pady=(8, 0))
        self.why = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=900)
        self.why.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 12))

    def reload(self):
        keep = self.tree.selection()
        tasks = workflow_tasks.tasks_from_rows(self.app.rows + list(self.app.doc_rows), self.app.identity,
                                               everything=self.everything)
        self.tasks = {t.id: t for t in tasks}
        self.tree.delete(*self.tree.get_children())
        for iid, values in task_text.tasks_table(tasks):
            self.tree.insert("", "end", iid=iid, values=values)
        self.summary.configure(text=task_text.tasks_summary(tasks, self.everything))
        for iid in keep:
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
        self._show_buttons()
        self._update_buttons()

    def _show_buttons(self):
        """On All Workflows, the superuser button shows only for a superuser and the overrides only for an Admin."""
        if not self.everything:
            return
        shown = task_text.all_workflows_buttons(self.app.identity)
        for key, button in self.action_buttons.items():
            if key in shown:
                button.grid()
            else:
                button.grid_remove()

    def _task(self):
        chosen = self.tree.selection()
        return self.tasks.get(chosen[0]) if chosen else None

    def _update_buttons(self):
        task = self._task()
        for key, value in task_text.button_states(task).items():
            if key in self.action_buttons:
                self.action_buttons[key].configure(state="normal" if value else "disabled")
        self.detail.configure(text=task_text.task_detail(task) if task else "")
        self.why.configure(text=(task.why_not_sign if task and not self.everything and not task.can_sign
                                 and not task.ready else ""))

    def _act(self, key):
        task = self._task()
        if task is None:
            return
        {"sign": self.app.task_sign, "reject": self.app.task_reject, "complete": self.app.task_complete,
         "withdraw": self.app.task_withdraw, "override": self.app.task_override,
         "override_reject": self.app.task_override_reject, "superuser": self.app.task_superuser_sign,
         "reassign": self.app.task_reassign}[key](task)
