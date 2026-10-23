"""
new_part_dialog.py - New Part / New Assembly: name, description, project, and the suggested number, checked as
you type.
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.core import part_number
from litterbox.core import projects as project_rules
from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import number_input
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.parts import create
from litterbox.parts import number_suggestions
from litterbox.team import project_access
from litterbox.vault import config

NO_PROJECT = "None"
KIND_CHOICES = ("CAD (SolidWorks files)", "Non-CAD (no CAD files: paint, stock, a kit built in its BOM)")
BASE_BOX_WIDTH = 130            # the part number box when it holds every digit


class NewPartDialog(modal_dialog.ModalDialog):
    """The New Part (or New Assembly) pop-up: a name, an optional description, the project, and the part number.

        NewPartDialog(parent, repo, org, kind=create.PART).show()
        # None if cancelled, else {"name": ..., "description": ..., "base": int or None, "variant": int or None,
        #                           "project": a project's name or None, "kind": create.PART or ASSEMBLY,
        #                           "noncad": True for a non-CAD part or assembly}

    The part number is two boxes, [base]-[variant]. Their grey placeholder text
    shows the number Litterbox will use if the box is left empty: the next free
    part number, and variant 001 (or, if the part number you type is already
    in use, its lowest free variant). A box left empty comes back as None.

    New Assembly (kind=create.ASSEMBLY) suggests variants from the org's assembly start (500), New Part the ones
    below it. A variant typed from the other range is allowed, with a warning under the boxes and a question on
    Create.

    Choosing a project (core/projects.py) puts its digits in front of the base box, which then takes only the rest
    of the digits, and the suggestion comes from the project's block. With no project, a number in a project's
    block is refused.

    A number you type must be written exactly as the org's part numbers are
    (for example 00002 and 001, with the digit counts from the vault's config),
    and must be unused. While you type, a line under the boxes says whether the
    part number is available; Create checks the same things again and refuses
    otherwise, leaving this window open. Everything here reads your local copy
    of the vault only.
    """
    FOCUS = "name_entry"

    def __init__(self, parent, repo, org, kind=create.PART):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.repo, self.org, self.kind = repo, org, kind
        self.result = None
        self.projects, self.project = [], None
        self.variants = (part_number.MIN_VARIANT, part_number.MAX_VARIANT)    # the kind's range, read from the vault
        width, height = 500, 620
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("New Assembly" if kind == create.ASSEMBLY else "New Part")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        self.name_var = tk.StringVar()
        self.desc_var = tk.StringVar()
        self.project_var = tk.StringVar(value=NO_PROJECT)

        ctk.CTkLabel(self, text="Name (required)", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(20, 2))
        self.name_entry = ctk.CTkEntry(self, textvariable=self.name_var, height=34)
        self.name_entry.grid(row=1, column=0, sticky="ew", padx=20)

        ctk.CTkLabel(self, text="Description (optional: extra context, tags, notes)", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(10, 2))
        self.desc_entry = ctk.CTkEntry(self, textvariable=self.desc_var, height=34)
        self.desc_entry.grid(row=3, column=0, sticky="ew", padx=20)

        ctk.CTkLabel(self, text="Kind", anchor="w").grid(row=4, column=0, sticky="ew", padx=20, pady=(10, 2))
        self.kind_var = tk.StringVar(value=KIND_CHOICES[0])
        ctk.CTkOptionMenu(self, variable=self.kind_var, values=list(KIND_CHOICES), width=260, height=34,
                          fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT).grid(
            row=5, column=0, sticky="w", padx=20)

        ctk.CTkLabel(self, text="Project", anchor="w").grid(row=6, column=0, sticky="ew", padx=20, pady=(10, 2))
        self.project_menu = ctk.CTkOptionMenu(self, variable=self.project_var, values=[NO_PROJECT], width=260,
                                              height=34, fg_color=theme.GRAY, button_color=theme.GRAY_HOVER,
                                              button_hover_color=theme.ACCENT, command=self._project_chosen)
        self.project_menu.grid(row=7, column=0, sticky="w", padx=20)

        ctk.CTkLabel(self, text="Part number:", anchor="w").grid(
            row=8, column=0, sticky="ew", padx=20, pady=(14, 2))
        numbers = ctk.CTkFrame(self, fg_color="transparent")
        numbers.grid(row=9, column=0, sticky="w", padx=20)
        self.prefix_label = ctk.CTkLabel(numbers, text="", font=ctk.CTkFont(size=14, weight="bold"))
        # No textvariable here: CustomTkinter only shows placeholder text without one.
        self.base_entry = ctk.CTkEntry(numbers, width=BASE_BOX_WIDTH, height=34, placeholder_text="")
        self.base_entry.grid(row=0, column=1)
        ctk.CTkLabel(numbers, text="-", width=18).grid(row=0, column=2)
        self.variant_entry = ctk.CTkEntry(numbers, width=70, height=34, placeholder_text="")
        self.variant_entry.grid(row=0, column=3)
        self.base_entry.bind("<KeyRelease>", lambda event: self._refresh(from_base=True))
        self.variant_entry.bind("<KeyRelease>", lambda event: self._refresh())

        # Under the boxes: "PN available" / "PN in use:" and, when in use, the name of the part that has it.
        self.verdict = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=width - 40,
                                    font=ctk.CTkFont(size=13, weight="bold"))
        self.verdict.grid(row=10, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.verdict_detail = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=width - 40,
                                           text_color=theme.ERROR)
        self.verdict_detail.grid(row=11, column=0, sticky="ew", padx=20)
        self.variant_note = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=width - 40,
                                         text_color=theme.WARN)
        self.variant_note.grid(row=12, column=0, sticky="ew", padx=20)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=13, column=0, sticky="ew", padx=20, pady=20)
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Create", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._create).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._create())
        try:
            config.apply(repo)              # learn this vault's digit counts before reading the boxes
            self.projects = config.get_projects(repo)
            self.variants = create.variant_range(repo, kind)
        except (config.ConfigError, LitterboxError) as e:
            self._say(str(e), theme.ERROR)
        else:
            offered = project_access.usable_here(repo, self.projects)        # a restricted project: its members
            self.project_menu.configure(values=[NO_PROJECT] + [p.name for p in offered])
            self._refresh(first_time=True)
        self.after(150, self._grab)

    def _say(self, text="", color=theme.MUTED, detail=""):
        self.verdict.configure(text=text, text_color=color)
        self.verdict_detail.configure(text=detail)

    def _variant_warning(self, variant):
        """A line saying a typed variant is from the other kind's range ("" if it fits or nothing is typed)."""
        low, high = self.variants
        if variant is None or low <= variant <= high:
            return ""
        usual = "assemblies" if self.kind == create.PART else "parts"
        what = "an assembly" if self.kind == create.ASSEMBLY else "a part"
        return (f"Variant {part_number.format_variant(variant)} is usually for {usual}. Variants for {what} are "
                f"{part_number.format_variant(low)} to {part_number.format_variant(high)}.")

    def _project_name(self):
        return self.project.name if self.project else None

    def _project_chosen(self, choice):
        """A project was picked: its digits go in front of a smaller base box (which is emptied), and the
        suggestion comes from its block."""
        self.project = None if choice == NO_PROJECT else project_rules.find(choice, self.projects)
        self.base_entry.delete(0, "end")
        if self.project is None:
            self.prefix_label.grid_forget()
            self.base_entry.configure(width=BASE_BOX_WIDTH)
        else:
            self.prefix_label.configure(text=self.project.prefix)
            self.prefix_label.grid(row=0, column=0, padx=(0, 2))
            share = self.project.remaining_digits() / part_number.BASE_DIGITS
            self.base_entry.configure(width=max(60, round(BASE_BOX_WIDTH * share)))
        self.focus_set()                    # the empty base box shows its grey suggestion again
        self._refresh(first_time=True)

    def _base_digits(self):
        """How many digits go in the base box."""
        return self.project.remaining_digits() if self.project else part_number.BASE_DIGITS

    def _shown_base(self, number):
        """A part number as the base box shows it: without the project's digits when a project is chosen."""
        text = part_number.format_base(number)
        return text[len(self.project.prefix):] if self.project else text

    def _typed(self):
        """What is in the two boxes: (base, variant), each an int or None for an empty box. With a project, the
        base is the whole part number (the project's digits and the ones typed).

        Raises ValueError (a message safe to show) if a box isn't written exactly.
        """
        if self.project:
            base = number_input.parse_project_number(self.base_entry.get(), self.project)
        else:
            base = number_input.parse_typed_number(self.base_entry.get(), "part number", part_number.BASE_DIGITS)
        variant = number_input.parse_typed_number(self.variant_entry.get(), "variant number", part_number.VARIANT_DIGITS)
        return base, variant

    def _refresh(self, first_time=False, from_base=False):
        """Update the placeholders and the availability line.

        The base box's placeholder is set when the window opens (and when the project changes) and is not
        touched while you type (changing the placeholder of a box that has the
        cursor and is empty would drop the grey text into the box). The variant
        placeholder follows the base you type.
        """
        try:
            base, variant = self._typed()
            problem = ""
        except ValueError as e:
            base = variant = None
            problem = str(e)
        if first_time or from_base:
            try:
                suggested_base, suggested_variant = number_suggestions.suggest_numbers(
                    self.repo, base, self.org, self._project_name(), self.kind)
            except LitterboxError as e:
                if first_time:
                    self.base_entry.configure(placeholder_text="")
                self._say(str(e), theme.ERROR)
                return
            if first_time:
                self.base_entry.configure(placeholder_text=self._shown_base(suggested_base))
            self.variant_entry.configure(placeholder_text=part_number.format_variant(suggested_variant))

        self.variant_note.configure(text="" if problem else self._variant_warning(variant))
        if problem:
            # Still typing (all digits, not too long yet)? Say it quietly. Anything else is a real mistake.
            texts = (self.base_entry.get().strip(), self.variant_entry.get().strip())
            limits = (self._base_digits(), part_number.VARIANT_DIGITS)
            still_typing = all(t.isascii() and t.isdigit() and len(t) <= n or not t for t, n in zip(texts, limits))
            self._say(problem, theme.MUTED if still_typing else theme.WARN)
        elif not self.base_entry.get().strip() and not self.variant_entry.get().strip():
            self._say()                                    # nothing typed: nothing to report
        else:
            try:
                check = number_suggestions.check_numbers(self.repo, base, variant, self.org, self._project_name(),
                                                         self.kind)
            except LitterboxError as e:
                self._say(str(e), theme.ERROR)
                return
            if check.taken:
                self._say("PN in use:", theme.ERROR, number_input.in_use_text(check))
            else:
                self._say(f"PN available: {check.pn}", theme.GREEN_TEXT)

    def _warn(self, message):
        messagebox.showwarning(self.title(), message, parent=self)

    def _create(self):
        name = self.name_var.get().strip()
        if not name:
            self._warn("Enter a name for the part.")
            return
        try:
            base, variant = self._typed()
        except ValueError as e:
            example = (f"{self.project.prefix} {1:0{self.project.remaining_digits()}d}" if self.project
                       else f"{self.org}-{part_number.format_base(2)}-{part_number.format_variant(1)}")
            self._warn(f"{e}\n\nA part number you type must be written in full, for example {example}.")
            return
        try:
            check = number_suggestions.check_numbers(self.repo, base, variant, self.org, self._project_name(),
                                                     self.kind)
        except LitterboxError as e:
            self._warn(str(e))
            return
        if check.taken:
            self._warn(f"{check.pn} is already in use.\n\n{number_input.in_use_text(check)}\n\n"
                       "Change the part number and try again.")
            return
        unusual = self._variant_warning(variant)
        if unusual and not messagebox.askokcancel(self.title(), f"{unusual}\n\nCreate {check.pn} anyway?", parent=self):
            return
        self.result = {"name": name, "description": self.desc_var.get().strip(),
                       "base": base, "variant": variant, "project": self._project_name(), "kind": self.kind,
                       "noncad": self.kind_var.get() == KIND_CHOICES[1]}
        self.destroy()
