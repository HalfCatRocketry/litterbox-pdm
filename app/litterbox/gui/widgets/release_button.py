"""
release_button.py - ReleaseButton: a button that acts when the mouse is RELEASED over it (like a
normal button), but still works when the window is busy redrawing. Plus the small mouse helpers it uses.
"""

import time

import customtkinter as ctk

from litterbox.user import settings


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
    Tk's release event was seen going missing, which made some clicks do nothing.

    The press and release are bound here on every part of the button (its canvas, text and image), replacing
    CustomTkinter's own release binding. CustomTkinter 6 binds only the release, and adds it to the text and image
    when it draws them, so _draw binds them again afterwards: otherwise the text in the middle clicked one way and
    the rest of the button (the canvas) another, and only the middle worked."""

    _armed = False
    _pressed_at = 0.0
    WATCH_MS = 15
    GIVE_UP_SECONDS = 30

    def _create_bindings(self, sequence=None):
        super()._create_bindings(sequence)
        self._bind_parts(sequence)

    def _draw(self, *args, **kwargs):
        result = super()._draw(*args, **kwargs)
        self._bind_parts()                               # the text and image may have just been made
        return result

    def _bind_parts(self, sequence=None):
        for part in (getattr(self, "_canvas", None), getattr(self, "_text_label", None),
                     getattr(self, "_image_label", None)):
            if part is None:
                continue
            if sequence is None or sequence == "<Button-1>":
                part.bind("<Button-1>", self._pressed)
            if sequence is None or sequence == "<ButtonRelease-1>":
                part.bind("<ButtonRelease-1>", self._released)

    def _pressed(self, event=None):                      # the mouse button went down: just remember it
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
            self.invoke()
        else:
            click_log(f"release '{self._label()}' ignored: mouse moved off the button")
