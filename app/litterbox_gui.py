"""
litterbox_gui.py - the Litterbox window.

Setup (once):   pip install customtkinter pyyaml
Run:            python litterbox_gui.py

Keep this file in the same folder as litterbox_engine.py, registry.py, pn.py,
gui_logic.py, settings.py, create.py, importer.py, import_session.py, scan.py and manifest.py.

The window is deliberately thin. What the buttons are allowed to do lives in
gui_logic.py, and the git work lives in litterbox_engine.py.
"""

import os
import queue
import sys
import threading
import time
import version
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from pathlib import Path, PurePosixPath
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

import gui_logic as logic
import opener
import litterbox_engine as engine
import config
import registry
import people
import references
import revise
import signing
import create
import init_vault
import import_session
import importer
import manifest as manifest_module
import scan as scan_module
import settings
import updater
import workflow
from team_draft import TeamDraft
import pn as pnmod
from pn import PNError, check_org
from pn import parse as parse_pn

# Set to True to download the latest changes every time the app opens.
# (Off by default: a download can replace files that are open in SolidWorks.)
AUTO_GET_LATEST_ON_START = False

# Colors
BG_PANEL = "#2b2b2b"
ACCENT = "#1f6aa5"
GRAY = "#3a3a3a"
GRAY_HOVER = "#4a4a4a"
TICK_BG = "#4d4d4d"                 # a ticked (selected) row in the parts list: lighter than the list background
GREEN, GREEN_HOVER = "#2e8b57", "#256f45"
TEAL, TEAL_HOVER = "#2f7d8c", "#256673"
RED, RED_HOVER = "#8b3a3a", "#6f2e2e"
PURPLE, PURPLE_HOVER = "#6b4fa3", "#573f87"
MUTED = "#9a9a9a"
WARN = "#e5c07b"
GREEN_TEXT = "#5fd38d"
ERROR = "#e06c75"

# Row colors in the list, by the "kind" of status (see litterbox_engine.PartStatus)
ROW_COLORS = {
    "ok": "#e6e6e6",          # available
    "mine": "#5fd38d",        # checked out by you
    "theirs": "#f0a35e",      # checked out by someone else
    "unclaimed": "#e5c07b",   # modified, and nobody has it checked out
    "stray": "#e5c07b",       # modified without being checked out
    "missing": "#e06c75",     # not downloaded
    "released": "#6cb6ff",
    "cots": "#4fc1c9",        # purchased part
    "void": "#7a7a7a",
    "error": "#e06c75",
}


# The icons live in the "assets" folder next to this file. (When the program is later
# packaged into an .exe, PyInstaller unpacks them to sys._MEIPASS instead.)
ASSETS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"

# Which icon to use. The default is the white one. To switch, add a line
# "icon: black" to C:\Litterbox\settings.yaml.
ICON_SETTING = {"choice": logic.DEFAULT_ICON}


FADE_IN_MS = 160            # how long a window takes to fade in, and out
FADE_OUT_MS = 120
FADE_STEPS = 8


def dark_title_bar(window):
    """Windows only: give the window's title bar the dark colours (when Litterbox is in dark mode).

    CustomTkinter does this itself shortly after a pop-up opens, but it can lose to our icon and
    fade handling and leave a white title bar. Doing it again just before the window fades in
    (and once more a moment later) makes it reliable.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if ctk.get_appearance_mode() == "Dark" else 0)
        for attribute in (20, 19):                      # 20 on current Windows 10/11, 19 on early Windows 10
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
        # Ask Windows to redraw the frame (no move, no resize, no change of order or focus).
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    except Exception:
        pass


def set_window_icon(window, main_window=False):
    """Put the Litterbox icon on a window, and make it fade in and out. Call it right after the window is created.

    Windows doesn't keep an icon that was set before the window is first shown, so the window
    is made see-through until the icon has been applied:
      1. the window starts fully transparent and the icon is set straight away
         (this also stops CustomTkinter putting its own blue icon on),
      2. the moment the window appears on screen (the <Map> event) the icon and the dark title
         bar are applied again, and about 40 ms later the window fades in,
      3. a timer at 0.4 seconds fades it in no matter what, so it can never stay invisible.
    Closing the window (its destroy method) fades it out first. For the main window the icon is
    also made the default for later windows. A missing icon file, or a system that can't show
    .ico files or transparency, just means no icon or no fade.
    """
    icon = logic.find_icon(ASSETS_DIR, ICON_SETTING["choice"])
    state = {"shown": False, "closing": False}
    real_destroy = window.destroy

    def apply():
        if icon is None:
            return
        try:
            window.iconbitmap(str(icon))
            if main_window:
                window.iconbitmap(default=str(icon))
        except Exception:                   # window closed, not Windows, or not a valid .ico
            pass

    def set_opacity(value):
        try:
            window.attributes("-alpha", value)
        except Exception:                   # window closed, or the system doesn't support it
            pass

    def fade_in(step=0):
        set_opacity(min(step / FADE_STEPS, 1.0))
        if step < FADE_STEPS and not state["closing"]:
            try:
                window.after(max(FADE_IN_MS // FADE_STEPS, 1), lambda: fade_in(step + 1))
            except Exception:
                set_opacity(1.0)

    def reveal():
        if state["shown"]:
            return
        state["shown"] = True
        apply()
        dark_title_bar(window)              # while the window is still invisible
        fade_in()
        # CustomTkinter sets its own icon and title bar about 200 ms after a window opens, undoing ours,
        # so put both back a few times afterwards (the last one wins).
        for delay in (250, 500, 900):
            try:
                window.after(delay, lambda: (apply(), dark_title_bar(window)))
            except Exception:
                pass

    def on_map(event):
        if event.widget is window:          # ignore the same event arriving from child widgets
            apply()
            try:
                window.after(40, reveal)
            except Exception:
                pass

    def fade_out_and_destroy(step=0):
        if step == 0:
            if state["closing"]:
                return
            state["closing"] = True
        try:
            if not state["shown"] or not window.winfo_exists():
                real_destroy()
                return
            set_opacity(max(1.0 - (step + 1) / FADE_STEPS, 0.0))
            if step + 1 >= FADE_STEPS:
                real_destroy()
            else:
                window.after(max(FADE_OUT_MS // FADE_STEPS, 1), lambda: fade_out_and_destroy(step + 1))
        except Exception:
            try:
                real_destroy()
            except Exception:
                pass

    window.destroy = fade_out_and_destroy
    if main_window:
        # The main window's close button would otherwise destroy it at once, without going through destroy().
        try:
            window.protocol("WM_DELETE_WINDOW", window.destroy)
        except Exception:
            pass
    set_opacity(0.0)
    apply()
    try:
        window.bind("<Map>", on_map, add="+")
        window.after(400, reveal)           # safety net
    except Exception:
        state["shown"] = True
        set_opacity(1.0)


def set_app_id():
    """Windows only: give Litterbox its own identity so the taskbar shows its icon, not Python's."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Litterbox.Vault")
    except Exception:
        pass


class InputDialog(ctk.CTkInputDialog):
    """The one-line text prompt, with the Litterbox icon."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_window_icon(self)


def style_tables():
    """Make the plain Tk table (Treeview) match the dark theme."""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Treeview", background=BG_PANEL, foreground="#e6e6e6", fieldbackground=BG_PANEL,
        borderwidth=0, rowheight=30, font=("Segoe UI", 10),
    )
    style.configure(
        "Treeview.Heading", background="#1f1f1f", foreground="#e6e6e6",
        relief="flat", font=("Segoe UI", 10, "bold"), padding=6,
    )
    style.map("Treeview", background=[("selected", ACCENT)])
    style.map("Treeview.Heading", background=[("active", "#333333")])
    # The parts list: one blue highlighted row (for looking at a part), and lighter gray for rows with a box ticked.
    style.configure("Parts.Treeview", background=BG_PANEL, foreground="#e6e6e6", fieldbackground=BG_PANEL,
                    borderwidth=0, rowheight=30, font=("Segoe UI", 10))
    style.map("Parts.Treeview", background=[("selected", ACCENT)])
    style.layout("Parts.Treeview", style.layout("Treeview"))


def click_log(text):
    """Button presses and freezes go to the log file only (not the on-screen log), to help find slow spots.
    Only when debug_mode is on in settings.yaml."""
    if not settings.DEBUG:
        return
    try:
        settings.append_log("ui: " + text)
    except Exception:
        pass


def left_button_down():
    """Is the main mouse button physically held down right now? True / False, or None if this system can't say.

    Asked straight of Windows, so it doesn't depend on Tk delivering the "mouse released" event, which on
    some machines goes missing."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        swapped = bool(user32.GetSystemMetrics(23))             # SM_SWAPBUTTON: left-handed mouse setting
        return bool(user32.GetAsyncKeyState(0x02 if swapped else 0x01) & 0x8000)
    except Exception:
        return None


def pointer_inside(widget):
    """Is the mouse pointer over this widget right now? True / False, or None if this system can't say.

    Asked straight of Windows: the pointer position and the widget's window rectangle come from the same
    place, so they always agree. Tk's own numbers (event.x_root and winfo_rootx) can disagree on screens
    with display scaling, which made clicks near a button's edge do nothing while the middle worked."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        point, rect = wintypes.POINT(), wintypes.RECT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        if not user32.GetWindowRect(wintypes.HWND(widget.winfo_id()), ctypes.byref(rect)):
            return None
        return rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom
    except Exception:
        return None


class ReleaseButton(ctk.CTkButton):
    """A button that acts when the mouse button is RELEASED over it (like most programs), not when it is pressed.
    Pressing and then moving off the button before letting go cancels the click.

    The release is noticed two ways, whichever comes first: Tk's own release event, and a quick check (every
    15 ms after the press) of whether Windows says the mouse button is still down. The check is there because
    Tk's release event was seen going missing, which made some clicks do nothing."""

    _armed = False
    _pressed_at = 0.0
    WATCH_MS = 15
    GIVE_UP_SECONDS = 30

    def _create_bindings(self, sequence=None):
        super()._create_bindings(sequence)
        if sequence is None or sequence == "<ButtonRelease-1>":
            for part in (self._canvas, self._text_label, self._image_label):
                if part is not None:
                    part.bind("<ButtonRelease-1>", self._released)

    def _clicked(self, event=None):                      # called by CustomTkinter on PRESS: just remember it
        if self._state == "disabled":
            click_log(f"press '{self._label()}' ignored: button is greyed out")
            return
        click_log(f"press '{self._label()}' ok")
        self._armed = True
        self._pressed_at = time.monotonic()
        self.after(self.WATCH_MS, self._watch_mouse)

    def _label(self):
        try:
            return self.cget("text")
        except Exception:
            return "?"

    def _watch_mouse(self):
        if not self._armed:
            return
        down = left_button_down()
        if down is None:                                  # can't tell: rely on Tk's release event
            return
        if down and time.monotonic() - self._pressed_at < self.GIVE_UP_SECONDS:
            self.after(self.WATCH_MS, self._watch_mouse)
            return
        try:
            x, y = self.winfo_pointerxy()
        except Exception:
            self._armed = False
            return
        self._finish(x, y, "noticed by the check")

    def _released(self, event=None):
        if event is None:
            return
        self._finish(event.x_root, event.y_root, "Tk release event")

    EDGE_SLACK = 3                  # pixels of benefit of the doubt around the button, for Tk's own numbers

    def _over_button(self, x, y):
        """Was the mouse released over this button? Windows' answer or Tk's, whichever says yes."""
        windows = pointer_inside(self)
        left, top = self.winfo_rootx(), self.winfo_rooty()
        slack = self.EDGE_SLACK
        tk_says = (left - slack <= x < left + self.winfo_width() + slack
                   and top - slack <= y < top + self.winfo_height() + slack)
        click_log(f"release at ({x}, {y}); button at ({left}, {top}) size {self.winfo_width()}x{self.winfo_height()}; "
                  f"Windows says {windows}, Tk says {tk_says}")
        return bool(windows) or tk_says

    def _finish(self, x, y, how):
        armed, self._armed = self._armed, False
        if not armed:
            return                                         # the other path already dealt with this press
        if self._over_button(x, y):
            click_log(f"release '{self._label()}' -> running ({how})")
            super()._clicked(None)
        else:
            click_log(f"release '{self._label()}' ignored: mouse moved off the button")


class DiscardDialog(ctk.CTkToplevel):
    """'Discard changes?' with Discard and Keep editing. Use ask_discard(parent, what)."""

    def __init__(self, parent, what):
        super().__init__(parent)
        set_window_icon(self)
        self.discard = False
        width, height = 420, 170
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Discard changes?")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure((0, 1), weight=1, uniform="d")
        ctk.CTkLabel(self, text=f"Discard {what}?", font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
                     wraplength=380, justify="left").grid(row=0, column=0, columnspan=2, sticky="ew", padx=20,
                                                          pady=(20, 4))
        ctk.CTkLabel(self, text="This can't be undone.", text_color=MUTED, anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=20)
        ReleaseButton(self, text="Keep editing", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=2, column=0, sticky="ew", padx=(20, 6), pady=22)
        ReleaseButton(self, text="Discard", height=38, fg_color=RED, hover_color=RED_HOVER,
                      command=self._discard).grid(row=2, column=1, sticky="ew", padx=(6, 20), pady=22)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _discard(self):
        self.discard = True
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.discard


def ask_discard(parent, what="these changes"):
    """True if the user chose Discard, False for Keep editing (or closing the question)."""
    return DiscardDialog(parent, what).show()


class ConfirmDialog(ctk.CTkToplevel):
    """A small pop-up: a heading, a list of lines, an optional note, and Cancel / Continue buttons.

        dialog = ConfirmDialog(parent, "Title", "Heading", ["line 1", "line 2"], note="...")
        if dialog.show():        # True if the user pressed the confirm button
            ...
    """

    def __init__(self, parent, title, heading, lines, note="", confirm_text="Continue"):
        super().__init__(parent)
        set_window_icon(self)
        self.result = False
        width, height = 540, 420
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(title)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ctk.CTkLabel(self, text=heading, font=ctk.CTkFont(size=16, weight="bold"), anchor="w",
                     justify="left", wraplength=width - 40).grid(
            row=0, column=0, sticky="ew", padx=20, pady=(20, 8))

        box = ctk.CTkTextbox(self, fg_color=BG_PANEL, font=ctk.CTkFont(family="Consolas", size=13))
        box.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 8))
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")

        if note:
            ctk.CTkLabel(self, text=note, text_color=MUTED, anchor="w", justify="left",
                         wraplength=width - 40).grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text=confirm_text, height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._confirm).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)         # make the pop-up modal once it is on screen

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _confirm(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.destroy()

    def show(self):
        """Wait for the user to answer. Returns True for the confirm button, False otherwise."""
        self.wait_window(self)
        return self.result


class OrgDialog(ctk.CTkToplevel):
    """Set up an org: its code, its vault folder, and the first part number it hands out.

        result = OrgDialog(parent, org="HCR", folder=r"C:\\...", start=1, base_digits=5, variant_digits=3).show()
        # None if cancelled, else (org, folder, start, base_digits, variant_digits)
    """

    def __init__(self, parent, org="", folder="", start=1, base_digits=5, variant_digits=3, title="Org setup",
                 save_text="Save"):
        super().__init__(parent)
        set_window_icon(self)
        self.result = None
        width, height = 520, 420
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(title)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        self.org_var = tk.StringVar(value=org)
        self.folder_var = tk.StringVar(value=folder)
        self.start_var = tk.StringVar(value=str(start))
        self.base_digits_var = tk.StringVar(value=str(base_digits))
        self.variant_digits_var = tk.StringVar(value=str(variant_digits))

        ctk.CTkLabel(self, text="Org code (2 to 4 letters, for example HCR)", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(20, 2))
        ctk.CTkEntry(self, textvariable=self.org_var, height=34).grid(row=1, column=0, sticky="ew", padx=20)

        ctk.CTkLabel(self, text="Vault folder", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(12, 2))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=20)
        row.columnconfigure(0, weight=1)
        ctk.CTkEntry(row, textvariable=self.folder_var, height=34).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ReleaseButton(row, text="Browse", width=90, height=34, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self._browse).grid(row=0, column=1)

        ctk.CTkLabel(self, text="First part number to hand out (for example 10001)", anchor="w").grid(
            row=4, column=0, sticky="ew", padx=20, pady=(12, 2))
        ctk.CTkEntry(self, textvariable=self.start_var, height=34, width=140).grid(
            row=5, column=0, sticky="w", padx=20)

        ctk.CTkLabel(self, text="Digits in the part number and in the variant (for example 5 and 3)", anchor="w").grid(
            row=6, column=0, sticky="ew", padx=20, pady=(12, 2))
        digits = ctk.CTkFrame(self, fg_color="transparent")
        digits.grid(row=7, column=0, sticky="w", padx=20)
        ctk.CTkEntry(digits, textvariable=self.base_digits_var, height=34, width=70).grid(row=0, column=0)
        ctk.CTkLabel(digits, text="-", width=18).grid(row=0, column=1)
        ctk.CTkEntry(digits, textvariable=self.variant_digits_var, height=34, width=70).grid(row=0, column=2)
        ctk.CTkLabel(digits, text="Can't be changed once part numbers exist.", text_color=MUTED).grid(
            row=0, column=3, padx=(14, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=8, column=0, sticky="ew", padx=20, pady=20)
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text=save_text, height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _browse(self):
        folder = filedialog.askdirectory(parent=self, initialdir=self.folder_var.get() or "C:\\")
        if folder:
            self.folder_var.set(os.path.normpath(folder))

    def _save(self):
        try:
            org = check_org(self.org_var.get().strip()).upper()
        except PNError as e:
            messagebox.showwarning("Org setup", str(e), parent=self)
            return
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("Org setup", "Choose the vault folder for this org.", parent=self)
            return
        text = self.start_var.get().strip()
        if not text.isdigit() or int(text) < 1:
            messagebox.showwarning("Org setup", "The first part number must be a whole number, 1 or higher.",
                                   parent=self)
            return
        try:
            base_digits = logic.parse_digit_count(self.base_digits_var.get(), "part number digits", *pnmod.BASE_DIGITS_RANGE)
            variant_digits = logic.parse_digit_count(self.variant_digits_var.get(), "variant digits",
                                                     *pnmod.VARIANT_DIGITS_RANGE)
        except ValueError as e:
            messagebox.showwarning("Org setup", str(e), parent=self)
            return
        self.result = (org, folder, int(text), base_digits, variant_digits)
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class TableSorter:
    """Click a column heading to sort a table by it; click again to reverse. ▲ / ▼ shows the sort.

        sorter = TableSorter(tree, [("pn", "Part number"), ...])
        ...after the table is redrawn...
        sorter.apply()
    Numbers inside text sort as numbers, capitals are ignored, and blanks always go last.
    """

    def __init__(self, tree, titles):
        self.tree, self.titles = tree, list(titles)
        self.column, self.reverse = None, False
        for name, title in self.titles:
            self.tree.heading(name, text=title, anchor="w", command=lambda name=name: self.click(name))

    def click(self, column):
        self.reverse = (not self.reverse) if column == self.column else False
        self.column = column
        self.apply()

    def apply(self):
        """Show the arrow, and put the rows in order (call again after the rows are redrawn)."""
        for name, title in self.titles:
            arrow = (" ▼" if self.reverse else " ▲") if name == self.column else ""
            self.tree.heading(name, text=title + arrow)
        if self.column is None:
            return
        ids = list(self.tree.get_children())
        values = [self.tree.set(iid, self.column) for iid in ids]
        for position, index in enumerate(logic.sort_order(values, self.reverse)):
            self.tree.move(ids[index], "", position)


class RevisionPickerDialog(ctk.CTkToplevel):
    """Ask which revision of a part to open. Click a button; the first one is also the Enter key.

        rev = RevisionPickerDialog(parent, pn, [("Rev B (working)", "B"), ("Rev A (released)", "A")]).show()
        # None if cancelled
    """

    def __init__(self, parent, pn, choices, title="Open"):
        super().__init__(parent)
        set_window_icon(self)
        self.result = None
        width = 380
        height = 100 + 46 * len(choices)
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(f"{title} {pn.short}")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=f"Which revision of {pn.short}?", font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        for number, (label, rev) in enumerate(choices):
            ReleaseButton(self, text=label, height=38, fg_color=ACCENT if number == 0 else GRAY,
                          hover_color="#18527f" if number == 0 else GRAY_HOVER,
                          command=lambda rev=rev: self._choose(rev)).grid(
                row=number + 1, column=0, sticky="ew", padx=20, pady=3)
        self.first = choices[0][1]
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._choose(self.first))
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _choose(self, rev):
        self.result = rev
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class FilenameDialog(ctk.CTkToplevel):
    """Shown after New Part: the exact file name to save the CAD file as, with a Copy button."""

    def __init__(self, parent, pn, revision="A"):
        super().__init__(parent)
        set_window_icon(self)
        self.stem = pnmod.file_stem(pn, revision)
        width, height = 520, 230
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Part created")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=f"Created {pn}", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text="Save your SolidWorks file in the cad folder with this name "
                                "(SolidWorks adds the extension):", anchor="w", justify="left",
                     wraplength=width - 40, text_color=MUTED).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=20)
        self.entry = ctk.CTkEntry(self, height=36, font=ctk.CTkFont(family="Consolas", size=14))
        self.entry.grid(row=2, column=0, sticky="ew", padx=(20, 6), pady=10)
        self.entry.insert(0, self.stem)
        self.entry.configure(state="readonly")
        self.copy_button = ReleaseButton(self, text="Copy filename", height=36, width=130,
                                         fg_color=ACCENT, hover_color="#18527f", command=self._copy)
        self.copy_button.grid(row=2, column=1, padx=(0, 20), pady=10)
        ReleaseButton(self, text="Close", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(6, 18))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._copy())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.stem)
        self.copy_button.configure(text="Copied")


