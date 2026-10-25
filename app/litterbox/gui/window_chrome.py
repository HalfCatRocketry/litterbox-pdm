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


TITLE_BAR = 40             # room for the title bar and frame, which a window's size doesn't count (at 100%)
EDGE = 8                    # kept free around a window that has to shrink to fit (at 100%)
NO_LIMIT = 100000           # the desktop's size when it can't be told


def work_area(window):
    """(left, top, right, bottom) in screen pixels of the desktop the window is on, less the taskbar. On Windows,
    the monitor the window (or, before it shows, its parent) is on; elsewhere the whole screen."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class MonitorInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.GetAncestor.restype = wintypes.HWND
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            hwnd = user32.GetAncestor(wintypes.HWND(window.winfo_id()), 2)          # GA_ROOT
            monitor = user32.MonitorFromWindow(hwnd, 2)                               # MONITOR_DEFAULTTONEAREST
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if monitor and user32.GetMonitorInfoW(wintypes.HANDLE(monitor), ctypes.byref(info)):
                work = info.rcWork
                return work.left, work.top, work.right, work.bottom
        except Exception:
            pass
    try:
        return 0, 0, int(window.winfo_screenwidth()), int(window.winfo_screenheight())
    except Exception:                       # can't be told: no limit
        return 0, 0, NO_LIMIT, NO_LIMIT


def window_scaling(window):
    """How much CustomTkinter enlarges this window's size (the monitor's scaling); 1.0 if it can't be told."""
    try:
        value = float(ctk.ScalingTracker.get_window_scaling(window))
        return value if value > 0 else 1.0
    except Exception:
        return 1.0


def fitted(window, width, height, area=None):
    """(width, height) at 100%, made small enough that the window, title bar and all, fits on its desktop."""
    left, top, right, bottom = area or work_area(window)
    scale = window_scaling(window)
    room_w = int((right - left) / scale) - 2 * EDGE
    room_h = int((bottom - top) / scale) - TITLE_BAR - 2 * EDGE
    return max(min(width, room_w), 200), max(min(height, room_h), 150)


def set_size(window, width, height):
    """Give a window this size (at 100%), or less if the screen is too small for it."""
    width, height = fitted(window, width, height)
    window.geometry(f"{width}x{height}")


def min_size(window, width, height):
    """The smallest a window may be made (at 100%), but never more than fits on the screen."""
    window.minsize(*fitted(window, width, height))


def place_over(window, parent, width, height, down=3):
    """Size a window and put it over its parent: centred across, and a third (down=3) or a quarter (down=4) of the
    way down. It never starts above or left of the parent, and is made smaller and moved if that is what it takes to
    keep all of it, title bar to buttons, on the parent's desktop."""
    area = work_area(parent)
    width, height = fitted(window, width, height, area)
    scale = window_scaling(window)
    real_w, real_h = round(width * scale), round(height * scale)          # what the screen sees: x and y aren't scaled
    x = parent.winfo_rootx() + max((parent.winfo_width() - real_w) // 2, 0)
    y = parent.winfo_rooty() + max((parent.winfo_height() - real_h) // down, 0)
    left, top, right, bottom = area
    edge, title = round(EDGE * scale), round(TITLE_BAR * scale)
    x = max(left + edge, min(x, right - real_w - edge))
    y = max(top + edge, min(y, bottom - real_h - title - edge))
    window.geometry(f"{width}x{height}+{x}+{y}")
