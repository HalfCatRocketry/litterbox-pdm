"""
window_chrome.py - how every Litterbox window looks on the desktop: dark title bar, the Litterbox
icon (white or black, from the assets folder, which PyInstaller unpacks to sys._MEIPASS in the built program), the
taskbar identity, and a short fade in and out.
"""

import os
import sys
from pathlib import Path

import customtkinter as ctk

from litterbox.gui.logic import icon_files


# The icons live in the "assets" folder next to this file. (When the program is later
# packaged into an .exe, PyInstaller unpacks them to sys._MEIPASS instead.)
ASSETS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"


# Which icon to use. The default is the white one. To switch, add a line
# "icon: black" to C:\Litterbox\settings.yaml.
ICON_SETTING = {"choice": icon_files.DEFAULT_ICON}

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
    icon = icon_files.find_icon(ASSETS_DIR, ICON_SETTING["choice"])
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