class ReasonDialog(ctk.CTkToplevel):
    """A question with a message and a required one-line reason.

        reason = ReasonDialog(parent, "Revise HCR-00001-001", "text...", "Why is it being revised?", "Revise").show()
        # None if cancelled, else the reason (never blank)
    """

    def __init__(self, parent, title, message, label, confirm_text="OK"):
        super().__init__(parent)
        set_window_icon(self)
        self.result = None
        width, height = 540, 440
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(title)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        box = ctk.CTkTextbox(self, fg_color=BG_PANEL, wrap="word", font=ctk.CTkFont(size=13))
        box.grid(row=0, column=0, sticky="nsew", padx=20, pady=(20, 8))
        box.insert("1.0", message)
        box.configure(state="disabled")
        ctk.CTkLabel(self, text=label, anchor="w").grid(row=1, column=0, sticky="ew", padx=20)
        self.entry = ctk.CTkEntry(self, height=34)
        self.entry.grid(row=2, column=0, sticky="ew", padx=20, pady=(2, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=ERROR, anchor="w")
        self.problem.grid(row=3, column=0, sticky="ew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text=confirm_text, height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._confirm).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._confirm())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _confirm(self):
        reason = " ".join(self.entry.get().split())
        if not reason:
            self.problem.configure(text="A reason is required.")
            return
        self.result = reason
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class EditDetailsDialog(ctk.CTkToplevel):
    """Change a part's name and description.

        EditDetailsDialog(parent, pn, name, description).show()
        # None if cancelled or nothing changed, else (name, description)
    """

    def __init__(self, parent, pn, name, description):
        super().__init__(parent)
        set_window_icon(self)
        self.result = None
        self.old = (name, description)
        width, height = 500, 300
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Edit Details")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text=str(pn), font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text="Name (required)", anchor="w").grid(row=1, column=0, sticky="ew", padx=20)
        self.name_entry = ctk.CTkEntry(self, height=34)
        self.name_entry.grid(row=2, column=0, sticky="ew", padx=20)
        self.name_entry.insert(0, name)
        ctk.CTkLabel(self, text="Description (optional)", anchor="w").grid(
            row=3, column=0, sticky="ew", padx=20, pady=(10, 0))
        self.desc_entry = ctk.CTkEntry(self, height=34)
        self.desc_entry.grid(row=4, column=0, sticky="ew", padx=20)
        self.desc_entry.insert(0, description)
        self.problem = ctk.CTkLabel(self, text="", text_color=ERROR, anchor="w")
        self.problem.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text="Save", height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._save())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.name_entry.focus_set()
        except tk.TclError:
            pass

    def _save(self):
        name, description = self.name_entry.get(), self.desc_entry.get()
        problem, changed = logic.edit_details_result(*self.old, name, description)
        self.problem.configure(text=problem)
        if problem:
            return
        if changed:
            self.result = (name, description)
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class NewPartDialog(ctk.CTkToplevel):
    """The New Part pop-up: a name, an optional description, and the part number.

        NewPartDialog(parent, repo, org).show()
        # None if cancelled, else {"name": ..., "description": ..., "base": int or None, "variant": int or None}

    The part number is two boxes, [base]-[variant]. Their grey placeholder text
    shows the number Litterbox will use if the box is left empty: the next free
    part number, and variant 001 (or, if the part number you type is already
    in use, its lowest free variant). A box left empty comes back as None.

    A number you type must be written exactly as the org's part numbers are
    (for example 00002 and 001, with the digit counts from the vault's config),
    and must be unused. While you type, a line under the boxes says whether the
    part number is available; Create checks the same things again and refuses
    otherwise, leaving this window open. Everything here reads your local copy
    of the vault only.
    """

    def __init__(self, parent, repo, org):
        super().__init__(parent)
        set_window_icon(self)
        self.repo, self.org = repo, org
        self.result = None
        width, height = 500, 450
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("New Part")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        self.name_var = tk.StringVar()
        self.desc_var = tk.StringVar()

        ctk.CTkLabel(self, text="Name (required)", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(20, 2))
        self.name_entry = ctk.CTkEntry(self, textvariable=self.name_var, height=34)
        self.name_entry.grid(row=1, column=0, sticky="ew", padx=20)

        ctk.CTkLabel(self, text="Description (optional: extra context, tags, notes)", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(10, 2))
        self.desc_entry = ctk.CTkEntry(self, textvariable=self.desc_var, height=34)
        self.desc_entry.grid(row=3, column=0, sticky="ew", padx=20)

        ctk.CTkLabel(self, text="Part number:", anchor="w").grid(
            row=4, column=0, sticky="ew", padx=20, pady=(14, 2))
        numbers = ctk.CTkFrame(self, fg_color="transparent")
        numbers.grid(row=5, column=0, sticky="w", padx=20)
        # No textvariable here: CustomTkinter only shows placeholder text without one.
        self.base_entry = ctk.CTkEntry(numbers, width=130, height=34, placeholder_text="")
        self.base_entry.grid(row=0, column=0)
        ctk.CTkLabel(numbers, text="-", width=18).grid(row=0, column=1)
        self.variant_entry = ctk.CTkEntry(numbers, width=70, height=34, placeholder_text="")
        self.variant_entry.grid(row=0, column=2)
        self.base_entry.bind("<KeyRelease>", lambda event: self._refresh(from_base=True))
        self.variant_entry.bind("<KeyRelease>", lambda event: self._refresh())

        # Under the boxes: "PN available" / "PN in use:" and, when in use, the name of the part that has it.
        self.verdict = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=width - 40,
                                    font=ctk.CTkFont(size=13, weight="bold"))
        self.verdict.grid(row=6, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.verdict_detail = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=width - 40,
                                           text_color=ERROR)
        self.verdict_detail.grid(row=7, column=0, sticky="ew", padx=20)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=8, column=0, sticky="ew", padx=20, pady=20)
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text="Create", height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._create).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._create())
        try:
            config.apply(repo)              # learn this vault's digit counts before reading the boxes
        except config.ConfigError as e:
            self._say(str(e), ERROR)
        else:
            self._refresh(first_time=True)
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.name_entry.focus_set()
        except tk.TclError:
            pass

    def _say(self, text="", color=MUTED, detail=""):
        self.verdict.configure(text=text, text_color=color)
        self.verdict_detail.configure(text=detail)

    def _typed(self):
        """What is in the two boxes: (base, variant), each an int or None for an empty box.

        Raises ValueError (a message safe to show) if a box isn't written exactly.
        """
        base = logic.parse_typed_number(self.base_entry.get(), "part number", pnmod.BASE_DIGITS)
        variant = logic.parse_typed_number(self.variant_entry.get(), "variant number", pnmod.VARIANT_DIGITS)
        return base, variant

    def _refresh(self, first_time=False, from_base=False):
        """Update the placeholders and the availability line.

        The base box's placeholder is set once when the window opens and is not
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
                suggested_base, suggested_variant = create.suggest_numbers(self.repo, base, self.org)
            except engine.LitterboxError as e:
                self._say(str(e), ERROR)
                return
            if first_time:
                self.base_entry.configure(placeholder_text=pnmod.format_base(suggested_base))
            self.variant_entry.configure(placeholder_text=pnmod.format_variant(suggested_variant))

        if problem:
            # Still typing (all digits, not too long yet)? Say it quietly. Anything else is a real mistake.
            texts = (self.base_entry.get().strip(), self.variant_entry.get().strip())
            limits = (pnmod.BASE_DIGITS, pnmod.VARIANT_DIGITS)
            still_typing = all(t.isascii() and t.isdigit() and len(t) <= n or not t for t, n in zip(texts, limits))
            self._say(problem, MUTED if still_typing else WARN)
        elif not self.base_entry.get().strip() and not self.variant_entry.get().strip():
            self._say()                                    # nothing typed: nothing to report
        else:
            try:
                check = create.check_numbers(self.repo, base, variant, self.org)
            except engine.LitterboxError as e:
                self._say(str(e), ERROR)
                return
            if check.taken:
                self._say("PN in use:", ERROR, logic.in_use_text(check))
            else:
                self._say(f"PN available: {check.pn}", GREEN_TEXT)

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
            self._warn(f"{e}\n\nA part number you type must be written in full, "
                       f"for example {self.org}-{pnmod.format_base(2)}-{pnmod.format_variant(1)}.")
            return
        try:
            check = create.check_numbers(self.repo, base, variant, self.org)
        except engine.LitterboxError as e:
            self._warn(str(e))
            return
        if check.taken:
            self._warn(f"{check.pn} is already in use.\n\n{logic.in_use_text(check)}\n\n"
                       "Change the part number and try again.")
            return
        self.result = {"name": name, "description": self.desc_var.get().strip(),
                       "base": base, "variant": variant}
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class PnEditor:
    """The part number editor placed over a table cell: ORG-[base box]-[variant box], like New Part.

    get() returns (base text, variant text). Enter in the first box moves to the second; Enter in the
    second box, or leaving both boxes, calls on_commit; Escape calls on_cancel.
    """

    def __init__(self, parent, org, base, variant, on_commit, on_cancel):
        self.on_commit = on_commit
        self.frame = tk.Frame(parent, bg="#1f1f1f", highlightthickness=1, highlightbackground=ACCENT)
        label = dict(bg="#1f1f1f", fg="#e6e6e6", font=("Segoe UI", 10))
        tk.Label(self.frame, text=f"{org}-", **label).pack(side="left", padx=(6, 0))
        options = dict(font=("Segoe UI", 10), bg="#2b2b2b", fg="#ffffff", insertbackground="#ffffff",
                       relief="flat", justify="center")
        self.base_box = tk.Entry(self.frame, width=pnmod.BASE_DIGITS + 1, **options)
        self.base_box.pack(side="left")
        tk.Label(self.frame, text="-", **label).pack(side="left")
        self.variant_box = tk.Entry(self.frame, width=pnmod.VARIANT_DIGITS + 1, **options)
        self.variant_box.pack(side="left", padx=(0, 6))
        self.base_box.insert(0, base)
        self.variant_box.insert(0, variant)
        for box in (self.base_box, self.variant_box):
            box.bind("<Escape>", lambda e: on_cancel())
            box.bind("<FocusOut>", lambda e: self.frame.after(60, self._left))
        self.base_box.bind("<Return>", lambda e: self.variant_box.focus_set())
        self.base_box.bind("-", lambda e: (self.variant_box.focus_set(), "break")[1])
        self.variant_box.bind("<Return>", lambda e: on_commit())

    def place(self, x, y, width, height):
        self.frame.place(x=x, y=y, width=width, height=height)
        self.base_box.focus_set()
        self.base_box.select_range(0, "end")

    def _left(self):
        """Commit once focus has left both boxes (moving from one box to the other does not count)."""
        try:
            if self.frame.focus_get() in (self.base_box, self.variant_box):
                return
        except (tk.TclError, KeyError):
            pass
        self.on_commit()

    def get(self):
        return self.base_box.get(), self.variant_box.get()

    def destroy(self):
        self.frame.destroy()


class ImportWindow(ctk.CTkToplevel):
    """The Import window: choose folders, review the table, Finish & Import.

        ImportWindow(parent, repo, org, on_imported=callback, log=function)

    1. Pick folders (or open a saved scan). Litterbox scans them (read-only), reads what each
       assembly references, and proposes new part numbers.
    2. The table lists every item with its new part number, name and description. Click the
       first column to select / deselect an item. Double-click a part number, name or description to
       edit it. Clear a part number to let Litterbox choose one again.
    3. Finish & Import checks the numbers against the newest records and imports. If a number you
       typed has been taken, nothing is imported: the window stays on the table with those rows
       in red. Cancel at any time removes everything copied so far.

    All the work is done by import_session.ImportSession on a background thread; this window
    only shows things and passes on clicks. The pieces that decide what rows say and what
    an edit does are in gui_logic.py.
    """

    COLUMNS = (("tick", "", 36, False), ("pn", "New part number", 140, False), ("name", "Name", 230, True),
               ("description", "Description", 260, True), ("kind", "Type", 90, False),
               ("files", "Files", 110, False), ("notes", "Notes", 230, True))
    EDIT_COLUMNS = {"#2": "pn", "#3": "name", "#4": "description"}

    def __init__(self, parent, repo, org, on_imported=None, log=None, cots=False):
        super().__init__(parent)
        set_window_icon(self)
        try:
            config.apply(repo)                      # learn this vault's digit counts for the part number boxes
        except config.ConfigError:
            pass
        self.repo, self.org, self.on_imported = repo, org, on_imported
        self.cots = cots                            # Import COTS: everything is recorded as a purchased part
        self.last_click = None                      # (row id, ticked afterwards) for shift-click
        self.family_applied = None                  # the base number the rows were last given, if any
        self.family_placeholder = ""
        self.duplicates = {}                        # table row -> warnings about parts the vault already has
        self._cots_confirmed = False
        self.heading = "Import COTS" if cots else "Import CAD"
        self.inbox = queue.Queue()                  # results from the background thread
        self.session = import_session.ImportSession(repo, self.inbox.put, log=log or (lambda text: None), org=org)
        self.folders = []
        self.conflicts = []
        self.renumbered = []
        self.running = False
        self.finishing = False
        self.closing = False
        self.closed = False
        self.editor = None
        self._details = {}                          # table row id -> gui_logic.ImportRow

        width, height = 1140, 720
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title(self.heading)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(900, 560)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 6))
        ctk.CTkLabel(header, text=self.heading, font=ctk.CTkFont(size=22, weight="bold"), anchor="w").pack(anchor="w")
        ctk.CTkLabel(header, text=("For purchased parts you have not modified (McMaster-Carr, vendor models). "
                                   "They are recorded as COTS. Your original files are only read."
                                   if cots else
                                   "Your original files are only read. Litterbox copies them into the vault under "
                                   "new part numbers."), text_color=MUTED, anchor="w").pack(anchor="w")

        self.pick_page = ctk.CTkFrame(self, fg_color="transparent")
        self.table_page = ctk.CTkFrame(self, fg_color="transparent")
        self._build_pick_page()
        self._build_table_page()

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(4, 16))
        footer.columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(footer, text="", text_color=MUTED, anchor="w", justify="left", wraplength=width - 60)
        self.status.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.progress = ctk.CTkProgressBar(footer)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        buttons = ctk.CTkFrame(footer, fg_color="transparent")
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.secondary = ReleaseButton(buttons, text="Close", width=150, height=38, fg_color=GRAY,
                                       hover_color=GRAY_HOVER, command=self._close)
        self.secondary.grid(row=0, column=0, padx=(0, 10))
        self.primary = ReleaseButton(buttons, text="Scan & Review", width=200, height=38, fg_color=GREEN,
                                     hover_color=GREEN_HOVER, command=self._scan)
        self.primary.grid(row=0, column=1)

        self.mode = "pick"
        self._show("pick")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._pump)
        self.after(150, self._grab)

    # ------------------------------------------------------------------
    # Building the pages
    # ------------------------------------------------------------------
    def _build_pick_page(self):
        page = self.pick_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ctk.CTkLabel(page, text="Folders to import (everything inside them is included)", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=24, pady=(10, 4))
        self.folder_list = tk.Listbox(page, bg=BG_PANEL, fg="#e6e6e6", selectbackground=ACCENT, borderwidth=0,
                                      highlightthickness=0, font=("Segoe UI", 10), activestyle="none")
        self.folder_list.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 8))
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 8))
        for column, (text, command) in enumerate((("Add folder...", self._add_folder),
                                                  ("Remove selected", self._remove_folder),
                                                  ("Open a saved scan...", self._open_manifest))):
            ReleaseButton(row, text=text, command=command, height=34, fg_color=GRAY,
                          hover_color=GRAY_HOVER).grid(row=0, column=column, padx=(0 if column == 0 else 8, 0))
        ctk.CTkLabel(page, text="Scanning looks at file names only. Nothing is opened, changed or moved."
                                + ("" if self.cots else " Purchased (COTS) parts are brought in with Import COTS."),
                     text_color=MUTED, anchor="w", justify="left", wraplength=900).grid(
            row=3, column=0, sticky="ew", padx=24, pady=(0, 6))
        self.cots_var = tk.BooleanVar(value=False)
        if self.cots:
            ctk.CTkCheckBox(page, text="I confirm that every file in these folders is a purchased part that I have "
                                       "NOT modified.", variable=self.cots_var, width=60).grid(
                row=4, column=0, sticky="w", padx=24, pady=(4, 6))

    def _build_table_page(self):
        page = self.table_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=24, pady=(6, 6))
        bar.columnconfigure(0, weight=1)
        self.summary = ctk.CTkLabel(bar, text="", anchor="w")
        self.summary.grid(row=0, column=0, sticky="w")
        for column, (text, command) in enumerate((("Select All", lambda: self._tick_all(True)),
                                                  ("Deselect All", lambda: self._tick_all(False)),
                                                  ("Refresh numbers", self._refresh_numbers))):
            ReleaseButton(bar, text=text, command=command, width=110, height=30, fg_color=GRAY,
                          hover_color=GRAY_HOVER).grid(row=0, column=1 + column, padx=(6, 0))

        family = ctk.CTkFrame(bar, fg_color="transparent")
        family.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.family_var = tk.BooleanVar(value=False)
        self.family_box = ctk.CTkCheckBox(family, text="Import all as the same base number:", width=0,
                                          variable=self.family_var, command=self._family_toggled)
        self.family_box.grid(row=0, column=0)
        # No textvariable here: CustomTkinter only shows placeholder text without one (see NewPartDialog).
        self.family_entry = ctk.CTkEntry(family, width=130, height=30, placeholder_text="")
        self.family_entry.grid(row=0, column=1, padx=(8, 0))
        self.family_entry.bind("<Return>", self._family_typed)
        self.family_entry.bind("<FocusOut>", self._family_typed)
        ctk.CTkLabel(family, text="(leave empty for the next free number; if it is in use, new variants start at "
                                  "the lowest free one)", text_color=MUTED).grid(row=0, column=2, padx=(10, 0))

        frame = ctk.CTkFrame(page, fg_color=BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=24)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        style_tables()
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in self.COLUMNS], show="headings", selectmode="browse")
        for name, title, width, stretch in self.COLUMNS:
            self.tree.column(name, width=width, anchor="center" if name == "tick" else "w", stretch=stretch)
        self.sorter = TableSorter(self.tree, [(name, title) for name, title, _w, _s in self.COLUMNS])
        for tag, options in (("ok", {"foreground": "#e6e6e6"}), ("typed", {"foreground": "#6cb6ff"}),
                             ("warn", {"foreground": WARN}), ("off", {"foreground": "#7a7a7a"}),
                             ("conflict", {"foreground": "#ffffff", "background": "#8b3a3a"})):
            self.tree.tag_configure(tag, **options)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._show_detail())

        ctk.CTkLabel(page, text="\u2611 = will be imported.   \u2610 = left out: no part number, nothing copied, and "
                                "it stays in the saved scan so you can import it later.   Click the first column to "
                                "select or deselect (Shift-click selects everything in between).\nDouble-click a part number, name or description to edit it "
                                "(clear a part number to let Litterbox choose one).",
                     text_color=MUTED, anchor="w", justify="left", wraplength=1050).grid(
            row=2, column=0, sticky="ew", padx=26, pady=(6, 0))
        self.detail = ctk.CTkLabel(page, text="", anchor="nw", justify="left", wraplength=1050, height=60,
                                   text_color=MUTED)
        self.detail.grid(row=3, column=0, sticky="ew", padx=26, pady=(2, 0))

    # ------------------------------------------------------------------
    # Pages, status, background results
    # ------------------------------------------------------------------
    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _show(self, mode):
        """mode: 'pick' (choose folders), 'table' (review), or 'working' (a job is running)."""
        self.mode = mode
        shown = "table" if mode == "table" or (mode == "working" and self.session.prepared is not None) else "pick"
        self.pick_page.grid_forget()
        self.table_page.grid_forget()
        (self.table_page if shown == "table" else self.pick_page).grid(row=1, column=0, sticky="nsew")
        working = mode == "working"
        if working:
            self.progress.grid()
            self.primary.configure(state="disabled")
            self.secondary.configure(text="Cancel import" if self.finishing else "Cancel", state="normal",
                                     command=self._cancel_job)
        else:
            self.progress.grid_remove()
            self.progress.set(0)
            self.secondary.configure(text="Close" if mode == "pick" else "Cancel import", state="normal",
                                     command=self._close)
            if mode == "pick":
                self.primary.configure(text="Scan & Review", state="normal", command=self._scan)
            else:
                self.primary.configure(text="Finish & Import", state="normal", command=self._finish)

    def _say(self, text, tone="normal"):
        color = {"normal": MUTED, "warn": WARN, "error": ERROR, "good": GREEN_TEXT}[tone]
        self.status.configure(text=text, text_color=color)

    def _pump(self):
        """Run the results the background thread has queued (always on the window's own thread)."""
        if self.closed:
            return
        try:
            while True:
                work = self.inbox.get_nowait()
                try:
                    work()
                except Exception as e:                  # a bug here must not freeze the window
                    self._say(f"Something unexpected went wrong: {e!r}", "error")
                    self.running = False
        except queue.Empty:
            pass
        try:
            self.after(50, self._pump)
        except tk.TclError:
            pass

    def _begin(self, text, finishing=False):
        self.running, self.finishing = True, finishing
        self._end_edit()
        self.progress.set(0)
        self._say(text)
        self._show("working")

    def _progress(self, done, total, text):
        if total:
            self.progress.set(min(done / total, 1.0))
        self._say(text)

    def _after(self, handler):
        """Wrap a result handler: ignore it if the window is closing, else mark the job finished first."""
        def wrapper(result, error):
            self.running = False
            self.finishing = False
            if self.closing:
                self._really_close()
                return
            handler(result, error)
        return wrapper

    @staticmethod
    def _error_text(error):
        known = (engine.LitterboxError, scan_module.ScanError, manifest_module.ManifestError)
        return str(error) if isinstance(error, known) else f"Unexpected error: {error!r}"

    # ------------------------------------------------------------------
    # Page 1: choosing folders and scanning
    # ------------------------------------------------------------------
    def _add_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Folder with CAD files to import")
        if folder and folder not in self.folders:
            self.folders.append(folder)
            self.folder_list.insert("end", folder)

    def _remove_folder(self):
        for index in reversed(self.folder_list.curselection()):
            self.folder_list.delete(index)
            del self.folders[index]

    def _cots_ok(self):
        """Import COTS only starts once the user has ticked the confirmation box."""
        if self.cots and not self.cots_var.get():
            self._say("Tick the box to confirm that everything you are importing is a purchased, unmodified part.",
                      "warn")
            return False
        return True

    def _scan(self):
        if not self._cots_ok():
            return
        if not self.folders:
            self._say("Add at least one folder first.", "warn")
            return
        self._start_job(dict(folders=list(self.folders)), "Scanning...")

    def _open_manifest(self):
        path = filedialog.askopenfilename(parent=self, title="Open a saved scan",
                                          initialdir=str(settings.ROOT / "imports"),
                                          filetypes=[("Litterbox scan", "*.yaml *.yml"), ("All files", "*.*")])
        if path and self._cots_ok():
            self._start_job(dict(manifest_path=path), "Opening the saved scan...")

    def _start_job(self, source, text):
        try:
            self.session.start(self._after(self._prepared), self._progress, manifest_root=settings.ROOT,
                               cots=self.cots, **source)
        except engine.LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin(text)

    def _prepared(self, proposal, error):
        if error is not None:
            self._show("pick")
            if isinstance(error, importer.ImportCancelled):
                self._say("Cancelled. Nothing was changed.", "warn")
            else:
                self._say("The scan could not be completed.", "error")
                messagebox.showerror("Import CAD", logic.shorten(self._error_text(error)), parent=self)
            return
        self.conflicts, self.renumbered = [], []
        self.family_applied = None
        self.family_var.set(False)
        self.family_placeholder = logic.import_base_placeholder(self.repo, self.session.prepared.proposal.org)
        self.family_entry.configure(placeholder_text=self.family_placeholder)
        self._show("table")
        self._rebuild()
        self._say(f"Scan saved to {self.session.manifest_path}. Review the table, then press Finish & Import.\n"
                  + self.session.prepared.proposal.note)
        if self.cots:
            self._check_duplicates()

    def _check_duplicates(self, then=None):
        """Import COTS: look for rows that duplicate parts already in the vault (a warning, never a block)."""
        def done(found, error):
            self._show("table")
            if error is None:
                self.duplicates = found
                self._rebuild()
                if found:
                    self._say(f"{len(found)} row(s) look like parts the vault already has (yellow). Select a row to "
                              "see why.", "warn")
            else:
                self._say(self._error_text(error), "warn")
            if then:
                then(error is None)
        try:
            self.session.check_duplicates(self._after(done))
        except engine.LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin("Checking for parts the vault already has...")

    # ------------------------------------------------------------------
    # Page 2: the table
    # ------------------------------------------------------------------
    def _rebuild(self):
        prepared = self.session.prepared
        rows = logic.import_rows(prepared.candidates, prepared.proposal, self.conflicts, self.duplicates)
        self._details = {str(r.item_id): r for r in rows}
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", iid=str(r.item_id), tags=(r.tag,), values=(
                "☑" if r.ticked else "☐", r.pn, r.name, r.description, r.kind, r.files, r.notes))
        keep = [iid for iid in selected if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(*keep)
        self.sorter.apply()
        self.summary.configure(text=logic.import_summary_line(prepared.candidates, prepared.proposal, self.conflicts),
                               text_color=ERROR if self.conflicts else "#e6e6e6")
        self._show_detail()

    def _show_detail(self):
        chosen = self.tree.selection()
        row = self._details.get(chosen[0]) if chosen else None
        self.detail.configure(text=row.detail if row else "")

    def _blocked(self):
        """True (and says why) while a job is running, since the background thread is using the table."""
        if self.running:
            self._say("Please wait for the current step to finish.", "warn")
        return self.running

    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or self._blocked():
            return
        ticked = self._details[iid].ticked
        self._end_edit()
        self.conflicts, self.duplicates = [], {}              # row positions change; the next check finds them again
        anchor, shown = self.last_click, list(self.tree.get_children())
        if logic.shift_held(event) and anchor is not None and anchor[0] in shown:
            # Shift: give every row from the last click to this one the state the last click gave its row
            between = logic.range_between(shown, anchor[0], iid)
            self.last_click = (iid, anchor[1])
            self._include_rows([int(i) for i in between], anchor[1])
            return "break"
        self.last_click = (iid, not ticked)
        self._run_quick(lambda done: self.session.include(int(iid), not ticked, done))
        return "break"

    def _tick_all(self, state):
        if self._blocked():
            return
        self._include_rows([r.item_id for r in self._details.values()], state)

    def _include_rows(self, item_ids, state):
        """Select (or deselect) these rows one after another on the session's thread, then redraw."""
        wanted = [self._details[str(i)] for i in item_ids if str(i) in self._details
                  and self._details[str(i)].ticked != state]
        self.conflicts, self.duplicates = [], {}

        def next_one(_result=None, error=None):
            if error is not None:
                self._say(self._error_text(error), "warn")
                if isinstance(error, importer.FamilyFull):
                    messagebox.showwarning("Not enough variant numbers", self._error_text(error), parent=self)
            if wanted and error is None:
                row = wanted.pop(0)
                self.running = False
                self._run_quick(lambda done: self.session.include(row.item_id, state, done), next_one, rebuild=False)
            else:
                self.running = False
                self._rebuild()

        next_one()

    def _run_quick(self, start, then=None, rebuild=True):
        """Run a short session job (ticking a row) without switching to the progress view."""
        def done(result, error):
            self.running = False
            if self.closing:
                self._really_close()
                return
            if then is not None:
                then(result, error)
                return
            if error is not None:
                self._say(self._error_text(error), "warn")
                if isinstance(error, importer.FamilyFull):
                    messagebox.showwarning("Not enough variant numbers", self._error_text(error), parent=self)
            if rebuild:
                self._rebuild()
        self.running = True
        try:
            start(done)
        except engine.LitterboxError as e:
            self.running = False
            self._say(str(e), "warn")

    def _family_toggled(self):
        """The 'same base number' box was ticked or cleared."""
        if self.running:
            self.family_var.set(not self.family_var.get())          # the table is busy: undo the click
            self._say("Please wait for the current step to finish.", "warn")
            return
        self._end_edit()
        self._apply_family(self.family_entry.get().strip() or self.family_placeholder if self.family_var.get() else None)

    def _family_typed(self, event=None):
        """A base number was typed (Return, or the box lost focus): use it if the box is ticked."""
        if not self.family_var.get() or self.running or self.closed:
            return
        wanted = self.family_entry.get().strip() or self.family_placeholder
        if self.family_applied is None or str(self.family_applied).lstrip("0") != wanted.lstrip("0"):
            self._apply_family(wanted)

    def _apply_family(self, base):
        """Give the rows variants of `base` (None: separate numbers again). Refuses, and says why, if it won't fit."""
        def done(proposal, error):
            self.running = False
            if self.closing:
                self._really_close()
                return
            if error is not None:
                self.family_var.set(self.family_applied is not None)       # nothing changed: go back
                self._say(self._error_text(error), "warn")
                messagebox.showwarning("Part number", self._error_text(error), parent=self)
                return
            self.family_applied = base
            self.conflicts, self.duplicates = [], {}
            self._rebuild()
            if base is None:
                self._say("The rows have separate part numbers again.")
            else:
                self._say(f"All the rows are variants of {base}: any rows you typed numbers into were left alone.")
        self.running = True
        try:
            self.session.set_family(base, done)
        except engine.LitterboxError as e:
            self.running = False
            self.family_var.set(self.family_applied is not None)
            self._say(str(e), "warn")

    def _on_double_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        column = self.EDIT_COLUMNS.get(self.tree.identify_column(event.x))
        iid = self.tree.identify_row(event.y)
        if not column or not iid or self._blocked():
            return
        self._end_edit()
        box = self.tree.bbox(iid, self.tree.identify_column(event.x))
        if not box:
            return
        x, y, w, h = box
        if column == "pn":
            base, variant = self._pn_parts(iid)
            editor = PnEditor(self.tree, self.org, base, variant, self._commit_edit, self._end_edit)
            editor.place(x, y, max(w, 200), h)
        else:
            editor = tk.Entry(self.tree, font=("Segoe UI", 10), bg="#1f1f1f", fg="#ffffff",
                              insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightcolor=ACCENT)
            editor.insert(0, self.tree.set(iid, column))
            editor.select_range(0, "end")
            editor.place(x=x, y=y, width=w, height=h)
            editor.focus_set()
            editor.bind("<Return>", lambda e: self._commit_edit())
            editor.bind("<Escape>", lambda e: self._end_edit())
            editor.bind("<FocusOut>", lambda e: self._commit_edit())
        self.editor = (editor, iid, column)
        return "break"

    def _pn_parts(self, iid):
        """The row's current part number as the two box texts ('00042', '001'), or empty boxes if unticked."""
        text = self.tree.set(iid, "pn")
        parsed = parse_pn(text) if text else None
        if not parsed:
            return "", ""
        return pnmod.format_base(parsed.base), pnmod.format_variant(parsed.variant)

    def _end_edit(self):
        if self.editor:
            editor, _iid, _column = self.editor
            self.editor = None
            try:
                editor.destroy()
            except tk.TclError:
                pass

    def _commit_edit(self):
        if not self.editor:
            return
        editor, iid, column = self.editor
        text = editor.get()
        self._end_edit()
        prepared = self.session.prepared
        index = next((n for n, e in enumerate(prepared.proposal.entries) if e.item.id == int(iid)), None)
        if column == "pn":
            problem = logic.edit_import_pn(prepared, int(iid), text[0], text[1], repo=self.repo)
        else:
            problem = logic.edit_import_cell(prepared, int(iid), column, text)
        self._say(problem, "warn" if problem else "normal")
        if column == "pn" and not problem:                    # an edited number is no longer known to be taken
            self.conflicts = [c for c in self.conflicts if c.index != index]
        self._rebuild()

    def _refresh_numbers(self):
        if self._blocked():
            return
        self._end_edit()

        def done(state, error):
            if error is not None:
                self._show("table")
                self._say(self._error_text(error), "error")
                return
            self._show("table")
            self.duplicates = {}
            self.conflicts, self.renumbered = state.conflicts, state.renumbered + self.renumbered
            self._rebuild()
            if state.conflicts:
                self._say(f"{len(state.conflicts)} part number(s) you typed are taken. Change the red rows.", "error")
            elif state.renumbered:
                self._say(f"{len(state.renumbered)} automatic part number(s) were taken and have been replaced.", "warn")
            else:
                self._say("All the part numbers are available.", "good")

        try:
            self.session.refresh(self._after(done))
        except engine.LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin("Checking the part numbers against the newest records...")

    # ------------------------------------------------------------------
    # Finish & Import, cancel, close
    # ------------------------------------------------------------------
    def _finish(self):
        if self._blocked():
            return
        self._end_edit()
        self.conflicts = []
        if self.cots and not self._cots_confirmed:
            self._check_duplicates(then=self._confirm_cots)       # look for duplicates, then ask
            return
        try:
            self.session.finish(self._after(self._finished), self._progress)
        except engine.LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin("Checking the part numbers...", finishing=True)

    def _confirm_cots(self, checked):
        """The last question before Import COTS goes ahead: it names the duplicates found, if any."""
        if not checked:
            return
        entries = self.session.prepared.proposal.entries
        text = logic.import_cots_confirm_text(len(entries), self.duplicates, [e.name for e in entries])
        if messagebox.askyesno("Import as COTS?", text, parent=self):
            self._cots_confirmed = True
            self._finish()
        else:
            self._say("Nothing was imported.", "warn")

    def _finished(self, result, error):
        confirmed, self._cots_confirmed = self._cots_confirmed, False      # each Finish asks again
        self.session.set_allow_external(False)             # the answer to the question below counts for one try only
        if isinstance(error, importer.ExternalReferences):
            self._show("table")
            self._rebuild()
            if messagebox.askyesno("Files outside this import", logic.import_external_text(error), parent=self):
                self.session.set_allow_external(True)
                self._cots_confirmed = confirmed
                self._finish()
            else:
                self._say("Nothing was imported. Select the missing items, or scan their folder too, and try again.",
                          "warn")
            return
        if error is None:
            messagebox.showinfo("Import complete", logic.import_result_text(result), parent=self)
            if self.on_imported:
                self.on_imported(result)
            self._really_close()
            return
        self._show("table")
        if isinstance(error, importer.PNConflict):
            self.conflicts, self.renumbered = error.conflicts, error.renumbered
            self._rebuild()
            self._say("Nothing was imported: some part numbers can't be used. Change the red rows, then press "
                      "Finish & Import again.", "error")
            messagebox.showwarning("Part numbers taken", logic.import_conflict_text(error.conflicts, error.renumbered),
                                   parent=self)
        elif isinstance(error, importer.ImportCancelled):
            self._rebuild()
            self._say("Import cancelled. Nothing was added to the vault, and your files were not changed.", "warn")
        else:
            self._rebuild()
            self._say("The import did not go ahead, and nothing was added to the vault.", "error")
            messagebox.showerror("Import CAD", logic.shorten(self._error_text(error)), parent=self)

    def _cancel_job(self):
        if self.running:
            self.session.cancel()
            self.secondary.configure(state="disabled")
            self._say("Cancelling... removing anything already copied.", "warn")

    def _close(self):
        if self.running:
            if messagebox.askyesno("Import CAD", "Cancel the import in progress? Anything already copied will be "
                                                 "removed.", parent=self):
                self.closing = True
                self._cancel_job()
            return
        if self.mode == "table" and self.session.prepared and messagebox.askyesno(
                "Import CAD", "Close without importing? Nothing has been added to the vault. The scan stays saved "
                              "and can be opened again.", parent=self) is False:
            return
        self._really_close()

    def _really_close(self):
        if self.closed:
            return
        self.closed = True
        self._end_edit()
        try:
            self.session.close()
        finally:
            try:
                self.grab_release()
            except tk.TclError:
                pass
            self.destroy()


class HistoryWindow(ctk.CTkToplevel):
    """A pop-up table of everything that has happened to one part."""

    def __init__(self, parent, record, revisions=None, on_open=None):
        super().__init__(parent)
        set_window_icon(self)
        self.title(f"History - {record.pn}")
        self.geometry("820x600")
        self.minsize(560, 400)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.on_open = on_open

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            header, text=f"{record.pn}   {record.name}",
            font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header, text=f"Status: {record.status}     Created by {record.created_by}"
                         + ("     COTS" if record.cots else ""),
            text_color=MUTED, anchor="w",
        ).grid(row=1, column=0, sticky="w")
        extra = [text for text in (record.description,
                                   f"Imported from: {record.import_path}" if record.import_path else "") if text]
        if extra:
            ctk.CTkLabel(header, text="\n".join(extra), text_color=MUTED, anchor="w", justify="left",
                         wraplength=760).grid(row=2, column=0, sticky="w")

        # The revisions of this part, with buttons to open one
        revision_rows = logic.revision_rows(record, revisions or {})
        box = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        box.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        box.columnconfigure(0, weight=1)
        self.rev_tree = ttk.Treeview(box, columns=("rev", "state", "details"), show="headings",
                                     height=min(max(len(revision_rows), 1), 5), selectmode="browse")
        for name, title, width in (("rev", "Rev", 60), ("state", "State", 160), ("details", "Details", 520)):
            self.rev_tree.heading(name, text=title, anchor="w")
            self.rev_tree.column(name, width=width, anchor="w")
        for row in revision_rows:
            self.rev_tree.insert("", "end", iid=row[0], values=row)
        if revision_rows:
            self.rev_tree.selection_set(revision_rows[0][0])
        self.rev_tree.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        if on_open:
            buttons = ctk.CTkFrame(box, fg_color="transparent")
            buttons.grid(row=0, column=1, padx=(0, 8), pady=8)
            ReleaseButton(buttons, text="Open", width=110, fg_color=TEAL, hover_color=TEAL_HOVER,
                          command=lambda: self._open(False)).grid(row=0, column=0, pady=(0, 6))
            ReleaseButton(buttons, text="Open Drawing", width=110, fg_color=TEAL, hover_color=TEAL_HOVER,
                          command=lambda: self._open(True)).grid(row=1, column=0)

        frame = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 20))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(frame, columns=("when", "who", "what", "details"), show="headings")
        history_columns = (("when", "When", 130), ("who", "Who", 110),
                           ("what", "What", 100), ("details", "Details", 420))
        for name, _title, width in history_columns:
            self.tree.column(name, width=width, anchor="w")
        self.sorter = TableSorter(self.tree, [(name, title) for name, title, _w in history_columns])
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)

        for row in logic.format_history(record):
            self.tree.insert("", "end", values=row)
        self.after(100, self.lift)

    def _open(self, drawing):
        chosen = self.rev_tree.selection()
        if chosen and self.on_open:
            self.on_open(chosen[0], drawing)


class ReferencesWindow(ctk.CTkToplevel):
    """What a part uses and where it is used. Click a box to select, then replace the chosen
    references with the latest released revision. Only assemblies that are still in work can change.

    The window stays open while references are being updated: set_busy() greys it out with a message,
    and show() fills it in again with the new data."""

    def __init__(self, parent, pn, name, uses_list, used_list, on_replace, this_outdated=False, others_outdated=(),
                 on_update=None):
        super().__init__(parent)
        set_window_icon(self)
        self.pn = pn
        self.title(f"References - {pn.short}")
        self.geometry("980x640")
        self.minsize(720, 460)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.on_replace = on_replace
        self.on_update = on_update                 # on_update(window, [PN, ...])
        self.busy = False
        self.title_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=18, weight="bold"), anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        self.body = None
        self.show(name, uses_list, used_list, this_outdated, others_outdated)
        self.after(100, self.lift)

    def show(self, name, uses_list, used_list, this_outdated=False, others_outdated=()):
        """(Re)build everything that depends on the data."""
        if self.body is not None:
            self.body.destroy()
        self.busy = False
        pn = self.pn
        self.title_label.configure(text=f"{pn.short}   {name}")
        self.entries = {}                      # (tree, iid) -> Use
        self.trees = []
        self.action_buttons = []
        body = self.body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        body.rowconfigure(3, weight=1)
        for row, title, columns, rows, items in (
                (0, "This part uses", (("tick", "", 34), ("pn", "Part", 110), ("name", "Name", 230),
                                       ("rev", "Rev used", 70), ("latest", "Latest released", 100),
                                       ("state", "State", 250)),
                 logic.uses_table(uses_list), uses_list),
                (2, "This part is used in", (("tick", "", 34), ("pn", "Assembly", 110), ("name", "Name", 200),
                                             ("rev", "Its rev", 60), ("status", "Its status", 80),
                                             ("used", "Rev of this part", 110), ("state", "State", 230)),
                 logic.used_in_table(used_list), used_list)):
            ctk.CTkLabel(body, text=title if rows else title + " - nothing", text_color=MUTED, anchor="w").grid(
                row=row, column=0, sticky="w", padx=20, pady=(8, 0))
            frame = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=10)
            frame.grid(row=row + 1, column=0, sticky="nsew", padx=20, pady=(4, 0))
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=6)
            for name_, _title, width in columns:
                tree.column(name_, width=width, anchor="w")
            TableSorter(tree, [(c[0], c[1]) for c in columns])
            tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
            scroll = ctk.CTkScrollbar(frame, command=tree.yview)
            scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
            tree.configure(yscrollcommand=scroll.set)
            for (iid, values, _can), use in zip(rows, items):
                tree.insert("", "end", iid=iid, values=values)
                self.entries[(str(tree), iid)] = use
            tree.bind("<Button-1>", lambda event, tree=tree: self._click(tree, event))
            self.trees.append(tree)

        self.banner_text = None
        stale_note = logic.outdated_note(pn, this_outdated, others_outdated)
        if stale_note:
            banner = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=10)
            banner.grid(row=4, column=0, sticky="ew", padx=20, pady=(10, 0))
            self.banner_text = ctk.CTkLabel(banner, text=stale_note, text_color="#e5c07b", anchor="w",
                                            justify="left", wraplength=560)
            self.banner_text.grid(row=0, column=0, sticky="w", padx=12, pady=8)
            self.banner_note = stale_note
            actions = ctk.CTkFrame(banner, fg_color="transparent")
            actions.grid(row=0, column=1, padx=8, pady=6)
            if this_outdated:
                self.action_buttons.append(ReleaseButton(
                    actions, text="Update this part", width=150, fg_color=ACCENT, hover_color="#18527f",
                    command=lambda: self._update([pn])))
                self.action_buttons[-1].grid(row=0, column=0, padx=4)
            if others_outdated:
                self.action_buttons.append(ReleaseButton(
                    actions, text=f"Update all ({len(others_outdated) + int(this_outdated)})", width=130,
                    fg_color=GRAY, hover_color=GRAY_HOVER,
                    command=lambda: self._update(([pn] if this_outdated else []) + list(others_outdated))))
                self.action_buttons[-1].grid(row=0, column=1, padx=4)
            banner.columnconfigure(0, weight=1)

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=20, pady=14)
        for column, (text, width, color, hover, command) in enumerate((
                ("Select all that can change", 190, GRAY, GRAY_HOVER, self._tick_all),
                ("Replace selected with latest released", 250, PURPLE, PURPLE_HOVER, self._replace))):
            button = ReleaseButton(buttons, text=text, width=width, fg_color=color, hover_color=hover,
                                   command=command)
            button.grid(row=0, column=column, padx=(0, 8))
            self.action_buttons.append(button)
        ReleaseButton(buttons, text="Close", width=100, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=2)
        ctk.CTkLabel(buttons, text="Released assemblies are frozen: revise the assembly to change them.",
                     text_color=MUTED).grid(row=0, column=3, padx=14)
        self._tick_all()

    def set_busy(self, message):
        """Grey out the buttons and show what is happening, without closing the window."""
        self.busy = True
        for button in self.action_buttons:
            button.configure(state="disabled")
        if self.banner_text is not None:
            self.banner_text.configure(text=message)

    def set_idle(self):
        """Back to normal after a failed update."""
        self.busy = False
        for button in self.action_buttons:
            button.configure(state="normal")
        if self.banner_text is not None:
            self.banner_text.configure(text=self.banner_note)

    def _update(self, pns):
        if self.busy or not self.on_update:
            return
        self.set_busy("Updating references... SolidWorks may start if it is not open.")
        self.on_update(self, pns)

    def _click(self, tree, event):
        if self.busy:
            return
        if tree.identify_column(event.x) != "#1" or tree.identify_region(event.x, event.y) != "cell":
            return
        iid = tree.identify_row(event.y)
        if iid:
            anchor = self.last_click.get(str(tree))
            if logic.shift_held(event) and anchor is not None and tree.exists(anchor) and tree.set(anchor, "tick"):
                mark = tree.set(anchor, "tick")             # Shift: everything from the last click to here
                for between in logic.range_between(list(tree.get_children()), anchor, iid):
                    if tree.set(between, "tick"):
                        self._set_mark(tree, between, mark)
            else:
                self._set_mark(tree, iid, logic.toggled(tree.set(iid, "tick")))
            self.last_click[str(tree)] = iid

    @staticmethod
    def _set_mark(tree, iid, mark):
        tree.set(iid, "tick", mark)

    def _tick_all(self):
        for tree in self.trees:
            for iid in tree.get_children():
                if tree.set(iid, "tick"):
                    self._set_mark(tree, iid, logic.CHECKED)

    def _replace(self):
        if self.busy:
            return
        chosen, seen = [], set()
        for tree in self.trees:
            for iid in tree.get_children():
                use = self.entries.get((str(tree), iid))
                if use is not None and tree.set(iid, "tick") == logic.CHECKED and use.replaceable:
                    key = (use.parent, use.child, use.child_revision)
                    if key not in seen:
                        seen.add(key)
                        chosen.append(references.Replacement(use.parent, use.child, use.child_revision))
        if not chosen:
            messagebox.showinfo("Nothing selected", "Select at least one reference to replace.")
            return
        self.destroy()
        self.on_replace(chosen)


class PersonDialog(ctk.CTkToplevel):
    """Add or edit one person on the team.

        PersonDialog(parent, person_or_None, roles, existing_ids, can_set_access, host_name_hint).show()
        # None if cancelled, else (problem-free) dict of fields; for a new person it includes 'id'
    """

    ADD_ROLE = "Add a role..."

    def __init__(self, parent, person, roles, existing_ids, can_set_access, host_name_hint="", apply=None):
        super().__init__(parent)
        set_window_icon(self)
        self.result = None
        self.apply = apply          # apply(fields) -> problem text, or "" when the change was taken
        self.person, self.existing_ids = person, existing_ids
        width, height = 520, 700
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Add Person" if person is None else f"Edit {person.name}")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        def label(row, text):
            ctk.CTkLabel(self, text=text, anchor="w", text_color=MUTED).grid(
                row=row, column=0, sticky="ew", padx=20, pady=(8, 0))

        def entry(row, value=""):
            box = ctk.CTkEntry(self, height=32)
            box.grid(row=row, column=1 - 1, sticky="ew", padx=20)
            box.insert(0, value)
            return box

        label(0, "Name (required)")
        self.name_entry = entry(1, person.name if person else "")
        label(2, "Email")
        self.email_entry = entry(3, person.email if person else "")
        label(4, "Names the host may report for this person (commas between). Use Who am I? on their computer.")
        self.host_entry = entry(5, ", ".join(person.host_names) if person else host_name_hint)
        label(6, "Access")
        self.access_var = tk.StringVar(value=(person.access if person else "member").capitalize())
        self.access_menu = ctk.CTkOptionMenu(self, variable=self.access_var, values=["Member", "Admin"], width=140,
                                             fg_color=GRAY, button_color=GRAY_HOVER)
        self.access_menu.grid(row=7, column=0, sticky="w", padx=20)
        if person is not None and person.access == "owner":
            self.access_var.set("Owner")
            self.access_menu.configure(state="disabled")
        elif not can_set_access:
            self.access_menu.configure(state="disabled")
        label(8, "Roles: pick from the list to add; select one in the box and press Remove to take it off")
        self.all_roles = list(roles)
        self.chosen_roles = list(person.roles) if person else []
        roles_row = ctk.CTkFrame(self, fg_color="transparent")
        roles_row.grid(row=9, column=0, sticky="ew", padx=20)
        roles_row.columnconfigure(1, weight=1)
        pick_box = ctk.CTkFrame(roles_row, fg_color="transparent")
        pick_box.grid(row=0, column=0, sticky="n")
        self.role_var = tk.StringVar(value=self.ADD_ROLE)
        self.role_menu = ctk.CTkOptionMenu(pick_box, variable=self.role_var, values=[self.ADD_ROLE], width=200,
                                           fg_color=GRAY, button_color=GRAY_HOVER, command=self._role_picked)
        self.role_menu.grid(row=0, column=0)
        ReleaseButton(pick_box, text="Remove", width=200, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self._remove_role).grid(row=1, column=0, pady=(6, 0))
        self.role_tree = ttk.Treeview(roles_row, columns=("role",), show="headings", height=4, selectmode="browse")
        self.role_tree.heading("role", text="This person's roles", anchor="w")
        self.role_tree.column("role", width=240, anchor="w")
        self.role_tree.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self._show_roles()
        label(10, "Signing keys (optional): one public key per line, given to you by the person")
        self.keys_box = ctk.CTkTextbox(self, height=90, fg_color=BG_PANEL)
        self.keys_box.grid(row=11, column=0, sticky="ew", padx=20)
        if person:
            self.keys_box.insert("1.0", "\n".join(person.signing_keys))
        self.problem = ctk.CTkLabel(self, text="", text_color=ERROR, anchor="w", justify="left", wraplength=470)
        self.problem.grid(row=12, column=0, sticky="ew", padx=20, pady=(8, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=13, column=0, sticky="ew", padx=20, pady=(8, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text="OK", height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.initial = self._snapshot()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)

    def _snapshot(self):
        return (self.name_entry.get(), self.email_entry.get(), self.host_entry.get(), self.access_var.get(),
                tuple(self.chosen_roles), self.keys_box.get("1.0", "end").strip())

    def _cancel(self):
        if self._snapshot() != self.initial and not ask_discard(self, "your changes to this person"):
            return
        self.destroy()

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.name_entry.focus_set()
        except tk.TclError:
            pass

    def _show_roles(self):
        self.role_tree.delete(*self.role_tree.get_children())
        for role in self.chosen_roles:
            self.role_tree.insert("", "end", iid=role, values=(role,))
        left = logic.roles_to_choose(self.all_roles, self.chosen_roles)
        self.role_menu.configure(values=[self.ADD_ROLE] + left)
        self.role_var.set(self.ADD_ROLE)

    def _role_picked(self, choice):
        if choice != self.ADD_ROLE and choice not in self.chosen_roles:
            self.chosen_roles.append(choice)
        self._show_roles()

    def _remove_role(self):
        chosen = self.role_tree.selection()
        if chosen and chosen[0] in self.chosen_roles:
            self.chosen_roles.remove(chosen[0])
        self._show_roles()

    def _save(self):
        form = {"name": self.name_entry.get(), "email": self.email_entry.get(), "host_names": self.host_entry.get(),
                "roles": ", ".join(self.chosen_roles), "keys": self.keys_box.get("1.0", "end"),
                "access": self.access_var.get()}
        problem, fields = logic.person_form_result(None if self.person is None else self.person.id, form,
                                                   self.existing_ids)
        self.problem.configure(text=problem)
        if problem:
            return
        if self.apply is not None:
            problem = self.apply(dict(fields))
            self.problem.configure(text=problem)
            if problem:
                return
        self.result = fields
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class SigningDialog(ctk.CTkToplevel):
    """Turn signed commits on or off for this vault and show the public key to give an Admin."""

    def __init__(self, parent, repo):
        super().__init__(parent)
        set_window_icon(self)
        self.repo = repo
        self.title("Signing")
        self.geometry("560x420")
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.state_label = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=520)
        self.state_label.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text="Your public key (give this to an Admin; it is safe to share):", anchor="w",
                     text_color=MUTED).grid(row=1, column=0, sticky="ew", padx=20)
        self.key_box = ctk.CTkTextbox(self, fg_color=BG_PANEL, height=110, wrap="word")
        self.key_box.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 8))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        for column, (text, command, color, hover) in enumerate((
                ("Turn on signing", self._on, ACCENT, "#18527f"), ("Copy public key", self._copy, GRAY, GRAY_HOVER),
                ("Turn off", self._off, GRAY, GRAY_HOVER), ("Close", self.destroy, GRAY, GRAY_HOVER))):
            ReleaseButton(buttons, text=text, width=120, fg_color=color, hover_color=hover,
                          command=command).grid(row=0, column=column, padx=(0, 6))
        self._show()
        self.after(100, self.lift)

    def _show(self):
        state = signing.status(self.repo)
        text = "Signing is ON for this vault." if state.enabled else "Signing is off for this vault."
        if state.problems:
            text += "\n" + "\n".join(state.problems)
        self.state_label.configure(text=text)
        self.key_box.configure(state="normal")
        self.key_box.delete("1.0", "end")
        self.key_box.insert("1.0", state.public_key)
        self.key_box.configure(state="disabled")

    def _on(self):
        try:
            signing.enable(self.repo)
        except engine.LitterboxError as e:
            messagebox.showerror("Signing", str(e))
        self._show()

    def _off(self):
        signing.disable(self.repo)
        self._show()

    def _copy(self):
        key = signing.status(self.repo).public_key
        if key:
            self.clipboard_clear()
            self.clipboard_append(key)


class RolesDialog(ctk.CTkToplevel):
    """The list of roles this org uses. Type a role and press Add; select one and press Remove.

        RolesDialog(parent, roles, holders_of).show()      # holders_of(role) -> names of people who have it
        # None if cancelled, else the new list of roles. Nothing is saved until the caller saves it.
    """

    def __init__(self, parent, roles, holders_of, apply=None):
        super().__init__(parent)
        set_window_icon(self)
        self.result = None
        self.apply = apply          # apply(roles) -> problem text, or "" when the change was taken
        self.roles = list(roles)
        self.initial = list(roles)
        self.holders_of = holders_of
        width, height = 460, 560
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Roles")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(380, 420)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Roles this org uses", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        frame = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("role",), show="headings", selectmode="browse")
        self.tree.heading("role", text="Role", anchor="w")
        self.tree.column("role", anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)

        add_row = ctk.CTkFrame(self, fg_color="transparent")
        add_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        add_row.columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(add_row, height=34, placeholder_text="New role, for example Reviewer")
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry.bind("<Return>", lambda event: self._add())
        ReleaseButton(add_row, text="Add", width=80, fg_color=ACCENT, hover_color="#18527f",
                      command=self._add).grid(row=0, column=1, padx=(0, 6))
        ReleaseButton(add_row, text="Remove", width=80, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self._remove).grid(row=0, column=2)
        ReleaseButton(self, text="Add the standard roles", height=30, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self._standard).grid(row=3, column=0, sticky="w", padx=20, pady=(8, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=ERROR, anchor="w")
        self.problem.grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text="OK", height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self._show()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)

    def _cancel(self):
        if self.roles != self.initial and not ask_discard(self, "your changes to the roles"):
            return
        self.destroy()

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _show(self):
        self.tree.delete(*self.tree.get_children())
        for role in self.roles:
            self.tree.insert("", "end", iid=role, values=(role,))

    def _add(self):
        problem, role = logic.add_role_result(self.entry.get(), self.roles)
        self.problem.configure(text=problem)
        if problem:
            return
        self.roles.append(role)
        self.entry.delete(0, "end")
        self._show()

    def _remove(self):
        chosen = self.tree.selection()
        if not chosen:
            self.problem.configure(text="Select a role to remove.")
            return
        role = chosen[0]
        if not messagebox.askyesno("Remove role", logic.role_removal_text(role, self.holders_of(role)), parent=self):
            return
        self.roles.remove(role)
        self.problem.configure(text="")
        self._show()

    def _standard(self):
        for role in people.STANDARD_ROLES:
            if role.lower() not in (r.lower() for r in self.roles):
                self.roles.append(role)
        self._show()

    def _save(self):
        if self.roles == self.initial:                  # nothing changed: nothing to keep
            self.destroy()
            return
        if self.apply is not None:
            problem = self.apply(list(self.roles))
            self.problem.configure(text=problem)
            if problem:
                return
        self.result = list(self.roles)
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class WorkflowsDialog(ctk.CTkToplevel):
    """Team > Workflows: the sign-off templates for each action, one tab per action.

        WorkflowsDialog(parent, roles, templates, apply=callback).show()
        # callback(ops, editor) -> problem text, or "" when the change was taken (see logic.WorkflowEditor)

    A template is a list of sign-offs. A role listed twice is two sign-offs; "+ or" lets a sign-off be filled by
    someone with any of several roles. Nothing is saved here: OK keeps the change in the Team window's draft.
    """

    def __init__(self, parent, roles, templates, apply=None):
        super().__init__(parent)
        set_window_icon(self)
        self.result = None
        self.apply = apply
        self.roles = list(roles)
        self.editor = logic.WorkflowEditor(templates)
        self.selected = {action: 0 for action in workflow.ACTIONS}
        self.name_vars = {}
        width, height = 820, 640
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Workflows")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(720, 520)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Workflows: who has to sign off before something happens. An action with no "
                                "workflow just happens.", text_color=MUTED, anchor="w", justify="left",
                     wraplength=width - 40).grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 6))
        self.panes = {}
        for action in workflow.ACTIONS:
            tab = self.tabs.add(workflow.label_of(action))
            tab.columnconfigure(0, weight=1)
            tab.rowconfigure(2, weight=1)
            self.panes[action] = tab
            self._redraw(action)
        self.problem = ctk.CTkLabel(self, text="", text_color=ERROR, anchor="w", justify="left",
                                    wraplength=width - 40)
        self.problem.grid(row=2, column=0, sticky="ew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=(6, 16))
        buttons.columnconfigure(0, weight=1)
        ReleaseButton(buttons, text="Add standard workflows", width=190, height=38, fg_color=PURPLE,
                      hover_color=PURPLE_HOVER, command=self._standard).grid(row=0, column=0, sticky="w")
        ReleaseButton(buttons, text="Cancel", width=110, height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=1, padx=(6, 6))
        ReleaseButton(buttons, text="OK", width=110, height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._save).grid(row=0, column=2)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _cancel(self):
        if self.editor.dirty and not ask_discard(self, "your changes to the workflows"):
            return
        self.destroy()

    # -- drawing -----------------------------------------------------------
    def _redraw(self, action):
        pane = self.panes[action]
        for child in pane.winfo_children():
            child.destroy()
        names = self.editor.names(action)
        index = min(self.selected[action], max(len(names) - 1, 0))
        self.selected[action] = index
        top = ctk.CTkFrame(pane, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        label = workflow.label_of(action)
        if not names:
            ctk.CTkLabel(top, text=f"No {label} workflow, so {label.lower()} just happens.", text_color=MUTED,
                         anchor="w").grid(row=0, column=0, padx=(0, 10), pady=4)
        else:
            self.selected_var = tk.StringVar(value=names[index])
            ctk.CTkOptionMenu(top, variable=self.selected_var, values=names, width=200, height=32, fg_color=GRAY,
                              button_color=GRAY_HOVER, button_hover_color=ACCENT,
                              command=lambda value, a=action: self._select(a, value)).grid(row=0, column=0,
                                                                                         padx=(0, 6), pady=4)
        ReleaseButton(top, text="New workflow", width=120, height=32, fg_color=ACCENT, hover_color="#18527f",
                      command=lambda: self._new(action)).grid(row=0, column=1, padx=(0, 6))
        if names:
            ReleaseButton(top, text="Delete", width=80, height=32, fg_color=RED, hover_color=RED_HOVER,
                          command=lambda: self._delete(action)).grid(row=0, column=2)
            name_row = ctk.CTkFrame(pane, fg_color="transparent")
            name_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
            ctk.CTkLabel(name_row, text="Name:", text_color=MUTED).grid(row=0, column=0, padx=(0, 6))
            var = tk.StringVar(value=names[index])
            self.name_vars[action] = var
            var.trace_add("write", lambda *_: self._rename(action, var.get()))
            ctk.CTkEntry(name_row, textvariable=var, width=220, height=30).grid(row=0, column=1)
            holder = ctk.CTkScrollableFrame(pane, fg_color=BG_PANEL, corner_radius=10)
            holder.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
            item = self.editor.items[action][index]
            for number, roles in enumerate(item["rows"]):
                self._draw_row(holder, action, index, number, roles)
            foot = ctk.CTkFrame(pane, fg_color="transparent")
            foot.grid(row=3, column=0, sticky="ew", pady=(8, 0))
            ReleaseButton(foot, text="Add a sign-off", width=130, height=30, fg_color=GRAY, hover_color=GRAY_HOVER,
                          command=lambda: self._add_row(action, index)).grid(row=0, column=0, sticky="w")
            same = tk.BooleanVar(value=item["same"])
            req = tk.BooleanVar(value=item["requester"])
            ctk.CTkCheckBox(foot, text="One person may fill more than one sign-off", variable=same,
                            command=lambda: item.update(same=bool(same.get()))).grid(row=1, column=0, sticky="w",
                                                                                     pady=(8, 0))
            ctk.CTkCheckBox(foot, text="The person who asks may be a signer", variable=req,
                            command=lambda: item.update(requester=bool(req.get()))).grid(row=2, column=0,
                                                                                         sticky="w", pady=(6, 0))

    def _draw_row(self, holder, action, index, number, roles):
        line = ctk.CTkFrame(holder, fg_color="transparent")
        line.grid(row=number, column=0, sticky="w", pady=(6 if number == 0 else 3, 0), padx=6)
        ctk.CTkLabel(line, text=f"Sign-off {number + 1}", width=80, anchor="w", text_color=MUTED).grid(
            row=0, column=0, padx=(0, 6))
        column = 1
        for position, role in enumerate(roles):
            if position:
                ctk.CTkLabel(line, text="or", text_color=MUTED).grid(row=0, column=column, padx=4)
                column += 1
            var = tk.StringVar(value=role)
            ctk.CTkOptionMenu(line, variable=var, values=self.roles or [role], width=170, height=30, fg_color=GRAY,
                              button_color=GRAY_HOVER, button_hover_color=ACCENT,
                              command=lambda value, a=action, i=index, n=number, p=position:
                              self.editor.set_role(a, i, n, p, value)).grid(row=0, column=column)
            column += 1
            if len(roles) > 1:
                ReleaseButton(line, text="x", width=26, height=26, fg_color=GRAY, hover_color=GRAY_HOVER,
                              command=lambda a=action, i=index, n=number, p=position: self._remove_or(a, i, n, p)
                              ).grid(row=0, column=column, padx=(2, 0))
                column += 1
        ReleaseButton(line, text="+ or", width=50, height=30, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=lambda: self._add_or(action, index, number)).grid(row=0, column=column, padx=(8, 4))
        ReleaseButton(line, text="Remove", width=76, height=30, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=lambda: self._remove_row(action, index, number)).grid(row=0, column=column + 1)

    # -- changes -----------------------------------------------------------
    def _select(self, action, name):
        self.selected[action] = self.editor.names(action).index(name)
        self._redraw(action)

    def _new(self, action):
        if not self.roles:
            self.problem.configure(text="This org has no roles yet. Add some in Team... > Roles first.")
            return
        self.selected[action] = self.editor.add(action, self.roles)
        self._redraw(action)

    def _delete(self, action):
        names = self.editor.names(action)
        index = self.selected[action]
        if names and messagebox.askyesno("Delete workflow", f"Delete the {workflow.label_of(action)} workflow "
                                         f"'{names[index]}'? Requests already waiting keep their sign-offs.",
                                         parent=self):
            self.editor.delete(action, index)
            self._redraw(action)

    def _rename(self, action, text):
        index = self.selected[action]
        if index < len(self.editor.items[action]):
            self.editor.items[action][index]["name"] = text

    def _add_row(self, action, index):
        self.editor.add_row(action, index, self.roles)
        self._redraw(action)

    def _remove_row(self, action, index, number):
        self.editor.remove_row(action, index, number)
        self._redraw(action)

    def _add_or(self, action, index, number):
        if self.editor.add_or(action, index, number, self.roles) is None:
            self.problem.configure(text="Every role is already listed on that sign-off.")
            return
        self._redraw(action)

    def _remove_or(self, action, index, number, position):
        self.editor.remove_or(action, index, number, position)
        self._redraw(action)

    def _standard(self):
        added, skipped = self.editor.add_standard(self.roles)
        for action in workflow.ACTIONS:
            self._redraw(action)
        lines = []
        if added:
            lines.append("Added: " + ", ".join(added) + ".")
        if skipped:
            lines.append("Not added because the org lacks these roles (add them in Team... > Roles first): "
                         + "; ".join(f"{name} needs {', '.join(missing)}" for name, missing in skipped) + ".")
        if not lines:
            lines.append("The standard workflows are all there already.")
        messagebox.showinfo("Standard workflows", "\n\n".join(lines), parent=self)

    def _save(self):
        if not self.editor.dirty:
            self.destroy()
            return
        problem = self.editor.problem()
        if problem:
            self.problem.configure(text=problem)
            return
        ops = self.editor.ops()
        if self.apply is not None:
            problem = self.apply(ops, self.editor)
            self.problem.configure(text=problem)
            if problem:
                return
        self.result = ops
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class WorkflowRequestDialog(ctk.CTkToplevel):
    """Start a workflow on some parts: pick a template, name a person for each sign-off, add optional extras.

        result = WorkflowRequestDialog(parent, action, parts, templates, directory, my_id).show()
        # None if cancelled, else {'template': name, 'assignments': [person ids], 'extras': [(role, id)],
        #                          'reason': text}
    Submit asks for a last confirmation before it returns.
    """

    CHOOSE = "Choose a person..."

    def __init__(self, parent, action, parts, templates, directory, my_id):
        super().__init__(parent)
        set_window_icon(self)
        self.result = None
        self.action, self.parts, self.templates = action, parts, templates
        self.directory, self.my_id = directory, my_id
        self.row_vars, self.row_ids, self.extras = [], [], []
        label = workflow.label_of(action)
        width, height = 680, 700
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title(f"{label} workflow")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(600, 520)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        ctk.CTkLabel(self, text=f"{label}: start a workflow", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        box = ctk.CTkTextbox(self, height=min(30 + 20 * len(parts), 120), fg_color=BG_PANEL)
        box.grid(row=1, column=0, sticky="ew", padx=20)
        box.insert("1.0", "\n".join(f"{pn}   {name}".rstrip() for pn, name in parts))
        box.configure(state="disabled")
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        ctk.CTkLabel(top, text="Workflow:").grid(row=0, column=0, padx=(0, 8))
        names = list(templates)
        self.template_var = tk.StringVar(value=names[0])
        ctk.CTkOptionMenu(top, variable=self.template_var, values=names, width=220, height=32, fg_color=GRAY,
                          button_color=GRAY_HOVER, button_hover_color=ACCENT,
                          command=lambda value: self._rebuild()).grid(row=0, column=1)
        self.reason_var = tk.StringVar()
        if action in workflow.NEEDS_REASON:
            reason = ctk.CTkFrame(self, fg_color="transparent")
            reason.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 0))
            reason.columnconfigure(1, weight=1)
            ctk.CTkLabel(reason, text="Reason:").grid(row=0, column=0, padx=(0, 8))
            ctk.CTkEntry(reason, textvariable=self.reason_var, height=32,
                         placeholder_text=f"Why is this being {label.lower()}ed? (a few words)").grid(
                row=0, column=1, sticky="ew")
        self.note = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w", justify="left", wraplength=width - 40)
        self.note.grid(row=4, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.holder = ctk.CTkScrollableFrame(self, fg_color=BG_PANEL, corner_radius=10)
        self.holder.grid(row=5, column=0, sticky="nsew", padx=20, pady=(8, 0))
        self.holder.columnconfigure(1, weight=1)
        ReleaseButton(self, text="Add an optional sign-off", width=190, height=30, fg_color=GRAY,
                      hover_color=GRAY_HOVER, command=self._add_extra).grid(row=6, column=0, sticky="w", padx=20,
                                                                             pady=(8, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=ERROR, anchor="w", justify="left",
                                    wraplength=width - 40)
        self.problem.grid(row=7, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=8, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text="Submit workflow", height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._submit).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self._rebuild()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    @property
    def template(self):
        return self.templates[self.template_var.get()]

    def _menu(self, parent, choices, var):
        values = [self.CHOOSE] + [label for label, _id in choices]
        return ctk.CTkOptionMenu(parent, variable=var, values=values, width=260, height=30, fg_color=GRAY,
                                 button_color=GRAY_HOVER, button_hover_color=ACCENT)

    def _rebuild(self):
        """Redraw the sign-off rows for the chosen template (extras are kept)."""
        for child in self.holder.winfo_children():
            child.destroy()
        template = self.template
        self.row_vars, self.row_ids = [], []
        for number, row in enumerate(template.rows):
            choices = logic.row_choices(self.directory, row.roles, self.my_id, template.requester_may_sign)
            var = tk.StringVar(value=choices[0][0] if len(choices) == 1 else self.CHOOSE)
            ctk.CTkLabel(self.holder, text=row.text(), anchor="w", width=190).grid(
                row=number, column=0, sticky="w", padx=(8, 8), pady=(8 if number == 0 else 3, 0))
            self._menu(self.holder, choices, var).grid(row=number, column=1, sticky="w",
                                                       pady=(8 if number == 0 else 3, 0))
            self.row_vars.append(var)
            self.row_ids.append({label: pid for label, pid in choices})
        self._redraw_extras()
        notes = []
        if not template.allow_same_person:
            notes.append("One person can't fill more than one sign-off.")
        if not template.requester_may_sign:
            notes.append("You can't sign your own request.")
        notes += workflow.role_warnings(template, self.directory)
        self.note.configure(text=" ".join(notes))

    def _redraw_extras(self):
        for child in list(getattr(self, "extra_frames", [])):
            child.destroy()
        self.extra_frames = []
        start = len(self.row_vars)
        for number, extra in enumerate(self.extras):
            frame = ctk.CTkFrame(self.holder, fg_color="transparent")
            frame.grid(row=start + number, column=0, columnspan=2, sticky="w", padx=8, pady=(3, 0))
            self.extra_frames.append(frame)
            ctk.CTkOptionMenu(frame, variable=extra["role"], values=self.directory.roles or [extra["role"].get()],
                              width=180, height=30, fg_color=GRAY, button_color=GRAY_HOVER,
                              button_hover_color=ACCENT,
                              command=lambda value, e=extra: self._extra_role(e)).grid(row=0, column=0, padx=(0, 8))
            choices = logic.row_choices(self.directory, [extra["role"].get()])
            extra["ids"] = {label: pid for label, pid in choices}
            self._menu(frame, choices, extra["person"]).grid(row=0, column=1)
            ReleaseButton(frame, text="Remove", width=76, height=30, fg_color=GRAY, hover_color=GRAY_HOVER,
                          command=lambda e=extra: self._remove_extra(e)).grid(row=0, column=2, padx=(8, 0))

    def _add_extra(self):
        if not self.directory.roles:
            return
        self.extras.append({"role": tk.StringVar(value=self.directory.roles[0]), "person": tk.StringVar(
            value=self.CHOOSE), "ids": {}})
        self._redraw_extras()

    def _extra_role(self, extra):
        extra["person"].set(self.CHOOSE)
        self._redraw_extras()

    def _remove_extra(self, extra):
        self.extras.remove(extra)
        self._redraw_extras()

    def _submit(self):
        assignments = [ids.get(var.get(), "") for var, ids in zip(self.row_vars, self.row_ids)]
        extras = [(e["role"].get(), e["ids"].get(e["person"].get(), "")) for e in self.extras]
        reason = " ".join(self.reason_var.get().split())
        try:
            slots = workflow.build_slots(self.template, self.directory, self.my_id, assignments, extras)
        except workflow.WorkflowError as e:
            self.problem.configure(text=logic.shorten(str(e)))
            return
        if self.action in workflow.NEEDS_REASON and not reason:
            self.problem.configure(text="A reason is required.")
            return
        self.problem.configure(text="")
        text = logic.request_confirm_text(self.action, self.parts, self.template, slots, reason,
                                          workflow.role_warnings(self.template, self.directory))
        if not messagebox.askokcancel("Start the workflow?", text, parent=self):
            return
        self.result = {"template": self.template.name, "assignments": assignments, "extras": extras,
                       "reason": reason}
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class ReassignDialog(ctk.CTkToplevel):
    """Change who signs a sign-off that hasn't been given. show() gives (slot index, person id) or None."""

    def __init__(self, parent, task, directory, requester_may_sign=True):
        super().__init__(parent)
        set_window_icon(self)
        self.result, self.task, self.directory = None, task, directory
        self.open = [(i, s) for i, s in enumerate(task.slots) if not s["done"]]
        width, height = 520, 260
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Change who signs")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Change who signs", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        self.slot_labels = {f"{s['text']}  (now {s['name']})": i for i, s in self.open}
        self.slot_var = tk.StringVar(value=next(iter(self.slot_labels)))
        ctk.CTkOptionMenu(self, variable=self.slot_var, values=list(self.slot_labels), width=470, fg_color=GRAY,
                          button_color=GRAY_HOVER, button_hover_color=ACCENT,
                          command=lambda value: self._people()).grid(row=1, column=0, padx=20, sticky="w")
        self.person_var = tk.StringVar()
        self.person_menu = ctk.CTkOptionMenu(self, variable=self.person_var, values=[""], width=470, fg_color=GRAY,
                                             button_color=GRAY_HOVER, button_hover_color=ACCENT)
        self.person_menu.grid(row=2, column=0, padx=20, pady=(8, 0), sticky="w")
        self.problem = ctk.CTkLabel(self, text="", text_color=ERROR, anchor="w")
        self.problem.grid(row=3, column=0, sticky="ew", padx=20, pady=(6, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="ew", padx=20, pady=(8, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        ReleaseButton(buttons, text="Cancel", height=38, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ReleaseButton(buttons, text="OK", height=38, fg_color=GREEN, hover_color=GREEN_HOVER,
                      command=self._ok).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.ids = {}
        self._people()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _people(self):
        index = self.slot_labels[self.slot_var.get()]
        choices = logic.row_choices(self.directory, self.task.slots[index]["roles"])
        self.ids = {label: pid for label, pid in choices}
        self.person_menu.configure(values=[label for label, _ in choices] or ["(nobody holds the role)"])
        self.person_var.set(choices[0][0] if choices else "(nobody holds the role)")

    def _ok(self):
        pid = self.ids.get(self.person_var.get())
        if not pid:
            self.problem.configure(text="Choose a person.")
            return
        self.result = (self.slot_labels[self.slot_var.get()], pid)
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result


class TasksWindow(ctk.CTkToplevel):
    """My Tasks: workflow requests waiting for sign-off, and what you can do about each."""

    def __init__(self, app):
        super().__init__(app)
        set_window_icon(self)
        self.app = app
        self.tasks = {}
        self.title("My Tasks")
        self.geometry("1060x480")
        self.minsize(780, 340)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.summary = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=1000)
        self.summary.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        frame = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in logic.TASK_COLUMNS], show="headings",
                                 selectmode="browse")
        for name, _title, width in logic.TASK_COLUMNS:
            self.tree.column(name, width=width, anchor="w")
        TableSorter(self.tree, [(c[0], c[1]) for c in logic.TASK_COLUMNS])
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._update_buttons())
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 4))
        self.action_buttons = {}
        for column, (key, text, color, hover, width) in enumerate((
                ("sign", "Approve", GREEN, GREEN_HOVER, 110), ("reject", "Reject...", RED, RED_HOVER, 110),
                ("complete", "Complete", PURPLE, PURPLE_HOVER, 110), ("reassign", "Change signer...", GRAY,
                                                                      GRAY_HOVER, 140),
                ("withdraw", "Withdraw", GRAY, GRAY_HOVER, 100),
                ("override", "Admin override...", GRAY, GRAY_HOVER, 150), ("close", "Close", GRAY, GRAY_HOVER, 80))):
            command = self.destroy if key == "close" else (lambda k=key: self._act(k))
            button = ReleaseButton(row, text=text, width=width, fg_color=color, hover_color=hover, command=command)
            button.grid(row=0, column=column, padx=(0, 6))
            self.action_buttons[key] = button
        self.detail = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=1000)
        self.detail.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.why = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w", justify="left", wraplength=1000)
        self.why.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.reload()
        self.after(100, self.lift)

    def reload(self):
        """Redraw from the part list the main window last loaded."""
        keep = self.tree.selection()
        tasks = workflow.tasks_from_rows(self.app.rows, self.app.identity)
        self.tasks = {t.id: t for t in tasks}
        self.tree.delete(*self.tree.get_children())
        for iid, values in logic.tasks_table(tasks):
            self.tree.insert("", "end", iid=iid, values=values)
        mine = workflow.count_for_me(tasks)
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
        self.detail.configure(text=logic.task_detail(task) if task else "")
        self.why.configure(text=(task.why_not_sign if task and not task.can_sign and not task.ready else ""))

    def _act(self, key):
        task = self._task()
        if task is None:
            return
        {"sign": self.app.task_sign, "reject": self.app.task_reject, "complete": self.app.task_complete,
         "withdraw": self.app.task_withdraw, "override": self.app.task_override,
         "reassign": self.app.task_reassign}[key](task)


class TeamWindow(ctk.CTkToplevel):
    """The team list: who may do what. Everyone can look; Admins and the Owner can change it."""

    def __init__(self, app):
        super().__init__(app)
        set_window_icon(self)
        self.app = app
        self.title("Team")
        self.geometry("1000x560")
        self.minsize(760, 420)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.summary = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=940)
        self.summary.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        frame = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = (("name", "Name", 170), ("email", "Email", 190), ("access", "Access", 70), ("roles", "Roles", 200),
                   ("active", "On", 40), ("hosts", "Host names", 200), ("keys", "Keys", 50))
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse")
        for name, _title, width in columns:
            self.tree.column(name, width=width, anchor="w")
        TableSorter(self.tree, [(c[0], c[1]) for c in columns])
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.buttons = ctk.CTkFrame(self, fg_color="transparent")
        self.buttons.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 4))
        self.status = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w", justify="left", wraplength=940)
        self.status.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.busy = False
        self.draft = None               # your unsaved changes (team_draft.TeamDraft); None until the team exists
        self.save_button = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda event: self.close())
        self.reload()
        self.after(100, self.lift)

    BUTTONS_PER_ROW = 5                 # more than this and the buttons start a new row instead of running off

    def _button(self, text, command, color=GRAY, hover=GRAY_HOVER, width=130):
        button = ReleaseButton(self.buttons, text=text, width=width, fg_color=color, hover_color=hover,
                               command=command)
        index = len(self.buttons.winfo_children()) - 1
        button.grid(row=index // self.BUTTONS_PER_ROW, column=index % self.BUTTONS_PER_ROW, padx=(0, 6),
                    pady=(0, 6), sticky="w")
        return button

    def close(self):
        """Close the window; if there are unsaved changes, ask first."""
        if self.draft is not None and self.draft.dirty and not ask_discard(self, "all the unsaved team changes"):
            return
        self.destroy()

    def _new_draft(self):
        identity = self.app.identity
        if identity.state == people.LEGACY or identity.directory is None:
            return None
        try:
            templates = workflow.load(self.app.repo())
        except engine.LitterboxError:
            templates = {}
        return TeamDraft(identity.directory, templates, identity.person.id if identity.person else "")

    def say(self, text, tone="normal"):
        """Show what Litterbox is doing, so you can see a click did something."""
        self.status.configure(text=text, text_color={"normal": MUTED, "warn": WARN, "error": ERROR}.get(tone, MUTED))

    def set_busy(self, busy):
        self.busy = busy
        if not busy:
            self.reload()                        # also puts the Save button back to the right state
            return
        for button in self.buttons.winfo_children():
            button.configure(state="disabled")

    def reload(self):
        """Redraw from the vault's team file and the current identity."""
        for child in self.buttons.winfo_children():
            child.destroy()
        identity = self.app.identity
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        if self.draft is None or not self.draft.dirty:      # nothing unsaved: show the vault as it is now
            self.draft = self._new_draft()
        directory = self.draft.directory if self.draft is not None else identity.directory
        if identity.state == people.LEGACY:
            directory = None
        elif directory is None:
            try:
                directory = people.load(self.app.repo())
            except engine.LitterboxError:
                directory = None
        self.save_button = None
        if directory is None:
            self.summary.configure(text="This vault has no team list yet, so everyone can do everything. Setting "
                                        "one up makes you the Owner; then only people you add can change anything.")
            self._button("Set Up Team", self.app.set_up_team, ACCENT, "#18527f")
        else:
            for iid, values in logic.people_table(directory):
                self.tree.insert("", "end", iid=iid, values=values)
            unsaved = self.draft.summary() if self.draft is not None else ""
            self.summary.configure(text=f"You: {identity.describe()}."
                                        + (f"\n{unsaved}. Press Save to upload them." if unsaved else ""))
            if identity.allows("manage_people")[0]:
                self._button("Add Person", lambda: self.app.edit_person(self, None, adding=True))
                self._button("Edit", lambda: self.app.edit_person(self, self._selected()))
                self._button("Switch On/Off", lambda: self.app.toggle_person(self, self._selected()))
                self._button("Roles...", lambda: self.app.edit_roles(self))
            if identity.allows("manage_workflows")[0]:
                self._button("Workflows...", lambda: self.app.edit_workflow(self), PURPLE, PURPLE_HOVER)
            if identity.allows("transfer_owner")[0]:
                self._button("Transfer Ownership", lambda: self.app.transfer_owner(self, self._selected()), PURPLE,
                             PURPLE_HOVER, 150)
        self._button("Who am I?", self.app.who_am_i)
        self._button("Signing...", lambda: SigningDialog(self.app, self.app.repo()))
        if self.draft is not None and (identity.allows("manage_people")[0] or identity.allows("manage_workflows")[0]):
            self.save_button = self._button("Save", lambda: self.app.save_team(self), GREEN, GREEN_HOVER, 100)
            self.save_button.configure(state="normal" if self.draft.dirty and not self.busy else "disabled")
        self._button("Close", self.close)
        for iid in keep:                                    # keep the same person selected after a change
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
        if self.busy:
            for button in self.buttons.winfo_children():
                button.configure(state="disabled")

    def _selected(self):
        chosen = self.tree.selection()
        return chosen[0] if chosen else None


class App(ctk.CTk):
    identity = people.Identity(people.LEGACY)       # replaced after the first refresh

    def __init__(self):
        super().__init__()
        # Icon first, and keep the window hidden until it is fully built, so the user
        # never sees it half-ready or with the wrong icon. (CustomTkinter supports
        # calling withdraw() right after creating the window.)
        self.settings = settings.load()
        settings.DEBUG = engine.DEBUG = settings.is_debug(self.settings)
        if logic.migrate_settings(self.settings, self._detect_org):
            settings.save(self.settings)
        self.org = logic.current_org(self.settings)
        ICON_SETTING["choice"] = self.settings.get("icon", logic.DEFAULT_ICON)
        set_window_icon(self, main_window=True)
        self.withdraw()
        self.title(f"Litterbox {version.display()}")
        self.geometry("1100x740")
        self.minsize(1000, 600)

        self.queue = queue.Queue()      # messages from the background thread to the window
        self.busy = False
        self.rows = []                  # every PartStatus from the engine
        self.identity = people.Identity(people.LEGACY)      # who you are on this vault's team (see people.py)
        self.rows_by_pn = {}
        self.buttons = []               # disabled while something is running
        self.action_buttons = {}        # button text -> button, for the ones that follow the selection
        self.pending_select = None      # a part to select once the list reloads (the one just created)
        self.note = ""                  # what just happened, kept in the status line after a refresh

        # Everything the engine logs ("> git lfs lock ...") shows up in the log box.
        engine.LOG = lambda message: self.queue.put(("log", message))

        self._build_ui()
        self.bind("<F5>", lambda event: self.refresh())
        self.after(100, self._poll_queue)
        if settings.DEBUG:
            self._watch_for_freezes()

        if self.org and Path(self.repo()).is_dir():
            if AUTO_GET_LATEST_ON_START:
                self.get_latest()
            else:
                self.refresh()
        elif self.org:
            self._say(f"The vault folder for {self.org} wasn't found: {self.repo()}. Use Org setup to fix it.", "warn")
        else:
            self._say("Choose Add org... in the box next to the title to get started.", "warn")

        self.after(120, self._reveal)
        self.after(4000, self._start_update_check)

    # ------------------------------------------------------------------
    # Updates (see updater.py)
    # ------------------------------------------------------------------
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
                raise engine.LitterboxError(str(e))

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
                raise engine.LitterboxError(str(e))

        self.run_task(work, "Downloaded the update", on_success=self._run_installer, refresh=False)

    def _run_installer(self, path):
        try:
            updater.launch_installer(path)
        except updater.UpdateError as e:
            messagebox.showerror("Litterbox", str(e))
            return
        self._say("Updating... Litterbox will start again by itself.")
        self.after(500, self.destroy)               # the installer replaces the program's files once we've closed

    def _reveal(self):
        """Show the window now that the icon is set and everything is built."""
        self.deiconify()
        self.lift()

    # ------------------------------------------------------------------
    # Building the window
    # ------------------------------------------------------------------
    def _button(self, parent, text, command, **options):
        button = ReleaseButton(parent, text=text, command=command, **options)
        self.buttons.append(button)
        if text in logic.BUTTON_ACTIONS:
            self.action_buttons[text] = button
        return button

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header and vault folder
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 6))
        header.columnconfigure(0, weight=1)
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_row, text="Litterbox", font=ctk.CTkFont(size=26, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.org_var = tk.StringVar(value=self.org or "No org")
        self.org_menu = ctk.CTkOptionMenu(
            title_row, variable=self.org_var, values=logic.org_menu_values(self.settings), width=120,
            height=32, fg_color=GRAY, button_color=GRAY_HOVER, button_hover_color=ACCENT,
            command=self.on_org_chosen)
        self.org_menu.grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.buttons.append(self.org_menu)
        who_box = ctk.CTkFrame(header, fg_color="transparent")
        who_box.grid(row=0, column=1, rowspan=3, sticky="ne")
        self.identity_label = ctk.CTkLabel(who_box, text="", text_color=MUTED, anchor="e")
        self.identity_label.grid(row=0, column=0, padx=(0, 10))
        self.tasks_button = self._button(who_box, "My Tasks", self.show_tasks, width=100, height=30, fg_color=GRAY,
                                         hover_color=GRAY_HOVER)
        self.tasks_button.grid(row=0, column=1, padx=(0, 6))
        team_button = self._button(who_box, "Team...", self.show_team, width=90, height=30, fg_color=GRAY,
                                   hover_color=GRAY_HOVER)
        team_button.grid(row=0, column=2)
        for button in (team_button, self.tasks_button):
            self.buttons.remove(button)         # opening these windows only reads, so they work while busy
        self.update_button = ctk.CTkButton(
            who_box, text=f"Version {version.display()}  -  check for updates", width=0, height=22, fg_color="transparent",
            hover_color=GRAY_HOVER, text_color=MUTED, font=ctk.CTkFont(size=11), command=self.check_for_updates)
        self.update_button.grid(row=1, column=0, columnspan=3, sticky="e", pady=(4, 0))
        ctk.CTkLabel(header, text="Shared vault check-in / check-out", text_color=MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w")
        self.folder_label = ctk.CTkLabel(header, text=self.repo(), text_color=MUTED, anchor="w")
        self.folder_label.grid(row=2, column=0, sticky="w", pady=(2, 0))

        # Search, filters, refresh
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=24, pady=(8, 8))
        toolbar.columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(toolbar, placeholder_text="Search part number, name or description...", height=34)
        self.search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search.bind("<KeyRelease>", lambda event: self._render())
        self.view = ctk.CTkSegmentedButton(toolbar, values=list(logic.VIEWS), command=lambda value: self._render())
        self.view.set("All")
        self.view.grid(row=0, column=1, padx=(0, 8))
        self.void_box = ctk.CTkCheckBox(toolbar, text="Show void", command=self._render, width=90)
        self.void_box.grid(row=0, column=2, padx=(0, 8))
        self.deselect_button = ctk.CTkButton(toolbar, text="Deselect All", width=96, height=34, fg_color=GRAY,
                                             hover_color=GRAY_HOVER, command=self._deselect_all)
        self.deselect_button.grid(row=0, column=3, padx=(0, 8))
        self._button(toolbar, "Refresh", self.refresh, width=84, height=34,
                     fg_color=GRAY, hover_color=GRAY_HOVER).grid(row=0, column=4, padx=(0, 8))
        self._button(toolbar, "Get Latest", self.get_latest, width=100, height=34,
                     fg_color=GRAY, hover_color=GRAY_HOVER).grid(row=0, column=5)

        # The list of parts
        frame = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=10)
        frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        style_tables()
        self.tree = ttk.Treeview(frame, columns=("tick", "pn", "name", "description", "cots", "rev", "state", "files"),
                                 show="headings", selectmode="browse",
                                 style="Parts.Treeview")
        main_columns = (("pn", "Part number", 140, False),
                        ("name", "Name", 240, True),
                        ("description", "Description", 220, True),
                        ("cots", "COTS", 60, False),
                        ("rev", "Rev", 50, False),
                        ("state", "Status", 230, False),
                        ("files", "Files", 110, False))
        for name, title, width, stretch in main_columns:
            self.tree.column(name, width=width, anchor="w", stretch=stretch)
        self.sorter = TableSorter(self.tree, [(name, title) for name, title, _w, _s in main_columns])
        # The tick boxes: tick parts to act on several at once without worrying about the highlight.
        self.ticked = set()
        self.tree.column("tick", width=40, minwidth=40, anchor="center", stretch=False)
        self.tree.heading("tick", text=logic.TICK_OFF, anchor="center", command=self._toggle_all_ticks)
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<space>", self._tick_highlighted)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._update_buttons(), add="+")
        for kind, color in ROW_COLORS.items():
            self.tree.tag_configure(kind, foreground=color)
        self.tree.tag_configure("ticked", background=TICK_BG)       # last, so it wins for the background only
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.tree.bind("<Double-1>", self.show_history)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)

        # Everyday buttons
        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 6))
        row1.columnconfigure((0, 1, 2, 3, 4, 5), weight=1, uniform="a")
        big = ctk.CTkFont(size=14, weight="bold")
        for column, (text, command, color, hover) in enumerate((
            ("Check Out", self.check_out, ACCENT, "#18527f"),
            ("Check In", self.check_in, GREEN, GREEN_HOVER),
            ("Save Progress", self.save_progress, TEAL, TEAL_HOVER),
            ("Undo Checkout", self.undo_checkout, RED, RED_HOVER),
            ("Open", self.open_part, TEAL, TEAL_HOVER),
            ("Open Drawing", self.open_drawing, TEAL, TEAL_HOVER),
        )):
            self._button(row1, text, command, height=42, font=big, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 6, 0 if column == 5 else 6))

        # Making parts
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 6))
        row2.columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="b")
        for column, (text, command, color, hover) in enumerate((
            ("New Part", self.new_part, ACCENT, "#18527f"),
            ("Import...", self.import_cad, TEAL, TEAL_HOVER),
            ("Import COTS...", self.import_cots, TEAL, TEAL_HOVER),
            ("Edit Details", self.edit_details, ACCENT, "#18527f"),
            ("References...", self.show_references, TEAL, TEAL_HOVER),
        )):
            self._button(row2, text, command, height=34, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 4, 0 if column == 4 else 4))

        # A part's life: release, revise, and the less common changes
        row3 = ctk.CTkFrame(self, fg_color="transparent")
        row3.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 8))
        row3.columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1, uniform="b")
        for column, (text, command, color, hover) in enumerate((
            ("Release", self.release, PURPLE, PURPLE_HOVER),
            ("Revise", self.revise, PURPLE, PURPLE_HOVER),
            ("Cancel Revision", self.cancel_revision, GRAY, GRAY_HOVER),
            ("Make COTS", self.make_cots, TEAL, TEAL_HOVER),
            ("Unrelease", self.reopen, GRAY, GRAY_HOVER),
            ("Void", self.void, GRAY, GRAY_HOVER),
            ("History", self.show_history, GRAY, GRAY_HOVER),
        )):
            self._button(row3, text, command, height=34, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 4, 0 if column == 6 else 4))

        # Status line and log
        self.status = ctk.CTkLabel(self, text="Ready", text_color=MUTED, anchor="w")
        self.status.grid(row=6, column=0, sticky="ew", padx=26)
        self.log_box = ctk.CTkTextbox(self, height=110, fg_color=BG_PANEL, text_color=MUTED,
                                      font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=7, column=0, sticky="ew", padx=24, pady=(4, 20))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def repo(self):
        """The vault folder of the org that is open."""
        return logic.known_orgs(self.settings).get(self.org, "") if self.org else ""

    @staticmethod
    def _detect_org(folder):
        try:
            return config.get_org(folder)
        except Exception:
            return None

    def _reload_org_menu(self):
        self.org_menu.configure(values=logic.org_menu_values(self.settings))
        self.org_var.set(self.org or "No org")
        self.folder_label.configure(text=self.repo())

    def on_org_chosen(self, choice):
        """The dropdown changed: switch org (everything reloads) or open the setup pop-up."""
        if choice == logic.ADD_ORG:
            self._org_setup(None)
        elif choice == logic.CREATE_VAULT:
            self.create_vault()
        elif choice == logic.EDIT_ORG:
            self._org_setup(self.org)
        elif choice != self.org:
            self.switch_org(choice)
        self._reload_org_menu()

    def switch_org(self, org):
        self.org = org
        self.settings["last_org"] = org
        self.settings["repo"] = self.repo()
        settings.save(self.settings)
        self.rows, self.rows_by_pn, self.note = [], {}, ""
        self._render()                              # clear the list straight away
        self.folder_label.configure(text=self.repo())
        if Path(self.repo()).is_dir():
            self.refresh()
        else:
            self._say(f"The vault folder for {org} wasn't found: {self.repo()}. Use Org setup to fix it.", "warn")

    def _org_setup(self, org):
        """Add a new org (org=None) or edit one: its code, vault folder and starting part number."""
        folder = logic.known_orgs(self.settings).get(org, "") if org else ""
        start, base_digits, variant_digits = 1, pnmod.DEFAULT_BASE_DIGITS, pnmod.DEFAULT_VARIANT_DIGITS
        if folder and Path(folder).is_dir():
            try:
                start = config.get_start_number(folder)
                base_digits, variant_digits = config.get_digits(folder)
            except config.ConfigError:
                pass
        result = OrgDialog(self, org or "", folder, start, base_digits, variant_digits,
                           title="Add org" if not org else f"Org setup - {org}").show()
        if not result:
            return
        new_org, new_folder, new_start, new_base_digits, new_variant_digits = result
        try:
            config.save(new_folder, org=new_org, start_number=new_start,
                        base_digits=new_base_digits, variant_digits=new_variant_digits)
        except (config.ConfigError, OSError) as e:
            messagebox.showerror("Org setup", f"Could not save the settings in the vault:\n\n{e}", parent=self)
            return
        if org and org != new_org:
            orgs = logic.known_orgs(self.settings)
            orgs.pop(org, None)
            self.settings["orgs"] = orgs
        logic.remember_org(self.settings, new_org, new_folder)
        settings.save(self.settings)
        self.note = ("Saved. Commit and push .litterbox/config.yaml so your team gets the same org setup")
        self.switch_org(new_org)

    def create_vault(self):
        """Create new vault...: turn an empty cloned repository into a vault (see init_vault.py)."""
        if not messagebox.askyesno("Create new vault", logic.CREATE_VAULT_INTRO, parent=self):
            return
        result = OrgDialog(self, "", "", 1, pnmod.DEFAULT_BASE_DIGITS, pnmod.DEFAULT_VARIANT_DIGITS,
                           title="Create new vault", save_text="Create").show()
        if not result:
            return
        org, folder, start, base_digits, variant_digits = result
        checked = init_vault.plan(folder, org, start, base_digits, variant_digits)
        if not checked.ok:
            messagebox.showerror("Create new vault", "\n\n".join(checked.problems), parent=self)
            return
        if checked.warnings and not messagebox.askyesno(
                "Create new vault", "\n\n".join(checked.warnings) + "\n\nCreate the vault anyway?", parent=self):
            return

        def made(created):
            logic.remember_org(self.settings, created.org, folder)
            settings.save(self.settings)
            self._reload_org_menu()
            self.switch_org(created.org)
            messagebox.showinfo("Create new vault", logic.vault_created_text(created), parent=self)

        self.run_task(lambda: init_vault.create(folder, org, start, base_digits, variant_digits),
                      f"Created the {checked.org} vault", on_success=made, refresh=False)

    def _say(self, text, tone="normal"):
        color = {"normal": MUTED, "warn": WARN, "error": ERROR}[tone]
        self.status.configure(text=text, text_color=color)
        for window in self._team_windows():
            window.say(text, tone)

    def _popup_parent(self):
        """Where a pop-up should open. From a Team or My Tasks window it opens over that window, so closing it
        doesn't leave the main window in front."""
        try:
            focused = self.focus_get()
            top = focused.winfo_toplevel() if focused is not None else self
        except Exception:
            return self
        return top if isinstance(top, (TeamWindow, TasksWindow, WorkflowsDialog, WorkflowRequestDialog, ReassignDialog, RolesDialog,
                            PersonDialog)) else self

    def _team_windows(self):
        return [w for w in self.winfo_children() if isinstance(w, TeamWindow) and w.winfo_exists()]

    def _log(self, text):
        settings.append_log(text)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _watch_for_freezes(self, last=None):
        """Every quarter second; if the window was too busy to run this on time, say so in the log."""
        now = time.monotonic()
        if last is not None and now - last > 1.5:
            click_log(f"the window was frozen for {now - last:.1f}s")
        self.after(250, lambda: self._watch_for_freezes(now))

    def _set_busy(self, busy):
        click_log(f"busy={busy}")
        self.busy = busy
        for button in self.buttons:
            if button not in self.action_buttons.values():
                button.configure(state="disabled" if busy else "normal")
        self._update_buttons()
        for window in self._team_windows():
            window.set_busy(busy)

    def _ask(self, text, title):
        """Ask for one line of text. Returns None if the user cancels."""
        return InputDialog(text=text, title=title).get_input()

    def _update_buttons(self):
        """Grey out the buttons that can't be used on the current selection: a button is lit only if every part it
        would act on is one it can be used on. Everything is greyed while a task is running."""
        if not getattr(self, "action_buttons", None):
            return
        tree = self.tree
        highlighted = [parse_pn(iid) for iid in tree.selection()]
        states = logic.button_states(self._ticked_pns(), highlighted, self.rows_by_pn)
        for text, button in self.action_buttons.items():
            button.configure(state="normal" if states.get(text) and not self.busy else "disabled")
        deselect = getattr(self, "deselect_button", None)
        if deselect is not None:
            deselect.configure(state="normal" if self.ticked or highlighted else "disabled")

    def _deselect_all(self):
        """Clear every box (and the highlight)."""
        self._set_ticks(list(self.tree.get_children()) + list(self.ticked), False)
        self.tree.selection_set(*[])
        self._update_buttons()

    def _ticked_pns(self):
        """The ticked parts that are shown in the list right now (a tick on a filtered-out part is ignored)."""
        ticked = getattr(self, "ticked", set())
        return [parse_pn(iid) for iid in self.tree.get_children() if iid in ticked]

    def _selected_pns(self, action=None):
        """The parts an action applies to: see logic.choose_targets."""
        highlighted = [parse_pn(iid) for iid in self.tree.selection()]
        if action is None:
            return highlighted
        return logic.choose_targets(action, self._ticked_pns(), highlighted)

    def _on_tree_click(self, event):
        """A click in the tick column flips that row's box and leaves the highlight alone."""
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return None
        iid = self.tree.identify_row(event.y)
        if iid:
            shown = list(self.tree.get_children())
            anchor = getattr(self, "last_tick", None)
            if logic.shift_held(event) and anchor in shown:   # Shift: tick everything from the last click to here
                self._set_ticks(logic.range_between(shown, anchor, iid), anchor in self.ticked)
            else:
                self._set_ticks([iid], iid not in self.ticked)
            self.last_tick = iid
        return "break"

    def _tick_highlighted(self, event=None):
        chosen = list(self.tree.selection())
        if chosen:
            self._set_ticks(chosen, not all(iid in self.ticked for iid in chosen))
        return "break"

    def _toggle_all_ticks(self):
        shown = list(self.tree.get_children())
        self._set_ticks(shown, not (shown and all(iid in self.ticked for iid in shown)))

    def _set_ticks(self, iids, on):
        for iid in iids:
            (self.ticked.add if on else self.ticked.discard)(iid)
            if not self.tree.exists(iid):
                continue
            self.tree.set(iid, "tick", logic.TICK_ON if on else logic.TICK_OFF)
            kinds = [t for t in self.tree.item(iid, "tags") if t != "ticked"]
            self.tree.item(iid, tags=logic.row_tags(kinds[0], on) if kinds else ())
        shown = self.tree.get_children()
        self.tree.heading("tick", text=logic.TICK_ON if shown and all(i in self.ticked for i in shown) else logic.TICK_OFF)
        self._say(logic.tick_text(len(self._ticked_pns())))
        self._update_buttons()

    def _plan(self, action):
        """Work out what the selected parts allow. Shows the reason and returns None if nothing can be done."""
        allowed, why = self.identity.allows(action)
        if not allowed:
            self._say(why, "warn")
            return None
        plan = logic.plan_action(action, self._selected_pns(action), self.rows_by_pn)
        if plan.message:
            self._say(plan.message, "warn")
            return None
        return plan

    # ------------------------------------------------------------------
    # Running git work in the background so the window never freezes
    # ------------------------------------------------------------------
    def run_task(self, work, done_text, on_success=None, refresh=True, is_refresh=False):
        """Run work() in a thread. Then show done_text, call on_success(result), and refresh the list."""
        if self.busy:
            self._say("Still working on the last request...", "warn")
            return False
        self._set_busy(True)
        self._say("Working...")
        if settings.DEBUG:
            self._working_since = time.monotonic()
            self.after(1000, self._show_elapsed)

        def worker():
            try:
                result, error = work(), None
            except engine.NothingToSaveError as e:     # not a failure: nothing was different
                result, error = None, e
            except engine.LitterboxError as e:
                result, error = None, str(e)
            except Exception as e:                      # anything unexpected
                result, error = None, f"Unexpected error: {e!r}"
            self.queue.put(("done", (result, error, done_text, on_success, refresh, is_refresh)))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _show_elapsed(self):
        """While a task runs, show how long it has taken, so a slow host looks slow rather than stuck."""
        if not self.busy:
            return
        seconds = int(time.monotonic() - self._working_since)
        if seconds >= 3:
            self._say(f"Working... {seconds}s (the host may be slow)", "warn" if seconds >= 20 else "normal")
        self.after(1000, self._show_elapsed)

    def _poll_queue(self):
        try:
            self._drain_queue()
        finally:
            self.after(100, self._poll_queue)

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "update":
                    self._offer_update(payload)
                elif kind == "done":
                    try:
                        self._finish(*payload)
                    except Exception as e:              # a bug in a handler must not kill the window
                        self._log(f"INTERNAL ERROR: {e!r}")
                        self._set_busy(False)
                        messagebox.showerror("Litterbox", f"Something unexpected went wrong:\n{e!r}")
        except queue.Empty:
            pass

    def _finish(self, result, error, done_text, on_success, refresh, is_refresh):
        self._set_busy(False)
        if isinstance(error, engine.NothingToSaveError):
            self.note = ""
            self._say("Nothing to save: nothing was different.")
            messagebox.showinfo("Nothing to save", str(error), parent=self._popup_parent())
        elif error:
            self.note = ""
            self._log("ERROR: " + error)
            self._say("Something went wrong. See the message, or the log below.", "error")
            messagebox.showerror("Litterbox", logic.shorten(error), parent=self._popup_parent())
        else:
            if not is_refresh:
                self.note = done_text
            self._say(done_text)
            if on_success:
                on_success(result)
        if refresh:
            self.refresh()

    # ------------------------------------------------------------------
    # The list
    # ------------------------------------------------------------------
    def refresh(self):
        repo = self.repo()
        def work():
            def find_out_who():
                try:
                    return people.current(repo)
                except engine.LitterboxError as e:           # a damaged team file must not hide the parts
                    return people.Identity(people.UNVERIFIED, detail=str(e).splitlines()[0])

            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=2) as pool:      # the list and "who am I" don't depend on each other
                who_job = pool.submit(find_out_who)
                rows = engine.get_status(repo)
                who = who_job.result()
            if engine.DEBUG:
                engine.LOG(f"Refreshed the list in {time.monotonic() - started:.1f}s")
            return rows, who

        def show(result):
            rows, who = result
            self.identity = who
            self._show_identity()
            self._show_rows(rows)

        self.run_task(work, "Up to date", on_success=show, refresh=False, is_refresh=True)

    def _show_rows(self, rows):
        self.rows = rows
        self.rows_by_pn = {row.pn: row for row in rows}
        self._refresh_tasks()
        shown = self._render()
        if self.pending_select:
            if self.tree.exists(self.pending_select):
                self.tree.selection_set(self.pending_select)
                self.tree.see(self.pending_select)
            self.pending_select = None
        if not rows:
            self._say("No parts found. Check that this is your vault folder (it should contain a PN-logs folder).", "warn")
            return
        count = f"{shown} of {len(rows)} parts shown" if shown != len(rows) else f"{len(rows)} parts"
        ticked = len(self._ticked_pns())
        count += f"   |   {ticked} ticked" if ticked else ""
        self._say((self.note + "   |   " if self.note else "") + count)

    def _render(self):
        """Redraw the list using the search box and filters. Returns how many rows are shown."""
        rows = logic.filter_rows(self.rows, self.search.get(), self.view.get(), bool(self.void_box.get()))
        self.ticked &= {str(row.pn) for row in self.rows}                     # parts that no longer exist lose their tick
        previous = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", iid=str(row.pn), tags=logic.row_tags(row.kind, str(row.pn) in self.ticked), values=(
                logic.TICK_ON if str(row.pn) in self.ticked else logic.TICK_OFF,
                row.pn.short, row.name, row.description, "Yes" if row.cots else "", row.revision, row.state,
                logic.file_types(row.files)))
        keep = [str(row.pn) for row in rows if str(row.pn) in previous]
        if keep:
            self.tree.selection_set(*keep)
        self.sorter.apply()
        self._update_buttons()
        return len(rows)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def get_latest(self):
        repo = self.repo()
        self.run_task(lambda: engine.get_latest(repo), "Downloaded the latest changes",
                      on_success=lambda changed: self._warn_open_files(changed))

    def new_part(self):
        """Open the New Part pop-up, then create the number in the background."""
        if not self._may("create"):
            return
        if self.busy:
            self._say("Still working on the last request...", "warn")
            return
        if not self.org or not Path(self.repo()).is_dir():
            self._say("Choose an org with a vault folder first (box next to the title).", "warn")
            return
        repo, org = self.repo(), self.org
        request = NewPartDialog(self, repo, org).show()
        if not request:
            return
        def work():
            pn = create.new_part(repo, request["name"], request["description"],
                                 base=request["base"], variant=request["variant"], org=org)
            try:
                engine.checkout(repo, pn)            # a new part starts out checked out to its creator
            except engine.LitterboxError as e:
                return pn, str(e)
            return pn, ""

        def created(result):
            pn, problem = result
            self.note = f"Created {pn}" + (f" (could not check it out: {problem})" if problem else " and checked it out to you")
            self.pending_select = str(pn)
            self.search.delete(0, "end")            # make sure the new row isn't filtered out
            FilenameDialog(self, pn)

        self.run_task(work, "Created", on_success=created)

    def import_cots(self):
        """Open the Import COTS window: the same as Import, but every part is recorded as purchased."""
        self.import_cad(cots=True)

    def import_cad(self, cots=False):
        """Open the Import window (choose old CAD folders, review the table, Finish & Import)."""
        if not self._may("create"):
            return
        if self.busy:
            self._say("Still working on the last request...", "warn")
            return
        if not self.org or not Path(self.repo()).is_dir():
            self._say("Choose an org with a vault folder first (box next to the title).", "warn")
            return

        def imported(result):
            self.note = f"Imported {len(result.pns)} {'COTS ' if cots else ''}part(s)"
            self.search.delete(0, "end")
            repo, pns = self.repo(), list(result.pns)
            if cots or not pns:
                self.refresh()
                return
            # Record which parts each imported assembly uses (a separate small step after the import)
            self.run_task(lambda: references.rescan(repo, pns, log=lambda text: self.queue.put(("log", text))),
                          self.note)

        ImportWindow(self, self.repo(), self.org, imported, log=lambda text: self.queue.put(("log", text)), cots=cots)

    def _warn_open_files(self, paths):
        names = logic.cad_changes(paths)
        if names:
            messagebox.showinfo(
                "Newer versions downloaded",
                "These files were updated:\n\n  " + "\n  ".join(names) +
                "\n\nIf any of them are open in SolidWorks, close and reopen them "
                "so you aren't looking at an old copy.")

    def _show_identity(self):
        text, tone = logic.identity_banner(self.identity)
        self.identity_label.configure(text=text, text_color=WARN if tone == "warn" else MUTED)
        self._refresh_tasks()

    # ------------------------------------------------------------------
    # My Tasks and the release workflow (see workflow.py)
    # ------------------------------------------------------------------
    def _task_windows(self):
        return [w for w in self.winfo_children() if isinstance(w, TasksWindow) and w.winfo_exists()]

    def _refresh_tasks(self):
        """Update the My Tasks button's count and any open My Tasks window."""
        button = getattr(self, "tasks_button", None)
        if button is None:
            return
        tasks = workflow.tasks_from_rows(self.rows, self.identity)
        button.configure(text=logic.tasks_button_text(workflow.count_for_me(tasks)))
        for window in self._task_windows():
            window.reload()

    def show_tasks(self):
        windows = self._task_windows()
        if windows:
            windows[0].reload()
            windows[0].lift()
            return
        TasksWindow(self)

    def task_sign(self, task):
        comment = self._ask("Comment (optional):", f"Approve: {task.label}")
        if comment is None:
            return
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow.sign_off(repo, pns, comment), f"Signed off {task.label}",
                      on_success=lambda result: self._signed(task, result))

    def _signed(self, task, result):
        text, _warn = logic.signoff_result_text(result)
        if text:
            messagebox.showwarning("Sign-off saved", text)
        elif result.completed:
            self.note = f"Signed off; {workflow.label_of(task.action)} done on {len(result.completed)} part" \
                        f"{'s' if len(result.completed) != 1 else ''}"

    def task_reject(self, task):
        reason = self._ask_reason("Why are you rejecting it? The person who asked will see this.",
                                  f"Reject: {task.label}")
        if reason is None:
            return
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow.reject(repo, pns, reason), f"Rejected {task.label}")

    def task_complete(self, task):
        repo, pns = self.repo(), task.pns
        label = workflow.label_of(task.action)
        if messagebox.askokcancel(f"{label} {task.label}", f"Everyone needed has signed. {label} now?"):
            self.run_task(lambda: workflow.complete_many(repo, pns), f"{label} done: {task.label}")

    def task_withdraw(self, task):
        repo, pns = self.repo(), task.pns
        if messagebox.askyesno(f"Withdraw {task.label}", "Withdraw this request? The sign-offs so far are "
                                                         "discarded, and you can ask again later."):
            self.run_task(lambda: workflow.withdraw(repo, pns), f"Withdrew the request for {task.label}")

    def task_override(self, task):
        label = workflow.label_of(task.action)
        reason = self._ask_reason(f"Why {label.lower()} without the sign-offs? This is recorded permanently.",
                                  f"Admin override: {label.lower()} {task.label}")
        if reason is None:
            return
        repo, pns, action = self.repo(), task.pns, task.action
        if messagebox.askokcancel(f"{label} {task.label}", f"{label} without the required sign-offs?\n\nReason: "
                                                           f"{reason}\n\nThis is recorded as an Admin override."):
            self.run_task(lambda: workflow.override(repo, pns, reason, action=action),
                          f"{label} done: {task.label} (Admin override)")

    def task_reassign(self, task):
        directory = self.identity.directory
        if directory is None:
            return
        chosen = ReassignDialog(self, task, directory).show()
        if chosen is None:
            return
        slot, person_id = chosen
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow.reassign(repo, pns, slot, person_id), f"Changed who signs {task.label}")

    # -- starting a workflow ------------------------------------------------
    def _one_part_only(self, action, plan):
        """Without a workflow these actions work on one part at a time. True if that's what was chosen."""
        if len(plan.targets) == 1:
            return True
        self._say(f"Select just one part to {logic.NAME[action]}. (This vault has no workflow for it, so it happens "
                  "directly, one part at a time.)", "warn")
        return False

    def _workflow_start(self, action, plan):
        """If this vault has workflows for the action, deal with it here (open the Workflow window, or finish a
        request that has all its sign-offs) and return True. Return False when it should just happen."""
        repo = self.repo()
        try:
            templates = workflow.templates_for(repo, action)
        except engine.LitterboxError as e:
            messagebox.showerror("Litterbox", logic.shorten(str(e)))
            return True
        pending = [pn for pn in plan.targets if self.rows_by_pn[pn].kind == "pending"]
        if not templates and not pending:
            return False
        if pending:
            if len(pending) != len(plan.targets):
                self._say("Some of these already have a request waiting. Select them separately.", "warn")
            else:
                self._finish_pending(action, pending)
            return True
        directory, me = self.identity.directory, self.identity.person
        if directory is None or me is None:
            self._say("Set up the team first (Team... > Set Up Team): sign-offs are done by people on it.", "warn")
            return True
        parts = [(pn, self.rows_by_pn[pn].name) for pn in plan.targets]
        chosen = WorkflowRequestDialog(self, action, parts, templates, directory, me.id).show()
        if not chosen:
            return True
        pns, label = list(plan.targets), workflow.label_of(action)
        self.run_task(lambda: workflow.request(repo, pns, action, chosen["template"], chosen["assignments"],
                                               chosen["extras"], chosen["reason"]),
                      f"Started the {label} workflow on {len(pns)} part{'s' if len(pns) != 1 else ''}")
        return True

    def _finish_pending(self, action, pns):
        """The action's button on parts that already have a request: finish it if everyone has signed, else say
        what is missing."""
        repo, label = self.repo(), workflow.label_of(action)
        rows = [self.rows_by_pn[pn] for pn in pns]
        other = next((r for r in rows if r.pending.get("action") != action), None)
        if other is not None:
            messagebox.showinfo(label, f"{other.pn} has a {workflow.label_of(other.pending.get('action'))} request "
                                       "waiting for sign-offs. Open My Tasks to approve, reject or withdraw it.")
            return
        waiting = next((r for r in rows if not workflow.is_complete(r.pending)), None)
        if waiting is not None:
            messagebox.showinfo(label, f"{waiting.pn} is still waiting for: " + ", ".join(
                workflow.waiting_on(waiting.pending)) + ".\n\nOpen My Tasks to approve, reject or withdraw the "
                                                        "request.")
            return
        if messagebox.askokcancel(f"{label} {len(pns)} part{'s' if len(pns) != 1 else ''}",
                                  f"Everyone needed has signed. {label} now?"):
            self.run_task(lambda: workflow.complete_many(repo, pns), f"{label} done: {', '.join(map(str, pns))}")

    def _may(self, action):
        """True if you may do `action`; otherwise says why in the status line."""
        allowed, why = self.identity.allows(action)
        if not allowed:
            self._say(why, "warn")
        return allowed

    def show_team(self):
        click_log("opening the Team window")
        TeamWindow(self)
        click_log("the Team window is built")

    def who_am_i(self):
        repo = self.repo()
        parent = self._popup_parent()                   # the Team window if that's where you pressed it

        def show(who):
            self.identity = who
            self._show_identity()
            messagebox.showinfo("Who am I?", logic.who_am_i_text(who) if who.state != people.UNVERIFIED
                                else who.message(), parent=parent)

        self.run_task(lambda: people.current(repo, refresh=True), "Checked who you are", on_success=show,
                      refresh=False)

    def set_up_team(self):
        if not messagebox.askokcancel(
                "Set up the team",
                "This creates the team list for this vault and makes YOU its Owner.\n\nFrom then on, only people an "
                "Admin adds to the list can change anything; everyone else can look and open files.\n\n"
                "Litterbox needs the internet to ask the host who you are."):
            return
        repo = self.repo()
        self.run_task(lambda: (people.setup_team(repo), people.current(repo, refresh=True))[1], "The team is set up",
                      on_success=self._team_changed)

    def _team_changed(self, who):
        self.identity = who
        self._show_identity()
        for child in self.winfo_children():
            if isinstance(child, TeamWindow) and child.winfo_exists():
                child.reload()

    def _stage(self, window, label, change, needs_owner=False):
        """Add a change to the Team window's unsaved changes. Returns "" if it was taken, else why not."""
        draft = window.draft
        if draft is None:
            return "The team isn't set up yet."
        try:
            draft.stage_people(label, change, needs_owner)
        except engine.LitterboxError as e:
            return logic.shorten(str(e))
        window.reload()
        return ""

    def edit_person(self, window, person_id, adding=False):
        if not self._may("manage_people"):
            return
        directory = window.draft.directory if window.draft is not None else self.identity.directory
        person = None if adding else (directory.get(person_id) if person_id else None)
        if person is None and not adding:
            self._say("Select a person first.", "warn")
            return

        def apply(fields):
            if person is None:
                new_id = fields.pop("id")
                return self._stage(window, f"Add {fields['name']}",
                                   lambda d, who: people.add_person(d, who, new_id, **fields))
            if logic.person_unchanged(person, fields):
                return ""
            pid = person.id
            return self._stage(window, f"Edit {person.name}", lambda d, who: people.update_person(d, who, pid, **fields))

        PersonDialog(window, person, directory.roles, [p.id for p in directory.people],
                     self.identity.access == people.OWNER, apply=apply).show()

    def toggle_person(self, window, person_id):
        if not self._may("manage_people"):
            return
        person = window.draft.directory.get(person_id) if person_id and window.draft is not None else None
        if person is None:
            self._say("Select a person first.", "warn")
            return
        turn_on, pid = not person.active, person.id
        problem = self._stage(window, f"Switch {'on' if turn_on else 'off'} {person.name}",
                              lambda d, who: people.set_active(d, who, pid, turn_on))
        if problem:
            messagebox.showwarning("Team", problem, parent=window)

    def edit_roles(self, window):
        if not self._may("manage_people") or window.draft is None:
            return
        directory = window.draft.directory
        RolesDialog(window, directory.roles, lambda role: people.holders_of(window.draft.directory, role),
                    apply=lambda roles: self._stage(window, "Roles", lambda d, who: people.set_roles(
                        d, who, roles, scrub=True))).show()

    def transfer_owner(self, window, person_id):
        if not self._may("transfer_owner"):
            return
        person = window.draft.directory.get(person_id) if person_id and window.draft is not None else None
        if person is None:
            self._say("Select the person who will become the Owner.", "warn")
            return
        if not messagebox.askokcancel(
                "Transfer ownership",
                f"Make {person.name} the Owner? You will become an Admin, and only {person.name} will be able to "
                "hand ownership on again.\n\nThis takes effect when you press Save.", parent=window):
            return
        pid = person.id
        problem = self._stage(window, f"{person.name} becomes the Owner",
                              lambda d, who: people.transfer_owner(d, who, pid), needs_owner=True)
        if problem:
            messagebox.showwarning("Team", problem, parent=window)

    def edit_workflow(self, window):
        if not self._may("manage_workflows") or window.draft is None:
            return
        draft = window.draft
        if not draft.directory.roles:
            messagebox.showinfo("Workflows", "This org has no roles yet. Add some in Team... > Roles first.",
                                parent=window)
            return

        def apply(ops, editor):
            wanted = editor.templates()
            notes = []
            for op in ops:
                if op["op"] == "set":
                    template = wanted[op["action"]][op["name"]]
                    notes += [f"{workflow.label_of(op['action'])} {op['name']}: {n}"
                              for n in workflow.role_warnings(template, draft.directory)]
            if notes and not messagebox.askyesno(
                    "Workflows", "\n".join(notes) + "\n\nUntil that is fixed a request will wait for an Admin "
                    "override. Keep this change anyway?", parent=window):
                return "Change the roles or the workflow, or press Cancel."

            def change(templates, _directory):
                workflow.apply_ops(templates, ops)

            try:
                draft.stage_workflow(logic.ops_label(ops), change)
            except engine.LitterboxError as e:
                return logic.shorten(str(e))
            window.reload()
            return ""

        WorkflowsDialog(window, draft.directory.roles, draft.templates, apply=apply).show()

    def save_team(self, window):
        """The Team window's Save: upload every staged change in one go."""
        draft = window.draft
        if draft is None or not draft.dirty:
            return
        repo = self.repo()

        def work():
            draft.save(repo)
            return people.current(repo, probe=False)

        self.run_task(work, "Saved the team changes", on_success=self._team_changed, refresh=False)

    def _run_batch(self, action, plan, func):
        repo = self.repo()
        self.run_task(
            lambda: logic.run_batch(plan.targets, lambda pn: func(repo, pn)),
            "", on_success=lambda result: self._after_batch(action, plan, result))

    def _after_batch(self, action, plan, result):
        done, failed = result
        self.note = logic.summary(action, len(done), len(failed), len(plan.skipped))
        self._say(self.note, "warn" if failed else "normal")
        if failed:
            messagebox.showerror("Litterbox", logic.shorten(
                "\n\n".join(f"{pn}: {message}" for pn, message in failed)))

        if action == "checkout":
            self._warn_open_files([path for _pn, r in done for path in r.changed_upstream])
        elif action in ("checkin", "save"):
            nothing = [str(pn) for pn, r in done if not r.uploaded]
            if nothing:
                messagebox.showinfo("Nothing to upload", "There were no changes to save in: " + ", ".join(nothing))
        elif action == "undo":
            left = [name for _pn, names in done for name in names]
            if left:
                messagebox.showinfo(
                    "New files kept",
                    "These new files were never uploaded, so they were left in your cad folder:\n\n  " +
                    "\n  ".join(left))

    def check_out(self):
        plan = self._plan("checkout")
        if plan:
            self._run_batch("checkout", plan, engine.checkout)

    def _ask_comment_and_check_in(self, action, plan, allow_unchanged=frozenset()):
        """Ask for a comment, then check in (or save progress on) the planned parts."""
        keep_lock = action == "save"
        comment = self._ask("Describe your changes:", "Save Progress" if keep_lock else "Check In")
        if comment is None:                                  # cancelled
            return
        comment = comment.strip() or "Update"
        reader = references.make_reader(log=lambda text: self.queue.put(("log", text)))
        self._run_batch(action, plan, lambda repo, pn: engine.checkin(
            repo, pn, comment, keep_lock=keep_lock, allow_unchanged=(pn in allow_unchanged),
            references_reader=reader))

    def _check_in(self, keep_lock):
        action = "save" if keep_lock else "checkin"
        plan = self._plan(action)
        if not plan:
            return
        if keep_lock:                       # saving progress with no changes just does nothing
            self._ask_comment_and_check_in(action, plan)
            return
        # Check In: first look for parts with nothing to upload, and ask before going ahead.
        repo = self.repo()
        self.run_task(
            lambda: [(pn, engine.change_report(repo, pn)) for pn in plan.targets], "",
            on_success=lambda reports: self._confirm_unchanged(plan, reports),
            refresh=False, is_refresh=True)

    def _confirm_unchanged(self, plan, reports):
        unchanged = logic.parts_without_changes(reports)
        if unchanged:
            dialog = ConfirmDialog(
                self, "No changes detected", "No changes were detected in these files:",
                logic.unchanged_lines(unchanged),
                note="Continue will still check the part in: the check-in is recorded in its log, "
                     "uploaded, and your lock is released. Cancel leaves everything as it is.",
                confirm_text="Continue")
            if not dialog.show():
                self._say("Check-in cancelled. Nothing was changed.", "warn")
                return
        self._ask_comment_and_check_in("checkin", plan, frozenset(pn for pn, _files in unchanged))

    def check_in(self):
        self._check_in(keep_lock=False)

    def save_progress(self):
        self._check_in(keep_lock=True)

    def undo_checkout(self):
        plan = self._plan("undo")
        if not plan:
            return
        if not messagebox.askyesno("Undo checkout", logic.undo_prompt(plan.targets)):
            return
        self._run_batch("undo", plan, engine.undo_checkout)

    def release(self):
        plan = self._plan("release")
        if not plan:
            return
        if self._workflow_start("release", plan) or not self._one_part_only("release", plan):
            return
        repo, pn = self.repo(), plan.targets[0]
        # Step 1: find out exactly what would be released. Step 2: ask. Step 3: do it.
        self.run_task(lambda: engine.release_plan(repo, pn), "Checked what a release would include",
                      on_success=lambda release_plan: self._confirm_release(repo, release_plan),
                      refresh=False)

    def _confirm_release(self, repo, release_plan):
        pn = release_plan.pn
        if not release_plan.ok:
            messagebox.showwarning(
                "Can't release yet",
                f"{pn} can't be released yet:\n\n" + "\n".join("- " + p for p in release_plan.problems))
            return
        if not messagebox.askokcancel(f"Release {pn}", logic.release_confirm_text(release_plan)):
            return
        self.run_task(lambda: engine.release(repo, pn), f"Released {pn}")

    def open_part(self, drawing=False):
        """Open the part's model, or (drawing=True) its drawing, in the program for that file type.

        If the part has both a released and a working revision, ask which one."""
        plan = self._plan("open_drawing" if drawing else "open")
        if not plan:
            return
        pn = plan.targets[0]
        row = self.rows_by_pn[pn]
        problem = logic.open_message(row, drawing)
        if problem:
            self._say(problem, "warn")
            return
        choices = logic.open_choices(row, drawing)
        if len(choices) == 1:
            rev = choices[0][0]
        else:
            rev = RevisionPickerDialog(self, pn, [(logic.revision_label(row, r), r) for r, _f in choices],
                                       "Open drawing of" if drawing else "Open").show()
            if rev is None:
                return
        if not drawing and self._offer_reference_review(pn, row, rev):
            return
        self._open_revision(pn, rev, drawing)

    def _offer_reference_review(self, pn, row, rev):
        """An assembly in work that uses out-of-date parts: offer to review them first. True if the review opened."""
        if row.kind not in ("ok", "mine", "unclaimed") or rev != row.revision:
            return False
        try:
            stale = [u for u in references.uses(self.repo(), pn, rev) if u.replaceable]
        except engine.LitterboxError:
            return False
        if not stale:
            return False
        if messagebox.askyesno("Parts out of date", logic.stale_open_text(pn, stale)):
            self._load_references(pn)
            return True
        return False

    def show_references(self):
        plan = self._plan("references")
        if plan:
            self._load_references(plan.targets[0])

    def _load_references(self, pn, window=None):
        """Open the References window for a part (or, with `window`, refresh the one that is already open)."""
        repo = self.repo()

        def load():
            records = references.load_records(repo)
            outdated = references.outdated_parts(repo, records)
            return (records[pn].name if pn in records else "", references.uses(repo, pn, None, records),
                    references.where_used(repo, pn, records), pn in outdated, [p for p in outdated if p != pn])

        def show(r):
            if window is not None and window.winfo_exists():
                window.show(r[0], r[1], r[2], r[3], r[4])
            else:
                ReferencesWindow(self, pn, r[0], r[1], r[2], self._replace_references,
                                 this_outdated=r[3], others_outdated=r[4],
                                 on_update=lambda win, pns: self._update_references(pn, pns, win))

        self.run_task(load, "", refresh=False, is_refresh=True, on_success=show)

    def _update_references(self, pn, pns, window):
        """Read the assemblies' files (starting SolidWorks if it is not running) and store what they use.
        The References window stays open and is refreshed when this finishes."""
        repo = self.repo()

        def work():
            try:
                results = references.rescan(repo, pns, log=lambda text: self.queue.put(("log", text)))
                return results, engine.get_status(repo), ""
            except Exception as e:                       # the window must be given back either way
                return None, None, str(e)

        def done(result):
            results, rows, error = result
            if error:
                if window.winfo_exists():
                    window.set_idle()
                messagebox.showerror("Update references", logic.shorten(error))
                return
            self._show_rows(rows)
            text, problems = logic.update_summary(results)
            if problems:
                messagebox.showwarning("Update references", text)
            self._load_references(pn, window)

        if not self.run_task(work, "Updated the lists of parts used", on_success=done, refresh=False):
            window.set_idle()

    def _replace_references(self, items):
        repo = self.repo()
        count = len({item.parent for item in items})
        if not messagebox.askokcancel(
                "Replace references",
                f"Point {count} assembl{'y' if count == 1 else 'ies'} at the latest released revision of the "
                "parts you ticked?\n\nAssemblies nobody has checked out are checked out, changed and checked "
                "back in. An assembly you already have checked out is changed in your copy and left for you to "
                "check in. Assemblies checked out by someone else are skipped."):
            return

        def done(results):
            text, problems = logic.replace_summary(results)
            (messagebox.showwarning if problems else messagebox.showinfo)("Replace references", text)

        self.run_task(lambda: references.replace_references(
            repo, items, log=lambda text: self.queue.put(("log", text))), "Updated references", on_success=done)

    def _open_revision(self, pn, rev, drawing=False):
        """Open one revision's model or drawing (used by the Open buttons and the History window)."""
        row = self.rows_by_pn.get(pn)
        files = logic.row_revisions(row).get(rev, []) if row else []
        path = opener.pick_drawing(files) if drawing else opener.pick_model(files)
        if path is None:
            self._say(f"{pn.short} Rev {rev} has no {'drawing' if drawing else 'file'}.", "warn")
            return
        try:
            opener.open_path(Path(self.repo()) / path, self.settings.get("open_with"))
        except engine.LitterboxError as e:
            messagebox.showwarning("Can't open", str(e))
            return
        self._say(f"Opening {PurePosixPath(path).name}...")

    def open_drawing(self):
        self.open_part(drawing=True)

    def edit_details(self):
        plan = self._plan("edit")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        row = self.rows_by_pn[pn]
        result = EditDetailsDialog(self, pn, row.name, row.description).show()
        if result is None:
            self._say("Nothing was changed.")
            return
        name, description = result
        self.run_task(lambda: engine.edit_details(repo, pn, name, description),
                      f"Updated the details of {pn}. Save Progress or Check In to upload them.")

    def revise(self):
        plan = self._plan("revise")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        self.run_task(lambda: revise.revise_plan(repo, pn), "Checked what a revision would create",
                      on_success=lambda revise_plan: self._confirm_revise(repo, revise_plan), refresh=False)

    def _confirm_revise(self, repo, revise_plan):
        pn = revise_plan.pn
        if not revise_plan.ok:
            messagebox.showwarning("Can't revise yet", logic.revise_problem_text(pn, revise_plan.problems))
            return
        reason = ReasonDialog(self, f"Revise {pn.short}", logic.revise_confirm_text(revise_plan),
                              "Why is it being revised? (a few words)", "Revise").show()
        if not reason:
            return
        self.pending_select = str(pn)
        self.run_task(lambda: revise.revise(repo, pn, reason, log=lambda text: self.queue.put(("log", text))),
                      f"Rev {revise_plan.new_revision} of {pn.short} is checked out to you")

    def cancel_revision(self):
        plan = self._plan("cancel_revision")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        self.run_task(lambda: revise.cancel_revision_plan(repo, pn), "Checked what cancelling would do",
                      on_success=lambda cancel_plan: self._confirm_cancel_revision(repo, cancel_plan),
                      refresh=False)

    def _confirm_cancel_revision(self, repo, cancel_plan):
        pn = cancel_plan.pn
        if not cancel_plan.ok:
            messagebox.showwarning("Can't cancel", logic.cancel_problem_text(pn, cancel_plan.problems))
            return
        reason = ReasonDialog(self, f"Cancel Rev {cancel_plan.revision} of {pn.short}",
                              logic.cancel_confirm_text(cancel_plan),
                              "Why is it being cancelled? (a few words)", "Cancel revision").show()
        if not reason:
            return
        self.pending_select = str(pn)
        self.run_task(lambda: revise.cancel_revision(repo, pn, reason, log=lambda text: self.queue.put(("log", text))),
                      f"Cancelled Rev {cancel_plan.revision} of {pn.short}")

    def make_cots(self):
        plan = self._plan("make_cots")
        if not plan:
            return
        if self._workflow_start("make_cots", plan) or not self._one_part_only("make_cots", plan):
            return
        repo, pn = self.repo(), plan.targets[0]
        self.run_task(lambda: engine.make_cots_plan(repo, pn), "Checked whether it can be made COTS",
                      on_success=lambda cots_plan: self._confirm_make_cots(repo, cots_plan),
                      refresh=False)

    def _confirm_make_cots(self, repo, cots_plan):
        pn = cots_plan.pn
        if not cots_plan.ok:
            messagebox.showwarning("Can't make COTS yet", logic.make_cots_problem_text(pn, cots_plan.problems))
            return
        if not messagebox.askokcancel(f"Make {pn} COTS",
                                      logic.make_cots_confirm_text(pn, cots_plan.name, cots_plan.files)):
            return
        self.run_task(lambda: engine.make_cots(repo, pn), f"{pn} is now a COTS part")

    def _ask_reason(self, text, title):
        """Ask for a reason. Returns None if cancelled or left blank (and says so)."""
        reason = self._ask(text, title)
        if reason is None:
            return None
        if not reason.strip():
            messagebox.showwarning(title, "A reason is required.")
            return None
        return reason.strip()

    def reopen(self):
        plan = self._plan("reopen")
        if not plan:
            return
        if self._workflow_start("reopen", plan) or not self._one_part_only("reopen", plan):
            return
        repo, pn = self.repo(), plan.targets[0]
        if self.rows_by_pn[pn].kind == "cots" and not messagebox.askyesno(
                "Unrelease COTS part", logic.reopen_cots_warning(pn)):
            return
        reason = self._ask_reason(f"Why is {pn} being unreleased?", "Unrelease")
        if reason:
            self.run_task(lambda: engine.reopen(repo, pn, reason), f"Unreleased {pn}")

    def void(self):
        plan = self._plan("void")
        if not plan:
            return
        if self._workflow_start("void", plan) or not self._one_part_only("void", plan):
            return
        repo, pn = self.repo(), plan.targets[0]
        problem = logic.void_problem(self.rows_by_pn[pn])
        if problem:
            messagebox.showwarning("Can't void", problem)
            return
        reason = self._ask_reason(f"Why is {pn} being voided?", "Void")
        if not reason:
            return
        if not messagebox.askyesno(
                "Void part",
                f"Void {pn}?\n\nIts number will never be used again, and it can't be checked out."):
            return
        self.run_task(lambda: engine.void(repo, pn, reason), f"Voided {pn}")

    def show_history(self, event=None):
        if event is not None and self.tree.identify_column(event.x) == "#1":
            return                                              # double-clicking a tick box isn't asking for history
        chosen = self._selected_pns("open")                    # the highlighted row, or the one selected part
        if len(chosen) != 1:
            self._say("Click one part to see its history.", "warn")
            return
        try:
            record = registry.load(self.repo(), chosen[0])
        except registry.RegistryError as e:
            messagebox.showerror("Litterbox", str(e))
            return
        row = self.rows_by_pn.get(chosen[0])
        HistoryWindow(self, record, logic.row_revisions(row) if row else {},
                      on_open=lambda rev, drawing, pn=chosen[0]: self._open_revision(pn, rev, drawing))


def main():
    if "--self-test" in sys.argv:                       # used by the release pipeline; opens no window
        import selftest
        after = sys.argv[sys.argv.index("--self-test") + 1:]
        sys.exit(selftest.run(after[0] if after else None, ASSETS_DIR))
    settings.append_log(f"Litterbox {version.display()} started")
    set_app_id()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App().mainloop()


if __name__ == "__main__":
    main()
